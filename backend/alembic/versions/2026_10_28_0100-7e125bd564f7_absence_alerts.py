"""absence alerts: one-to-one WhatsApp messages to a parent when their child is absent

Revision ID: 7e125bd564f7
Revises: e5b7d9f1a3c5
Create Date: 2026-10-28 10:00:00+00:00

WHY THIS MIGRATION EXISTS
    When a whole-day register is submitted, each absent child's guardians can get a
    WhatsApp message from the campus's own number. That message goes to ONE PERSON,
    never the class group, and the outbox until now could only address a group.

WHAT CHANGES
    * `whatsapp_settings.absence_alerts_enabled` -- OFF for every campus. Messaging
      parents automatically is something a school turns on, not something it finds
      out it agreed to.
    * `whatsapp_messages.recipient_phone` -- E.164, set for a one-to-one message.
      `invite_code` becomes nullable, and a CHECK requires one of the two: a message
      with nowhere to go is a row the dispatcher can only fail.
    * `whatsapp_messages.dedupe_key` -- with a partial unique index per campus. An
      absence alert is keyed by date, child and guardian, so a register reopened and
      submitted again does not text the same parent twice.
    * `whatsapp_messages.kind` accepts `absence_alert`.

DOWNGRADE DELETES THE ALERTS
    Queued and sent absence alerts are removed: the older schema has no column to
    hold their recipient.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7e125bd564f7"
down_revision: str | None = "e5b7d9f1a3c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_settings",
        sa.Column(
            "absence_alerts_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    op.add_column("whatsapp_messages", sa.Column("recipient_phone", sa.String(20), nullable=True))
    op.add_column("whatsapp_messages", sa.Column("dedupe_key", sa.String(120), nullable=True))
    op.alter_column("whatsapp_messages", "invite_code", existing_type=sa.String(64), nullable=True)
    op.create_check_constraint(
        op.f("ck_whatsapp_messages_destination_present"),
        "whatsapp_messages",
        "invite_code IS NOT NULL OR recipient_phone IS NOT NULL",
    )
    op.create_index(
        "uq_whatsapp_messages_school_id_dedupe_key",
        "whatsapp_messages",
        ["school_id", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )

    op.drop_constraint(op.f("ck_whatsapp_messages_kind"), "whatsapp_messages", type_="check")
    op.create_check_constraint(
        op.f("ck_whatsapp_messages_kind"),
        "whatsapp_messages",
        "kind IN ('fee_notice', 'custom', 'diary', 'absence_alert')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM whatsapp_messages WHERE kind = 'absence_alert'")
    op.drop_constraint(op.f("ck_whatsapp_messages_kind"), "whatsapp_messages", type_="check")
    op.create_check_constraint(
        op.f("ck_whatsapp_messages_kind"),
        "whatsapp_messages",
        "kind IN ('fee_notice', 'custom', 'diary')",
    )

    op.drop_index("uq_whatsapp_messages_school_id_dedupe_key", table_name="whatsapp_messages")
    op.drop_constraint(
        op.f("ck_whatsapp_messages_destination_present"), "whatsapp_messages", type_="check"
    )
    op.alter_column(
        "whatsapp_messages", "invite_code", existing_type=sa.String(64), nullable=False
    )
    op.drop_column("whatsapp_messages", "dedupe_key")
    op.drop_column("whatsapp_messages", "recipient_phone")
    op.drop_column("whatsapp_settings", "absence_alerts_enabled")
