"""book batch embeddings: chunks may wait for their vector; the batch ids they wait on

Revision ID: c1e3a5b7d9f1
Revises: b9d1e3f5a7c9
Create Date: 2026-10-10 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    With `BOOKS_BATCH_EMBEDDINGS` a chapter's chunks are embedded through OpenAI's
    Batch API, which answers within 24 hours. The chapter is saved straight away
    -- pages, report, review -- with its chunks' `embedding` still NULL, and
    `book_chapters.embed_batch` records which batches to collect. Search skips a
    chunk until its vector arrives. See `app/modules/books/jobs.py`.

DOWNGRADE
    A chunk still waiting for its vector cannot satisfy NOT NULL, so it is
    deleted: that chapter keeps its pages but drops out of search until the
    agent is run on it again.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c1e3a5b7d9f1"
down_revision: str | None = "b9d1e3f5a7c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "book_chapters",
        sa.Column("embed_batch", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.alter_column("book_chunks", "embedding", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM book_chunks WHERE embedding IS NULL")
    op.alter_column("book_chunks", "embedding", nullable=False)
    op.drop_column("book_chapters", "embed_batch")
