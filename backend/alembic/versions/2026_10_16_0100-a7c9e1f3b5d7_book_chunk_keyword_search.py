"""book chunk keyword search: a generated tsvector beside each chunk's embedding

Revision ID: a7c9e1f3b5d7
Revises: f4b6d8e0a2c4
Create Date: 2026-10-16 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    "Ask the library" retrieves passages with hybrid search: pgvector finds text
    with the question's MEANING, full-text search finds its exact WORDS ("Newton's
    second law", "Exercise 3.4"), and the two rankings are fused. The keyword half
    needs an indexed tsvector. It is a STORED generated column, so PostgreSQL keeps
    it in step with `content` and the worker writes nothing new.

    Adding a stored generated column rewrites `book_chunks` once.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a7c9e1f3b5d7"
down_revision: str | None = "f4b6d8e0a2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "book_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
        ),
    )
    op.create_index(
        "ix_book_chunks_search_vector",
        "book_chunks",
        ["search_vector"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_book_chunks_search_vector", table_name="book_chunks")
    op.drop_column("book_chunks", "search_vector")
