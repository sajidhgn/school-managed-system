"""branding: theme colour and logo, organization-wide with per-campus override

Revision ID: a0c2e4f6b8d0
Revises: f9b1d3e5a7c9
Create Date: 2026-09-04 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    ID cards and report headers need to look like they came from THIS school, and a
    trust running several campuses states the requirement both ways in the same
    breath: "one brand everywhere" and "the girls' campus has its own crest". Both
    are true, so the schema holds branding twice:

      - `organizations.logo_url` / `organizations.theme_colors` -- the single brand
        every campus inherits by default. A one-campus client touches only this.

      - `schools.theme_colors` (joining the `schools.logo_url` that already existed)
        -- the per-campus override. NULL does not mean "no colours"; it means "use
        the organization's". Clearing an override is therefore a revert, not a
        deletion of branding.

    `theme_colors` is an ORDERED ARRAY of `#RRGGBB` strings, not one colour and not
    a JSONB blob: position is meaning (first is primary, second is secondary, and
    card designs read them by index), and `varchar(7)[]` lets the database refuse a
    novel that a JSONB column would swallow. The palette is inherited or overridden
    AS A WHOLE -- mixing one campus's primary with the trust's secondary produces
    combinations nobody chose.

    No `use_org_branding` flag: the NULL-means-inherit rule per field IS the flag,
    and it cannot drift out of step with the values the way a separate boolean can
    (flag says "individual", fields say nothing).

WHY NOTHING IS BACKFILLED
    Every organization starts unbranded and every school starts inheriting, which
    is exactly what NULL already says. Consumers fall back to the neutral default
    they render today.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a0c2e4f6b8d0"
down_revision: str | None = "f9b1d3e5a7c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("logo_url", sa.String(length=500), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("theme_colors", postgresql.ARRAY(sa.String(length=7)), nullable=True),
    )
    op.add_column(
        "schools",
        sa.Column("theme_colors", postgresql.ARRAY(sa.String(length=7)), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("schools", "theme_colors")
    op.drop_column("organizations", "theme_colors")
    op.drop_column("organizations", "logo_url")
