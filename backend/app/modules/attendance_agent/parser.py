"""Reading "Nursery-A absent 12, 13, 15" without a model.

WHY A PARSER BEFORE THE MODEL
    Nearly every attendance message has one shape: a class, a status word, roll
    numbers. Reading that in code is instant, free, works while the model provider
    is down, and cannot misread "13" as "18". `agent.py` is the fallback for the
    rest ("12 and 13 didn't come", "also 17", "12 to 15 chutti").

STRICT ON PURPOSE
    The parser accounts for EVERY word of the message or gives up. A word it does
    not know may change the meaning -- "also", "not", "except", the "-" of a range
    -- and a parser that skipped it would produce a confident wrong register.
    Giving up costs one model call; guessing costs a child marked absent.

THE SHAPE IT READS
    [class] <status> <rolls> [<status> <rolls>]...
    [class] all present

    The class is everything before the first status word. Matching it to a real
    section is the conversation's job, against the teacher's own classes.
"""

from __future__ import annotations

import re

from app.modules.attendance.models import AttendanceStatus
from app.modules.attendance_agent.agent import AttendanceMark, AttendanceReading

# Several words meaning one thing, folded to a single token before reading.
_PHRASES: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), token)
    for pattern, token in (
        (r"\bg(?:h)?air\s*haa?zir\b", " absent "),
        (r"غیر\s*حاضر", " absent "),
        (r"\bhalf[\s-]*day\b", " halfday "),
        (r"\bon\s+leave\b", " leave "),
        (
            r"\b(?:all|everyone|everybody|sab|full\s+class)\s+(?:are\s+|is\s+)?"
            r"(?:present|haa?zir)\b",
            " allpresent ",
        ),
        (r"\bfull\s+attendance\b", " allpresent "),
        (
            r"\b(?:no|none|nobody|no\s+one|koi\s+nahi?)\s+(?:is\s+)?absent(?:s|ees?)?\b",
            " allpresent ",
        ),
        (r"سب\s*حاضر", " allpresent "),
    )
)

STATUS_WORDS: dict[str, AttendanceStatus] = {
    "absent": AttendanceStatus.ABSENT,
    "absents": AttendanceStatus.ABSENT,
    "absentee": AttendanceStatus.ABSENT,
    "absentees": AttendanceStatus.ABSENT,
    "abs": AttendanceStatus.ABSENT,
    "late": AttendanceStatus.LATE,
    "latecomer": AttendanceStatus.LATE,
    "latecomers": AttendanceStatus.LATE,
    # An authorised absence -- a leave application, a note from home -- is EXCUSED,
    # which leaves the percentage's denominator (see `AttendanceStatus`).
    "leave": AttendanceStatus.EXCUSED,
    "excused": AttendanceStatus.EXCUSED,
    "chutti": AttendanceStatus.EXCUSED,
    "chhutti": AttendanceStatus.EXCUSED,
    "chuti": AttendanceStatus.EXCUSED,
    "rukhsat": AttendanceStatus.EXCUSED,
    "چھٹی": AttendanceStatus.EXCUSED,
    "رخصت": AttendanceStatus.EXCUSED,
    "halfday": AttendanceStatus.HALF_DAY,
    "half": AttendanceStatus.HALF_DAY,
    "present": AttendanceStatus.PRESENT,
    "hazir": AttendanceStatus.PRESENT,
    "haazir": AttendanceStatus.PRESENT,
    "حاضر": AttendanceStatus.PRESENT,
}
ALL_PRESENT = "allpresent"

# Words that sit between roll numbers and mean nothing: "roll no 12 and 13".
_FILLER = frozenset(
    {
        "roll", "rolls", "rn", "no", "nos", "number", "numbers", "num", "student",
        "students", "is", "are", "was", "were", "and", "aur", "today", "aaj", "the",
        "hai", "hain", "نمبر", "اور",
    }
)  # fmt: skip
# Words that may surround the class name: "Attendance Nursery-A today: absent 4".
_CLASS_FILLER = frozenset({"attendance", "today", "todays", "aaj", "ki", "for", "of"})
# Punctuation allowed between roll numbers. NOT "-": "12-15" may be a range.
_SEPARATORS = frozenset(",;:&./#()+*_\n")

_TOKEN_RE = re.compile(r"[0-9]+|[a-z]+|[؀-ۿ]+|\S")
# Urdu/Arabic digits and punctuation as their Western forms: "۱۲، ۱۳" is "12, 13".
_URDU_FORMS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩،؛۔", "01234567890123456789,;.")  # noqa: RUF001


def fold(text: str) -> str:
    """Lower case, Western digits, multi-word phrases as single tokens."""
    folded = text.lower().translate(_URDU_FORMS)
    for pattern, token in _PHRASES:
        folded = pattern.sub(token, folded)
    return folded


def roll_key(roll: str) -> str:
    """How two roll numbers are compared: "07" is roll 7; "A12" is "a12"."""
    roll = roll.strip().lower()
    return str(int(roll)) if roll.isdigit() else roll


def _is_class_noise(token: str) -> bool:
    return token in _CLASS_FILLER or token in _SEPARATORS


def looks_like_attendance(text: str) -> bool:
    """Whether a message is a register, before anyone tries to read it.

    A status word AND (a number, or "all present"). "Ali was absent, send him the
    homework" -- a diary correction -- has the word but no number, and stays with
    the diary agent.
    """
    tokens = _TOKEN_RE.findall(fold(text))
    has_status = any(t in STATUS_WORDS or t == ALL_PRESENT for t in tokens)
    has_rolls = any(t.isdigit() or t == ALL_PRESENT for t in tokens)
    return has_status and has_rolls


def parse_attendance(text: str) -> AttendanceReading | None:
    """The message as an `AttendanceReading`, or None when it is not the usual shape."""
    folded = fold(text)
    matches = list(_TOKEN_RE.finditer(folded))
    first = next(
        (i for i, m in enumerate(matches) if m.group() in STATUS_WORDS or m.group() == ALL_PRESENT),
        None,
    )
    if first is None:
        return None

    # The class: what precedes the first status word, minus "attendance", "today"
    # and punctuation at either end. Kept as typed ("nursery-a") for the record.
    start, end = 0, first
    while start < end and _is_class_noise(matches[start].group()):
        start += 1
    while end > start and _is_class_noise(matches[end - 1].group()):
        end -= 1
    class_text = folded[matches[start].start() : matches[end - 1].end()] if start < end else ""

    marks: dict[str, AttendanceStatus] = {}
    all_present = False
    current: AttendanceStatus | None = None
    awaiting_rolls = False
    for match in matches[first:]:
        token = match.group()
        if token == ALL_PRESENT:
            if awaiting_rolls:
                return None
            all_present, current = True, None
        elif token in STATUS_WORDS:
            if awaiting_rolls:
                return None  # "absent late 12": which one did they mean?
            current, awaiting_rolls = STATUS_WORDS[token], True
        elif token.isdigit():
            if current is None:
                return None  # a number after "all present": "all present 12"?
            key = roll_key(token)
            if marks.get(key, current) is not current:
                return None  # the same child twice, two different ways
            marks[key] = current
            awaiting_rolls = False
        elif token in _FILLER or token in _SEPARATORS:
            continue
        else:
            return None
    if awaiting_rolls or not (marks or all_present):
        return None

    return AttendanceReading(
        is_attendance=True,
        class_label=class_text.strip() or None,
        class_choice=None,
        all_present=all_present,
        marks=[AttendanceMark(roll_number=roll, status=status) for roll, status in marks.items()],
    )
