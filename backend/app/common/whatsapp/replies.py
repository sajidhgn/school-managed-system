"""How a teacher answers the school's WhatsApp agents -- OK, CANCEL, a class name.

WHY THIS FILE EXISTS
    Two agents now talk to teachers on the school's number: the diary agent (a
    photo of the diary page) and the attendance agent ("Nursery-A absent 12, 13").
    Both end the same way -- the teacher sees a preview and answers OK or CANCEL --
    and both have to recognise a class however it is typed. Those words and that
    matching live here once, so "haan" confirms a diary exactly when it confirms a
    register, and "9-A" names the same class to both.
"""

from __future__ import annotations

import re

CONFIRM_WORDS = frozenset(
    {
        "ok", "okay", "k", "yes", "y", "post", "send", "post it", "send it", "ok post",
        "yes post", "done", "submit", "haan", "han", "ji", "jee", "theek hai", "thik hai",
        "👍", "✅", "اوکے", "جی", "ہاں",
    }
)  # fmt: skip
CANCEL_WORDS = frozenset(
    {"cancel", "no", "n", "stop", "discard", "delete", "nahi", "nahin", "❌", "نہیں"}
)

CLASS_COMMAND_RE = re.compile(r"^(?:class|grade|section)\b[\s:#-]*(.+)$", re.IGNORECASE)
"""`CLASS 5-A` -- the teacher correcting which class something is for."""

_LABEL_NOISE_RE = re.compile(r"\b(?:class|grade|section)\b|[^0-9a-z؀-ۿ]+")


def reply_word(text: str) -> str:
    """A short reply, reduced to what it says: `" OK! "` -> `"ok"`."""
    return text.strip().lower().strip(" .!?،۔")  # noqa: RUF001 -- Urdu punctuation


def norm_label(text: str) -> str:
    """A class label without the words and punctuation teachers vary.

    `Grade 9-A`, `grade 9a`, `9 A` and `9-A` are all `9a`.
    """
    return _LABEL_NOISE_RE.sub("", text.lower())
