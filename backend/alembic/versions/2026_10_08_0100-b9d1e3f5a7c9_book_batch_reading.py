"""book batch reading: a `reading` chapter status and the batch ids it waits on

Revision ID: b9d1e3f5a7c9
Revises: a8c0d2e4f6b8
Create Date: 2026-10-08 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    With `BOOKS_BATCH_READS` a chapter's scanned pages are read through OpenAI's
    Batch API, which answers within 24 hours rather than seconds. The chapter
    waits in the new `reading` status, and `read_batch` records which batches to
    collect when they finish. See `app/modules/books/jobs.py`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b9d1e3f5a7c9"
down_revision: str | None = "a8c0d2e4f6b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = ("empty", "uploaded", "queued", "processing", "ready", "needs_review", "failed")
_AFTER = ("empty", "uploaded", "queued", "reading", "processing", "ready", "needs_review", "failed")


def _status_check(values: Sequence[str]) -> None:
    # op.f(): the full name, already converted -- the naming convention would prefix it again.
    op.drop_constraint(op.f("ck_book_chapters_book_chapter_status"), "book_chapters", type_="check")
    listed = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint("book_chapter_status", "book_chapters", f"status IN ({listed})")


def upgrade() -> None:
    op.add_column(
        "book_chapters",
        sa.Column("read_batch", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    _status_check(_AFTER)


def downgrade() -> None:
    # A chapter mid-batch goes back to the queue; its batch result is abandoned.
    op.execute(
        "UPDATE book_chapters SET status = 'queued', locked_at = NULL WHERE status = 'reading'"
    )
    _status_check(_BEFORE)
    op.drop_column("book_chapters", "read_batch")
