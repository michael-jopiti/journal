"""Page colours selectable for each day, taken from ``.design/colors.jpeg``."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Color:
    id: str
    name: str
    bg: str  # page background
    fg: str  # text and rules, chosen for contrast on ``bg``


PALETTE: tuple[Color, ...] = (
    Color("paper", "Paper", "#F2F1EA", "#000000"),
    Color("red", "Red", "#FF4B3E", "#000000"),
    Color("pink", "Pink", "#F7B6D2", "#000000"),
    Color("lilac", "Lilac", "#E49BFF", "#000000"),
    Color("green", "Sage", "#8FB79A", "#000000"),
    Color("blue", "Sky", "#94B8D0", "#000000"),
    Color("yellow", "Yellow", "#FFEF4A", "#000000"),
    Color("salmon", "Salmon", "#F9A38A", "#000000"),
    Color("purple", "Violet", "#8E63E8", "#000000"),
    Color("grey", "Grey", "#D4D4D4", "#000000"),
    Color("black", "Black", "#000000", "#FFFFFF"),
)

DEFAULT_COLOR = PALETTE[0].id
COLORS_BY_ID = {c.id: c for c in PALETTE}
