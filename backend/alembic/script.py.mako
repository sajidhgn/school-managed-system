"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

REVIEW CHECKLIST -- confirm before merging:
  [ ] Does downgrade() actually reverse upgrade()? Test it locally.
  [ ] New tenant table? It needs school_id NOT NULL + ENABLE ROW LEVEL SECURITY
      + a tenant_isolation POLICY. Autogenerate does NOT emit RLS statements --
      you must add them by hand (see the helpers in alembic/rls.py).
  [ ] Adding a NOT NULL column to a populated table? Use the three-step pattern:
      add nullable -> backfill -> set NOT NULL. A single-step add locks the table
      and fails on existing rows.
  [ ] Creating an index on a large table? Use postgresql_concurrently=True and
      set transaction_per_migration=False for that revision -- CREATE INDEX takes
      an exclusive lock that blocks writes for the duration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
