"""attendance agent: teachers mark the register by WhatsApp ("Nursery-A absent 12, 13")

Revision ID: d4f6a8c0e2b4
Revises: c3e5a7b9d1f3
Create Date: 2026-10-17 03:00:00+00:00

WHY THIS MIGRATION EXISTS
    A teacher can now send the day's register to the school's WhatsApp number. The
    agent matches the roll numbers to names, shows them back, and submits the
    register when the teacher replies OK. See `app/modules/attendance_agent/`.

WHAT CHANGES
    * `attendance_chat_drafts` is created (RLS): one row per register sent, holding
      it between the message and the OK.
    * No permission is added: sending a register needs `attendance:mark`, the same
      code the web register needs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "d4f6a8c0e2b4"
down_revision: str | None = "c3e5a7b9d1f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "attendance_chat_drafts"
_STATUSES = ("needs_class", "awaiting_confirmation", "submitted", "cancelled", "failed")


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("teacher_user_id", sa.UUID(), nullable=True),
        sa.Column("reply_chat_id", sa.String(length=64), nullable=False),
        sa.Column("inbound_message_id", sa.String(length=160), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                *_STATUSES,
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("request_text", sa.Text(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("class_hint", sa.String(length=120), nullable=True),
        sa.Column("marks", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("resolved", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("class_label", sa.String(length=120), nullable=True),
        sa.Column("attendance_session_id", sa.UUID(), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f(f"fk_{_TABLE}_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f(f"fk_{_TABLE}_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["teacher_user_id"],
            ["users.id"],
            name=op.f(f"fk_{_TABLE}_teacher_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name=op.f(f"fk_{_TABLE}_section_id_sections"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["attendance_session_id"],
            ["attendance_sessions.id"],
            name=op.f(f"fk_{_TABLE}_attendance_session_id_attendance_sessions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        sa.UniqueConstraint(
            "school_id",
            "inbound_message_id",
            name="uq_attendance_chat_drafts_school_id_inbound_message_id",
        ),
    )
    op.create_index(op.f(f"ix_{_TABLE}_organization_id"), _TABLE, ["organization_id"])
    op.create_index(op.f(f"ix_{_TABLE}_school_id"), _TABLE, ["school_id"])
    op.create_index(op.f(f"ix_{_TABLE}_teacher_user_id"), _TABLE, ["teacher_user_id"])
    op.create_index(
        "ix_attendance_chat_drafts_school_id_teacher_status",
        _TABLE,
        ["school_id", "teacher_user_id", "status"],
    )
    setup_tenant_table(_TABLE)


def downgrade() -> None:
    teardown_tenant_table(_TABLE)
    op.drop_table(_TABLE)
