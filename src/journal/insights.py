"""Aggregate scale answers (mood, energy, ...) over a time window for charting.

Metrics are discovered from ``schema.SECTIONS``, so any new ``Kind.SCALE``
field appears on the home page without further code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean

from .schema import SCALE_MAX, SECTIONS, Kind
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


def _y(value: float) -> float:
    """Map a 1..SCALE_MAX value to an SVG y coordinate (high values at the top)."""
    return round(PAD + (HEIGHT - 2 * PAD) * (1 - (value - 1) / (SCALE_MAX - 1)), 1)


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


def build_charts(entries: list[Entry], rng: Range, today: date) -> list[dict]:
    """One chart per scale field: bucketed averages, SVG geometry and the window average."""
    start = window_start(rng, today)
    by_date = {e["date"]: e for e in entries}
    buckets = [
        [start + timedelta(days=i + j) for j in range(rng.bucket) if i + j < rng.days]
        for i in range(0, rng.days, rng.bucket)
    ]
    charts = []
    for section in SECTIONS:
        for field in section.fields:
            if field.kind is not Kind.SCALE:
                continue
            raw = [
                [by_date[d.isoformat()]["sections"][section.id][field.id] for d in b if d.isoformat() in by_date]
                for b in buckets
            ]
            avgs = [mean(v) if (v := [x for x in vals if x is not None]) else None for vals in raw]
            step = (WIDTH - 2 * PAD) / max(len(buckets) - 1, 1)
            points = [None if a is None else (round(PAD + i * step, 1), _y(a)) for i, a in enumerate(avgs)]
            answered = [x for vals in raw for x in vals if x is not None]
            charts.append(
                {
                    "id": field.id,
                    "label": field.label,
                    "low": field.low,
                    "high": field.high,
                    "path": _path(points),
                    "dots": [p for p in points if p is not None],
                    "average": round(mean(answered), 1) if answered else None,
                    "count": len(answered),
                }
            )
    return charts
