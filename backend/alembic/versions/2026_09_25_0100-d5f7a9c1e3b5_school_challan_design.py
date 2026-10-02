"""schools: the printed fee challan template an office designs

Revision ID: d5f7a9c1e3b5
Revises: c4e6a8b0d2f4
Create Date: 2026-09-25 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    The card design (b1d3f5a7c9e2) answered "what does our student card look like".
    This answers the same question for the other piece of paper a campus prints in
    bulk: the fee challan. Which detachable copies come off it, WHICH ACCOUNTS A
    PARENT MAY PAY INTO, which identifiers and contacts are on it, whether the total
    is spelled out, whether a signature block is left for the counter.

    The accounts are the part that could not stay in code. Every school collects
    through its own bank branch and its own wallet number, those numbers change, and
    a challan printed with the wrong one sends a family's money somewhere the school
    cannot reconcile it. That is a fact about a campus, so it lives on the campus row
    where the office can correct it without a deployment.

WHY JSONB AND NOT A COLUMN PER KNOB
    Same trade as `card_design`, for the same reason: the knob set is the part
    guaranteed to grow, the shape is validated by `ChallanDesignConfig` in the
    tenancy schemas, and every knob defaults to how the challan already rendered. A
    NULL row and an empty object both mean "the standard challan", so nothing is
    backfilled and no accounts are invented for a campus that never opened the
    designer -- a printed account number nobody entered is the one error here that
    costs real money.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5f7a9c1e3b5"
down_revision: str | None = "c4e6a8b0d2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schools",
        sa.Column("challan_design", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schools", "challan_design")
