"""What counts as the same book in the shared library (`books/catalog.py`)."""

from __future__ import annotations

import pytest

from app.modules.books.catalog import catalog_key, grade_key


@pytest.mark.parametrize(
    ("label", "key"),
    [
        ("Class 5", "5"),
        ("Grade V", "5"),
        ("Fifth", "5"),
        ("class five", "5"),
        ("5th", "5"),
        ("Std. 5", "5"),
        ("Year 5", "5"),
        ("Grade 10", "10"),
        ("Class X", "10"),
        # Not only a grade: kept as written, so it never merges with "Class 1".
        ("Prep I", "prep i"),
        ("O Level", "o level"),
        ("Class 10-A", "class 10 a"),
        ("Nursery", "nursery"),
    ],
)
def test_a_class_name_keys_as_its_grade_only_when_it_names_nothing_else(
    label: str, key: str
) -> None:
    assert grade_key(label) == key


def test_one_book_typed_two_ways_has_one_key() -> None:
    assert catalog_key("New Countdown-5", "OXFORD", "3rd Edition.", "Grade 9") == catalog_key(
        "new countdown 5", " oxford", "3rd edition", "Class IX"
    )
    # Diacritics and case aside, the words must match.
    assert catalog_key("Café Reader", "Gohar", "2024", "Class 2") == catalog_key(
        "CAFE READER", "gohar", "2024", "class two"
    )


def test_one_title_for_two_grades_is_two_books() -> None:
    assert catalog_key("Mathematics", "PTB", "2024", "Class 5") != catalog_key(
        "Mathematics", "PTB", "2024", "Class 6"
    )
    assert catalog_key("Mathematics", "PTB", "2024", "Class 5") != catalog_key(
        "Mathematics", "PTB", "2025", "Class 5"
    )
