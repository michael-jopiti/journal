"""Read-side features built on saved entries: chart data, streaks and search.

Metrics are discovered from ``schema.SECTIONS``, so any new ``Kind.SCALE`` or
``Kind.NUMBER`` field gets a home-page chart without further code.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

from .schema import SCALE_MAX, SECTIONS, Field, Kind
from .storage import Entry

# SVG viewBox and inner padding used by the chart template.
WIDTH, HEIGHT, PAD = 600, 120, 8


@dataclass(frozen=True)
class Range:
    id: str
    label: str
    days: int  # length of the window, ending today
    bucket: int  # days averaged into one point; keeps long ranges legible


RANGES: tuple[Range, ...] = (
    Range("week", "Week", 7, 1),
    Range("month", "Month", 30, 1),
    Range("6months", "6 months", 182, 7),
    Range("year", "Year", 365, 7),
)
RANGES_BY_ID = {r.id: r for r in RANGES}
DEFAULT_RANGE = "week"


def window_start(rng: Range, today: date) -> date:
    return today - timedelta(days=rng.days - 1)


# ---------------------------------------------------------------- charts


def _y(value: float, lo: float, hi: float) -> float:
    """Map ``lo..hi`` to an SVG y coordinate (high values at the top)."""
    return round(PAD + (HEIGHT - 2 * PAD) * (1 - (value - lo) / (hi - lo)), 1)


def _path(points: list[tuple[float, float] | None]) -> str:
    """SVG path through ``points``, lifting the pen at gaps (``None``)."""
    d, pen_down = [], False
    for p in points:
        if p is None:
            pen_down = False
            continue
        d.append(f"{'L' if pen_down else 'M'}{p[0]} {p[1]}")
        pen_down = True
    return " ".join(d)


def _numeric_fields() -> Iterator[tuple[str, Field]]:
    for section in SECTIONS:
        for field in section.fields:
            if field.kind in (Kind.SCALE, Kind.NUMBER):
                yield section.id, field


def build_charts(entries: list[Entry], rng: Range, today: date) -> list[dict]:
    """One chart per numeric field: bucketed averages, SVG geometry and the window average.

    Scales are drawn on a fixed 1..5 axis; numbers (sleep, ...) from 0 to the largest average.
    """
    start = window_start(rng, today)
    by_date = {e["date"]: e for e in entries}
    buckets = [
        [start + timedelta(days=i + j) for j in range(rng.bucket) if i + j < rng.days]
        for i in range(0, rng.days, rng.bucket)
    ]
    charts = []
    for section_id, field in _numeric_fields():
        raw = [
            [by_date[d.isoformat()]["sections"][section_id][field.id] for d in b if d.isoformat() in by_date]
            for b in buckets
        ]
        avgs = [mean(v) if (v := [x for x in vals if x is not None]) else None for vals in raw]
        if field.kind is Kind.SCALE:
            lo, hi, axis = 1, SCALE_MAX, f"{field.low} ↓ / {field.high} ↑"
        else:
            lo, hi = 0, max(round(max((a for a in avgs if a is not None), default=1), 1), 1)
            axis = f"0 – {hi:g} {field.unit}"
        step = (WIDTH - 2 * PAD) / max(len(buckets) - 1, 1)
        points = [None if a is None else (round(PAD + i * step, 1), _y(a, lo, hi)) for i, a in enumerate(avgs)]
        answered = [x for vals in raw for x in vals if x is not None]
        charts.append(
            {
                "id": field.id,
                "label": field.label,
                "axis": axis,
                "path": _path(points),
                "dots": [p for p in points if p is not None],
                "average": round(mean(answered), 1) if answered else None,
                "count": len(answered),
            }
        )
    return charts


# ------------------------------------------------------- streaks and gaps


def streaks(days: set[date], today: date) -> tuple[int, int]:
    """(current, longest) runs of consecutive journaled days.

    The current streak stays alive until the end of today, so an empty
    today does not reset it.
    """
    one = timedelta(days=1)
    current, d = 0, today if today in days else today - one
    while d in days:
        current, d = current + 1, d - one
    longest = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev and d - prev == one else 1
        longest, prev = max(longest, run), d
    return current, longest


def day_strip(entries: list[Entry], rng: Range, today: date, first_day: date | None) -> tuple[list[dict], int]:
    """One cell per day of the window (``color`` is None for a gap) and the count of missed days.

    Days before the first ever entry, and today, are not counted as missed.
    """
    colors = {e["date"]: e["color"] for e in entries}
    start = window_start(rng, today)
    strip = [
        {"date": d.isoformat(), "color": colors.get(d.isoformat())}
        for d in (start + timedelta(days=i) for i in range(rng.days))
    ]
    missed = sum(1 for c in strip if c["color"] is None and first_day and first_day.isoformat() <= c["date"] < today.isoformat())
    return strip, missed


# ----------------------------------------------------------------- search

SNIPPET_CONTEXT = 50
MAX_HITS_PER_ENTRY = 5


def _texts(field: Field, value) -> Iterator[str]:
    """Searchable strings of one stored field value."""
    match field.kind:
        case Kind.SCALE | Kind.NUMBER:
            return
        case Kind.LIST | Kind.TAGS:
            yield from value
        case Kind.PHOTOS:
            yield from (p["caption"] for p in value)
        case _:
            yield value


def search(entries: Iterable[Entry], query: str, limit: int = 100) -> list[dict]:
    """Case-insensitive substring search over every text in ``entries`` (newest first).

    Each result: ``{"date", "color", "hits": [{"section", "field", "before", "match", "after"}]}``.
    """
    q = query.strip().lower()
    if not q:
        return []
    results = []
    for e in entries:
        hits = []
        for section in SECTIONS:
            for field in section.fields:
                for text in _texts(field, e["sections"][section.id][field.id]):
                    i = text.lower().find(q)
                    if i < 0:
                        continue
                    a, b = max(i - SNIPPET_CONTEXT, 0), i + len(q)
                    hits.append(
                        {
                            "section": section.title,
                            "field": field.label,
                            "before": ("…" if a else "") + text[a:i],
                            "match": text[i:b],
                            "after": text[b : b + SNIPPET_CONTEXT] + ("…" if b + SNIPPET_CONTEXT < len(text) else ""),
                        }
                    )
        if hits:
            results.append({"date": e["date"], "color": e["color"], "hits": hits[:MAX_HITS_PER_ENTRY]})
            if len(results) >= limit:
                break
    return results
