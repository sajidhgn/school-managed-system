"""`amount_in_words` -- the line that defends a challan's total against a pen.

WHY THIS IS TESTED AT ALL, GIVEN IT ONLY PRINTS WORDS
    A challan is reconciled at a bank counter by comparing the figure with the words.
    If the two ever disagree, the clerk's correct response is to refuse the payment,
    and the school finds out as a queue of parents who could not pay. So the failure
    mode is not "an ugly string" -- it is a day of uncollected fees, which is worth a
    table of cases.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.common.money import amount_in_words


@pytest.mark.parametrize(
    ("amount", "words"),
    [
        # The sample challan this layout was built from.
        ("5100", "Five Thousand One Hundred Only"),
        ("1700", "One Thousand Seven Hundred Only"),
        # Zero is a real total: a fully concessioned student still gets a challan, and
        # a blank line there reads as a rendering bug to the office.
        ("0", "Zero Only"),
        # The irregular English teens, and the tens that are not.
        ("13", "Thirteen Only"),
        ("20", "Twenty Only"),
        ("99", "Ninety Nine Only"),
        # A hundred with nothing after it must not trail an empty word.
        ("100", "One Hundred Only"),
        ("101", "One Hundred One Only"),
        # THE SOUTH ASIAN SCALE, which is the whole reason this is not a library
        # call: a clerk in Lahore says "one lakh", not "one hundred thousand".
        ("100000", "One Lakh Only"),
        ("1000000", "Ten Lakh Only"),
        ("10000000", "One Crore Only"),
        (
            "1234567",
            "Twelve Lakh Thirty Four Thousand Five Hundred Sixty Seven Only",
        ),
        # Paisa, which a percentage concession can produce.
        ("1700.25", "One Thousand Seven Hundred and Twenty Five Paisa Only"),
        # A credit note is a real document, so a negative is spelled, not refused.
        ("-300", "Minus Three Hundred Only"),
    ],
)
def test_amounts_are_spelled_for_a_pakistani_counter(amount: str, words: str) -> None:
    assert amount_in_words(Decimal(amount)) == words


def test_the_words_agree_with_the_printed_figure() -> None:
    """Rounded to two places FIRST.

    The challan prints `1,700.13` and the words must say the same thing. Spelling the
    unrounded value would put a third decimal in one and not the other, which is
    exactly the disagreement the words exist to make impossible.
    """
    assert amount_in_words(Decimal("1700.125")) == amount_in_words(Decimal("1700.13"))


def test_an_amount_past_the_scale_words_raises_rather_than_lying() -> None:
    """One kharab is the first figure the scale words cannot spell.

    Silently dropping the top group would print a total a hundredth of the real one,
    on a document whose entire purpose is to state the amount unambiguously.
    """
    with pytest.raises(ValueError):
        amount_in_words(Decimal(10) ** 11)
