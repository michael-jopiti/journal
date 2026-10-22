"""Journal structure: the single source of truth for what a daily entry contains.

The form, the validation and the stored JSON are all derived from ``SECTIONS``.
To add a prompt, add a ``Field`` here; nothing else needs to change.

Sections follow established psychological practice:

* Check-in      - mood tracking (self-monitoring in CBT / behavioural activation).
* Gratitude     - "three good things" (Seligman, positive psychology).
* The day       - expressive writing (Pennebaker): facts first, then feelings.
* Pictures      - a captioned photo as a memory anchor (photo-elicitation).
* Thought record - cognitive restructuring (Beck, CBT).
* Self-compassion - Kristin Neff's self-compassion practice.
* Tomorrow      - implementation intentions (Gollwitzer).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Kind(StrEnum):
    """How a field is rendered and validated."""

    TEXT = "text"  # free multi-line text -> str
    SCALE = "scale"  # integer 1..SCALE_MAX, or None when unanswered
    LIST = "list"  # fixed number of short text items -> list[str]
    PHOTOS = "photos"  # uploaded pictures -> list[{"file": str, "caption": str}]


SCALE_MAX = 5
MAX_TEXT_LENGTH = 20_000
MAX_CAPTION_LENGTH = 500
MAX_PHOTOS = 12


@dataclass(frozen=True)
class Field:
    id: str
    label: str
    kind: Kind = Kind.TEXT
    hint: str = ""
    count: int = 1  # number of items, only used by Kind.LIST
    low: str = ""  # scale end labels, only used by Kind.SCALE
    high: str = ""


@dataclass(frozen=True)
class Section:
    id: str
    title: str
    prompt: str
    fields: tuple[Field, ...]


SECTIONS: tuple[Section, ...] = (
    Section(
        "check_in",
        "Check-in",
        "How are you arriving today? Rate honestly, not ideally.",
        (
            Field("mood", "Mood", Kind.SCALE, low="Low", high="High"),
            Field("energy", "Energy", Kind.SCALE, low="Drained", high="Charged"),
            Field("stress", "Stress", Kind.SCALE, low="Calm", high="Tense"),
        ),
    ),
    Section(
        "gratitude",
        "Gratitude",
        "Three specific things that went well today. Add why they happened.",
        (Field("items", "Three good things", Kind.LIST, count=3),),
    ),
    Section(
        "day",
        "The day",
        "Write without editing. Facts first, then feelings.",
        (
            Field("what_happened", "What happened", hint="Events, people, decisions."),
            Field(
                "feelings",
                "What I felt",
                hint="Name each emotion. Note where you feel it in your body.",
            ),
        ),
    ),
    Section(
        "pictures",
        "Pictures",
        "Add a picture that holds the day. Caption it in a sentence.",
        (Field("photos", "Pictures", Kind.PHOTOS),),
    ),
    Section(
        "thought_record",
        "Thought record",
        "Examine one difficult thought. Skip on easy days.",
        (
            Field("situation", "Situation", hint="Where, when, with whom?"),
            Field("automatic_thought", "Automatic thought", hint="What went through your mind?"),
            Field("evidence_for", "Evidence for the thought"),
            Field("evidence_against", "Evidence against the thought"),
            Field("balanced_thought", "A more balanced thought"),
        ),
    ),
    Section(
        "self_compassion",
        "Self-compassion",
        "What would you say to a close friend in the same situation?",
        (Field("kind_words", "Words of kindness to myself"),),
    ),
    Section(
        "tomorrow",
        "Tomorrow",
        "Choose one intention. Use the form: when X happens, I will do Y.",
        (Field("intention", "One intention"),),
    ),
)
