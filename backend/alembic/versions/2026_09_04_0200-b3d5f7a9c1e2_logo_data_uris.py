"""logo columns to text: uploaded logos live inline as data URIs

Revision ID: b3d5f7a9c1e2
Revises: a0c2e4f6b8d0
Create Date: 2026-09-04 02:00:00+00:00

WHY THIS MIGRATION EXISTS
    The settings UI now accepts a logo as an uploaded image, not only a link.
    This deployment has no object store, and the frontend architecture keeps the
    API origin hidden from the browser (everything rides the BFF proxy), so a
    "served file" URL has nowhere to point. The upload therefore travels as a
    client-side-downscaled `data:image/...` URI and is stored inline -- which a
    varchar(500) cannot hold. Text it is; the size cap (300k chars) and the
    accepted shapes (`https?://` or `data:image/`) are enforced at the schema
    layer, where they can produce a 422 instead of a truncation.

WHY BOTH TABLES
    Branding resolves school-over-organization field by field, so whatever a
    logo value can be at one level it must be able to be at the other --
    otherwise "promote this campus's logo to the whole trust" would fail on a
    column width.

No data is rewritten: every existing value fits, text is a widening.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3d5f7a9c1e2"
down_revision: str | None = "a0c2e4f6b8d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "organizations",
        "logo_url",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "schools",
        "logo_url",
        existing_type=sa.String(length=500),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Narrowing truncates any stored data URI; there is no lossless downgrade
    # for a value wider than the old column. USING left(...) keeps the column
    # change itself from failing on such rows.
    op.execute("ALTER TABLE schools ALTER COLUMN logo_url TYPE varchar(500) USING left(logo_url, 500)")
    op.execute(
        "ALTER TABLE organizations ALTER COLUMN logo_url TYPE varchar(500) USING left(logo_url, 500)"
    )
