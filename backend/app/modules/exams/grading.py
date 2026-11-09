"""Turning a percentage into a grade on the campus scale.

Kept apart from the service so the parent portal, the result sheet and the tests all
grade with the one function -- two copies of "which band does 79.995 fall in" is how a
report card and a parent's phone come to disagree.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

from app.modules.exams.schemas import GradeBand

# The scale every campus starts on: the legacy Pakistani board scale (A+ at 80, pass
# at 33) that the printed result card has always used, so a campus that never opens
# the settings screen keeps the grades its cards already carried. A campus replaces it
# from Exams -> Grading scale, and "reset" returns here.
BOARD_SCALE: tuple[GradeBand, ...] = (
    GradeBand(min_percent=Decimal(80), grade="A+", remark="Excellent"),
    GradeBand(min_percent=Decimal(70), grade="A", remark="Very Good"),
    GradeBand(min_percent=Decimal(60), grade="B", remark="Good"),
    GradeBand(min_percent=Decimal(50), grade="C", remark="Satisfactory"),
    GradeBand(min_percent=Decimal(40), grade="D", remark="Fair"),
    GradeBand(min_percent=Decimal(33), grade="E", remark="Needs improvement"),
    GradeBand(min_percent=Decimal(0), grade="F", remark="Fail"),
)


def band_for(percentage: Decimal, bands: Sequence[GradeBand] | None) -> GradeBand | None:
    """The band `percentage` falls in (None only for an empty list).

    `bands` must be highest first (as stored). The percentage is compared exactly as
    printed -- already rounded to two places by the result sheet -- so a child shown
    79.99% is never graded as if they had 80.
    """
    if not bands:
        return None
    for band in bands:
        if percentage >= band.min_percent:
            return band
    return bands[-1]


def paper_percentage(obtained: Decimal, max_marks: int) -> Decimal:
    """One paper's percentage, rounded the way the sheet rounds the total."""
    return (obtained * 100 / max_marks).quantize(Decimal("0.01"))
