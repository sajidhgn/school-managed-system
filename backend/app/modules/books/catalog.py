"""What makes two uploads "the same book" in the shared library.

WHY THIS FILE EXISTS
    The library is shared by every school on the platform, and a book may be in it
    only once: the second school to own "New Countdown 5" adds the copy already
    there instead of uploading, paying for and indexing it again. Two schools never
    type a book identically, so the comparison is on a normalised key, stored in
    `books.catalog_key` under a unique index.

THE KEY
    title | publisher | version | grade, each case-folded with punctuation,
    diacritics and spacing ignored -- "New Countdown-5", "new countdown 5." and
    "NEW  COUNTDOWN 5" are one title.

    The grade is part of it because many boards print one title per grade
    ("Mathematics", Punjab Textbook Board, 2024). It comes from the uploading
    school's class name, and schools name the same grade differently, so a name
    that is only a grade -- "Class 5", "Grade V", "Five", "5th", "Std. 5" -- keys as
    the number. Anything else ("Prep I", "O Level") keys as its text: reading a
    number out of it could merge two different books, and then the second school
    could not add its own.

    `alembic/versions/*_shared_book_library.py` carries a frozen copy of these
    functions for its backfill; change both or neither.
"""

from __future__ import annotations

import re
import unicodedata

_NON_WORD = re.compile(r"[^\w]+")
_GRADE_WORDS = frozenset({"class", "grade", "standard", "std", "year", "level", "form"})
_NUMBER_WORDS = {
    word: number
    for number, words in enumerate(
        (
            ("one", "first", "i"),
            ("two", "second", "ii"),
            ("three", "third", "iii"),
            ("four", "fourth", "iv"),
            ("five", "fifth", "v"),
            ("six", "sixth", "vi"),
            ("seven", "seventh", "vii"),
            ("eight", "eighth", "viii"),
            ("nine", "ninth", "ix"),
            ("ten", "tenth", "x"),
            ("eleven", "eleventh", "xi"),
            ("twelve", "twelfth", "xii"),
        ),
        start=1,
    )
    for word in words
}
_ORDINAL = re.compile(r"^(\d{1,2})(st|nd|rd|th)?$")


def normalise(text: str) -> str:
    """Case, accents, punctuation and spacing removed: what a person would call the
    same words."""
    folded = unicodedata.normalize("NFKD", text).casefold()
    bare = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " ".join(_NON_WORD.sub(" ", bare).replace("_", " ").split())


def grade_key(label: str) -> str:
    """ "Class 5", "Grade V" and "Fifth" -> "5"; any other name -> its own text."""
    words = normalise(label).split()
    numbers: list[int] = []
    for word in words:
        if word in _GRADE_WORDS:
            continue
        if match := _ORDINAL.match(word):
            numbers.append(int(match.group(1)))
        elif word in _NUMBER_WORDS:
            numbers.append(_NUMBER_WORDS[word])
        else:
            return " ".join(words)
    return str(numbers[0]) if len(numbers) == 1 else " ".join(words)


def catalog_key(title: str, publisher: str, version: str, grade: str) -> str:
    return "|".join((normalise(title), normalise(publisher), normalise(version), grade_key(grade)))
