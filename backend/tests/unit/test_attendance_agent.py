"""The attendance agent's parser: what it reads, and -- as much -- what it refuses to.

The parser's one job beyond reading the usual message is to GIVE UP on anything it
might misread, so the model (or the teacher) gets the chance to. Most cases below
are refusals.
"""

from __future__ import annotations

import pytest

from app.common.whatsapp.replies import norm_label, reply_word
from app.modules.attendance.models import AttendanceStatus
from app.modules.attendance_agent.parser import looks_like_attendance, parse_attendance, roll_key

ABSENT = AttendanceStatus.ABSENT


def marks(text: str) -> tuple[str | None, bool, list[tuple[str, AttendanceStatus]]]:
    reading = parse_attendance(text)
    assert reading is not None, text
    return (
        reading.class_label,
        reading.all_present,
        [(m.roll_number, m.status) for m in reading.marks],
    )


def test_the_usual_message_is_read_without_a_model() -> None:
    assert marks("Nursery-A Absent roll numbers 12,13,15") == (
        "nursery-a",
        False,
        [("12", ABSENT), ("13", ABSENT), ("15", ABSENT)],
    )


@pytest.mark.parametrize(
    "text",
    [
        "nursery a: absent 12, 13 & 15",
        "Nursery-A absent 12 13 15",
        "Attendance Nursery-A today: absent 12 and 13, 15",
        "Nursery-A *absent* roll no 12, 13, 15.",
        "Nursery-A ghair hazir 12, 13, 15",
        "Nursery-A absent ۱۲، ۱۳، ۱۵",  # noqa: RUF001 -- Urdu digits and comma
    ],
)
def test_the_ways_teachers_type_it_read_the_same(text: str) -> None:
    _, all_present, read = marks(text)
    assert not all_present
    assert read == [("12", ABSENT), ("13", ABSENT), ("15", ABSENT)]


def test_several_statuses_in_one_message() -> None:
    assert marks("5B absent 3, 4 late 7 leave 9 half day 8")[2] == [
        ("3", ABSENT),
        ("4", ABSENT),
        ("7", AttendanceStatus.LATE),
        ("9", AttendanceStatus.EXCUSED),
        ("8", AttendanceStatus.HALF_DAY),
    ]
    assert marks("Prep chutti 2")[2] == [("2", AttendanceStatus.EXCUSED)]


def test_all_present_and_no_class() -> None:
    assert marks("Grade 5-B all present") == ("grade 5-b", True, [])
    assert marks("sab hazir") == (None, True, [])
    assert marks("No absent today, late 3") == (None, True, [("3", AttendanceStatus.LATE)])
    assert marks("absent 12, 13")[0] is None


@pytest.mark.parametrize(
    "text",
    [
        "Prep absent 12-15",  # a range? or 12 and 15? -- the model asks itself, not us
        "12, 13 absent",  # status after the numbers
        "Nursery-A also 17 absent",  # relative to a list on screen
        "Nursery-A absent 12 except 13",
        "Nursery-A absent 12 present 12",  # the same child two ways
        "Nursery-A absent late 12",  # which status do the numbers belong to?
        "Nursery-A absent 12 late",  # a status with no numbers after it
        "Nursery-A absent",  # no numbers at all: NEVER "everyone present"
        "all present 12",
    ],
)
def test_anything_it_might_misread_is_left_to_the_model(text: str) -> None:
    assert parse_attendance(text) is None


def test_a_register_is_told_apart_from_a_diary_correction() -> None:
    assert looks_like_attendance("Nursery-A absent 12, 13")
    assert looks_like_attendance("12 and 13 didn't come, 7 late")
    assert looks_like_attendance("sab hazir")
    assert not looks_like_attendance("Ali was absent, send him the homework")
    assert not looks_like_attendance("Maths is exercise 4.3 not 4.2")
    assert not looks_like_attendance("ok")


def test_roll_numbers_compare_without_leading_zeros() -> None:
    assert roll_key("07") == roll_key("7") == "7"
    assert roll_key(" A12 ") == "a12"


def test_class_labels_and_replies_compare_loosely() -> None:
    assert norm_label("Grade 9-A") == norm_label("9a") == norm_label("9 - A") == "9a"
    assert norm_label("Nursery-A") == norm_label("nursery a")
    assert reply_word(" OK! ") == "ok"
    assert reply_word("ہاں۔") == "ہاں"  # noqa: RUF001 -- Urdu full stop
