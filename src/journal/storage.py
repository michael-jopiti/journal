"""Entry validation and persistence.

Layout on disk: one JSON file per day, ``<data_dir>/YYYY-MM-DD.json``::

    {
      "date": "2026-10-23",
      "color": "yellow",
      "updated_at": "2026-10-23T21:04:11+00:00",
      "sections": {"check_in": {"mood": 4, ...}, "gratitude": {"items": ["", "", ""]}, ...}
    }

One file per day keeps writes tiny and atomic, diffs readable, and the whole
collection trivially loadable (``Store.entries()``, ``jq``, ``pandas.read_json``).
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .palette import COLORS_BY_ID, DEFAULT_COLOR
from .schema import MAX_CAPTION_LENGTH, MAX_PHOTOS, MAX_TEXT_LENGTH, SCALE_MAX, SECTIONS, Field, Kind

Entry = dict[str, Any]

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
# Image files are named <uuid hex>.<ext>; this is also what makes served paths safe.
IMAGE_NAME = re.compile(r"[0-9a-f]{32}\.(?:jpg|png|gif|webp)")


def sniff_image(data: bytes) -> str | None:
    """File extension for ``data`` judged by its magic bytes, or None if not a supported image.

    The client-supplied filename and content type are never trusted. SVG is
    deliberately unsupported: it can carry scripts.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def parse_date(value: str) -> date:
    """Parse a strict ``YYYY-MM-DD`` string. Raises ``ValueError`` otherwise."""
    if not _ISO_DATE.fullmatch(value):
        raise ValueError(f"invalid date: {value!r}")
    return date.fromisoformat(value)


def _clean_text(value: Any) -> str:
    return value[:MAX_TEXT_LENGTH] if isinstance(value, str) else ""


def _clean_field(field: Field, value: Any) -> Any:
    """Coerce untrusted input to the shape ``field`` declares."""
    match field.kind:
        case Kind.SCALE:
            ok = isinstance(value, int) and not isinstance(value, bool)
            return value if ok and 1 <= value <= SCALE_MAX else None
        case Kind.LIST:
            items = value if isinstance(value, list) else []
            items = items[: field.count] + [""] * (field.count - len(items))
            return [_clean_text(i) for i in items]
        case Kind.NUMBER:
            ok = (
                isinstance(value, int | float)
                and not isinstance(value, bool)
                and math.isfinite(value)
                and field.minimum <= value <= field.maximum
            )
            return value if ok else None
        case Kind.TAGS:
            chosen = {v for v in value if isinstance(v, str)} if isinstance(value, list) else set()
            return [o for o in field.options if o in chosen]
        case Kind.PHOTOS:
            items = value if isinstance(value, list) else []
            return [
                {"file": i["file"], "caption": _clean_text(i.get("caption"))[:MAX_CAPTION_LENGTH]}
                for i in items[:MAX_PHOTOS]
                if isinstance(i, dict) and isinstance(i.get("file"), str) and IMAGE_NAME.fullmatch(i["file"])
            ]
        case _:
            return _clean_text(value)


def empty_entry(day: date) -> Entry:
    """A blank entry in the canonical shape."""
    return clean_entry(day, {})


def clean_entry(day: date, raw: Any) -> Entry:
    """Build a canonical entry from untrusted ``raw``; unknown keys are dropped."""
    raw = raw if isinstance(raw, dict) else {}
    raw_sections = raw.get("sections")
    raw_sections = raw_sections if isinstance(raw_sections, dict) else {}
    sections: dict[str, dict[str, Any]] = {}
    for section in SECTIONS:
        raw_fields = raw_sections.get(section.id)
        raw_fields = raw_fields if isinstance(raw_fields, dict) else {}
        sections[section.id] = {f.id: _clean_field(f, raw_fields.get(f.id)) for f in section.fields}
    color = raw.get("color")
    return {
        "date": day.isoformat(),
        "color": color if color in COLORS_BY_ID else DEFAULT_COLOR,
        "updated_at": raw.get("updated_at") if isinstance(raw.get("updated_at"), str) else None,
        "sections": sections,
    }


class Store:
    """Directory-backed collection of daily entries."""

    def __init__(self, data_dir: str | os.PathLike[str]) -> None:
        self.data_dir = Path(data_dir)

    def _path(self, day: date) -> Path:
        return self.data_dir / f"{day.isoformat()}.json"

    def load(self, day: date) -> Entry:
        """Return the entry for ``day``; a blank one if none is saved yet."""
        try:
            raw = json.loads(self._path(day).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return empty_entry(day)
        return clean_entry(day, raw)

    def save(self, day: date, raw: Any) -> Entry:
        """Validate ``raw`` and write it atomically. Returns the stored entry."""
        entry = clean_entry(day, raw)
        entry["updated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Write to a temp file then rename, so a crash never leaves a half-written day.
        fd, tmp = tempfile.mkstemp(dir=self.data_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(entry, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self._path(day))
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return entry

    def image_dir(self, day: date) -> Path:
        return self.data_dir / "images" / day.isoformat()

    def save_image(self, day: date, data: bytes) -> str:
        """Store an uploaded image for ``day``; returns its file name. Raises ``ValueError`` if unsupported."""
        ext = sniff_image(data)
        if ext is None:
            raise ValueError("unsupported image type")
        name = uuid.uuid4().hex + ext
        self.image_dir(day).mkdir(parents=True, exist_ok=True)
        (self.image_dir(day) / name).write_bytes(data)
        return name

    def days(self) -> list[date]:
        """Dates that have a saved entry, newest first."""
        if not self.data_dir.is_dir():
            return []
        found = []
        for p in self.data_dir.glob("*.json"):
            try:
                found.append(parse_date(p.stem))
            except ValueError:
                continue  # ignore stray files
        return sorted(found, reverse=True)

    def entries(self, start: date | None = None, end: date | None = None) -> Iterator[Entry]:
        """Saved entries, newest first, optionally limited to ``start``..``end`` inclusive.

        Entry point for analysis features.
        """
        for day in self.days():
            if (start is None or day >= start) and (end is None or day <= end):
                yield self.load(day)
