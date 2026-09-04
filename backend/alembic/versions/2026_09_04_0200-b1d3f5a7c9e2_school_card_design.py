"""schools: the student ID card template a principal designs

Revision ID: b1d3f5a7c9e2
Revises: b3d5f7a9c1e2
Create Date: 2026-09-04 02:00:00+00:00

WHY THIS MIGRATION EXISTS
    Branding (a0c2e4f6b8d0) answered "whose colours and crest". This answers the
    question the office asks next: WHAT DOES OUR CARD LOOK LIKE -- where the logo
    sits, how the photo is framed, which lines print, whose phone number the
    "if found" line shows, whether a QR is included. Those are decisions a
    principal makes once for the whole campus, not per print, so they live on the
    school row rather than in whoever-printed-last's browser storage.

WHY JSONB AND NOT A COLUMN PER KNOB
    The knob set is the part guaranteed to grow (the shape is validated by
    `CardDesignConfig` in the tenancy schemas, where every knob has a default
    equal to the pre-feature rendering). A NULL row and an empty object both mean
    "the standard card", so nothing is backfilled and no design is invented for
    campuses that never opened the designer.

WHY PER CAMPUS WITH NO ORGANIZATION-LEVEL DEFAULT
    Unlike a palette, a card layout is operational, not brand: it follows the
    printer and pouch stock at a campus desk. An org-level layout would mostly be
    inherited accidentally, then "fixed" at the campus anyway.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b1d3f5a7c9e2"
down_revision: str | None = "b3d5f7a9c1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "schools",
        sa.Column("card_design", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schools", "card_design")
