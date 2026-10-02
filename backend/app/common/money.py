"""Money rendered as English words, for the line every challan and receipt carries.

WHY A PRINTED BILL SPELLS ITS OWN TOTAL
    The digits on a fee challan pass through a parent's hands, a bank counter and a
    school's cash box, and a figure written only in numerals can be altered with one
    pen stroke: 1,700 becomes 4,700 by closing the top of a 1. The words cannot be
    edited the same way, so the counter clerk reconciles the two and a tampered
    challan is caught at the moment it is presented rather than at month end.

    That is also why the words are generated here rather than typed by whoever is at
    the desk: a hand-written amount in words is exactly as trustworthy as the person
    holding the pen.

THE SOUTH ASIAN SCALE, DELIBERATELY
    Groups of lakh (100,000) and crore (10,000,000), because these words are read
    aloud at a counter in Pakistan. "Five Lakh" is what the clerk and the parent both
    say; "Five Hundred Thousand" would be technically correct and practically
    foreign. Below a lakh the two systems agree, which is where almost every school
    fee lands anyway.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_UNITS = (
    "Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
    "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
    "Seventeen", "Eighteen", "Nineteen",
)  # fmt: skip

_TENS = (
    "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety",
)  # fmt: skip

# Read right to left: the last three digits, then repeating two-digit groups. This is
# what makes 1,234,567 come out as "Twelve Lakh Thirty Four Thousand Five Hundred
# Sixty Seven" rather than as millions.
_SCALES = ("Thousand", "Lakh", "Crore", "Arab")

_MAX = Decimal(10) ** 11
"""One kharab -- the first amount the scale words above cannot spell. A fee challan
never reaches it; raising rather than silently dropping the top group is what keeps
that true, because a total spelled as a hundredth of itself is worse than no total."""


def amount_in_words(value: Decimal, *, fraction_unit: str = "Paisa") -> str:
    """Spell an amount: 5100 becomes "Five Thousand One Hundred Only".

    Rounds to two places first -- the words must agree with the printed figure, and
    the printed figure is rounded. A negative amount is spelled with a leading
    "Minus" rather than refused: a credit note is a real document.
    """
    amount = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "Minus " if amount < 0 else ""
    amount = abs(amount)
    if amount >= _MAX:
        raise ValueError(f"{value} is too large to spell.")

    rupees = int(amount)
    fraction = int((amount - rupees) * 100)

    words = _spell(rupees)
    if fraction:
        words = f"{words} and {_spell(fraction)} {fraction_unit}"
    return f"{sign}{words} Only"


def _spell(number: int) -> str:
    """A non-negative integer in South Asian grouping, with no scale word of its own."""
    if number < 100:
        return _spell_two(number)

    # The hundreds are peeled off first because they are the one group of THREE
    # digits; everything above them pairs off into lakh and crore.
    head, tail = divmod(number, 1000)
    parts: list[str] = []

    if head:
        for scale in _SCALES:
            head, group = divmod(head, 100)
            if group:
                parts.append(f"{_spell_two(group)} {scale}")
            if not head:
                break
        parts.reverse()

    if tail:
        hundreds, rest = divmod(tail, 100)
        if hundreds:
            parts.append(f"{_UNITS[hundreds]} Hundred")
        if rest:
            parts.append(_spell_two(rest))

    return " ".join(parts)


def _spell_two(number: int) -> str:
    """0-99. The teens are irregular in English, so they are a lookup, not a rule."""
    if number < 20:
        return _UNITS[number]
    tens, unit = divmod(number, 10)
    return f"{_TENS[tens]} {_UNITS[unit]}" if unit else _TENS[tens]
