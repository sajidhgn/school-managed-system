"""arabic test papers: allow 'ar' as a paper's and a question's language

Revision ID: c3e5a7b9d1f3
Revises: b2d4f6a8c0e2
Create Date: 2026-10-17 02:00:00+00:00

WHY THIS MIGRATION EXISTS
    `PaperLanguage` gained ARABIC. The language columns are VARCHAR with a CHECK
    listing the allowed values (`str_enum`), so the CHECK is replaced.

DOWNGRADE
    Arabic papers and questions cannot satisfy the narrower CHECK, so they are
    deleted first (a paper's entries go with it by cascade).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "c3e5a7b9d1f3"
down_revision: str | None = "b2d4f6a8c0e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKS = (
    ("questions", "ck_questions_question_language"),
    ("papers", "ck_papers_paper_language"),
)


def _replace(values: str) -> None:
    for table, name in _CHECKS:
        # Raw SQL: `op.drop_constraint` would prefix the naming convention again.
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK (language IN ({values}))")


def upgrade() -> None:
    _replace("'en', 'ur', 'ar'")


def downgrade() -> None:
    op.execute("DELETE FROM papers WHERE language = 'ar'")
    op.execute("DELETE FROM questions WHERE language = 'ar'")
    _replace("'en', 'ur'")
