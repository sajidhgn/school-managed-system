"""whatsapp class groups: linked groups, monthly fee notice settings, outbox, permissions

Revision ID: f7b9c1e3a5d7
Revises: e6a8b0d2f4c6
Create Date: 2026-10-02 02:00:00+00:00

WHY THIS MIGRATION EXISTS
    Storage for posting to class parents' WhatsApp groups: which group belongs to
    which class, each campus's monthly fee-notice settings, and the outbox every post
    goes through. See `app/modules/whatsapp/models.py` for the modelling rationale.

ONE FEE NOTICE PER GROUP PER MONTH
    A partial unique index on `whatsapp_messages (group_id, period_label) WHERE
    kind = 'fee_notice'` -- the guard that makes the nightly pass safe to repeat.

THREE NEW PERMISSIONS, BACKFILLED
    principal  (system)  read + send + manage
    accountant (system)  read + send -- the fee reminder is the accountant's message
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "f7b9c1e3a5d7"
down_revision: str | None = "e6a8b0d2f4c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, resource, action, category, description, min_scope, dangerous) -- must
# match `app/modules/rbac/catalog.py`.
_NEW_PERMISSIONS = (
    (
        "whatsapp:read",
        "whatsapp",
        "read",
        "Communication",
        "View linked WhatsApp groups and sent messages.",
        "school",
        False,
    ),
    (
        "whatsapp:send",
        "whatsapp",
        "send",
        "Communication",
        "Send messages to class WhatsApp groups.",
        "school",
        False,
    ),
    (
        "whatsapp:manage",
        "whatsapp",
        "manage",
        "Communication",
        "Link class WhatsApp groups and configure the monthly fee notice.",
        "school",
        False,
    ),
)

_GRANTS = (
    ("principal", ("whatsapp:read", "whatsapp:send", "whatsapp:manage")),
    ("accountant", ("whatsapp:read", "whatsapp:send")),
)


def _tenant_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
    ]


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def _tenant_fks(table: str) -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f(f"fk_{table}_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f(f"fk_{table}_school_id_schools"),
            ondelete="CASCADE",
        ),
    ]


def _tenant_indexes(table: str) -> None:
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    op.create_index(op.f(f"ix_{table}_school_id"), table, ["school_id"])


def upgrade() -> None:
    # --- groups -----------------------------------------------------------
    op.create_table(
        "whatsapp_groups",
        *_tenant_columns(),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("invite_code", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("send_fee_notice", sa.Boolean(), nullable=False),
        *_timestamps(),
        *_tenant_fks("whatsapp_groups"),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
            name=op.f("fk_whatsapp_groups_class_id_classes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name=op.f("fk_whatsapp_groups_section_id_sections"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "school_id", "invite_code", name="uq_whatsapp_groups_school_id_invite_code"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_groups")),
    )
    _tenant_indexes("whatsapp_groups")
    op.create_index(op.f("ix_whatsapp_groups_class_id"), "whatsapp_groups", ["class_id"])
    op.create_index(op.f("ix_whatsapp_groups_section_id"), "whatsapp_groups", ["section_id"])
    setup_tenant_table("whatsapp_groups")

    # --- settings ---------------------------------------------------------
    op.create_table(
        "whatsapp_settings",
        *_tenant_columns(),
        sa.Column("fee_notice_enabled", sa.Boolean(), nullable=False),
        sa.Column("send_day", sa.Integer(), nullable=False),
        sa.Column("fee_template", sa.Text(), nullable=False),
        sa.Column("monthly_note", sa.Text(), nullable=True),
        *_timestamps(),
        *_tenant_fks("whatsapp_settings"),
        sa.CheckConstraint(
            "send_day BETWEEN 1 AND 28", name=op.f("ck_whatsapp_settings_send_day_in_month")
        ),
        sa.UniqueConstraint("school_id", name="uq_whatsapp_settings_school_id"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_settings")),
    )
    _tenant_indexes("whatsapp_settings")
    setup_tenant_table("whatsapp_settings")

    # --- outbox -----------------------------------------------------------
    op.create_table(
        "whatsapp_messages",
        *_tenant_columns(),
        sa.Column("group_id", sa.UUID(), nullable=True),
        sa.Column("group_name", sa.String(length=120), nullable=False),
        sa.Column("invite_code", sa.String(length=64), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "fee_notice",
                "custom",
                name="kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("period_label", sa.String(length=40), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "sent",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        *_timestamps(),
        *_tenant_fks("whatsapp_messages"),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["whatsapp_groups.id"],
            name=op.f("fk_whatsapp_messages_group_id_whatsapp_groups"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_whatsapp_messages_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_whatsapp_messages")),
    )
    _tenant_indexes("whatsapp_messages")
    op.create_index(op.f("ix_whatsapp_messages_group_id"), "whatsapp_messages", ["group_id"])
    op.create_index(
        op.f("ix_whatsapp_messages_created_by_user_id"),
        "whatsapp_messages",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_whatsapp_messages_status_created_at", "whatsapp_messages", ["status", "created_at"]
    )
    op.create_index(
        "ix_whatsapp_messages_school_id_created_at",
        "whatsapp_messages",
        ["school_id", "created_at"],
    )
    op.create_index(
        "uq_whatsapp_messages_group_id_period_label_fee_notice",
        "whatsapp_messages",
        ["group_id", "period_label"],
        unique=True,
        postgresql_where=sa.text("kind = 'fee_notice'"),
    )
    setup_tenant_table("whatsapp_messages")

    # --- permissions ------------------------------------------------------
    for code, resource, action, category, description, min_scope, dangerous in _NEW_PERMISSIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO permissions
                    (code, resource, action, category, description, min_scope, is_dangerous)
                VALUES (:code, :resource, :action, :category, :description, :min_scope, :dangerous)
                ON CONFLICT (code) DO UPDATE
                    SET category = EXCLUDED.category,
                        description = EXCLUDED.description,
                        min_scope = EXCLUDED.min_scope,
                        is_dangerous = EXCLUDED.is_dangerous
                """
            ).bindparams(
                code=code,
                resource=resource,
                action=action,
                category=category,
                description=description,
                min_scope=min_scope,
                dangerous=dangerous,
            )
        )

    for role_code, codes in _GRANTS:
        for code in codes:
            op.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (role_id, organization_id, permission_code)
                    SELECT r.id, r.organization_id, :code
                      FROM roles r
                     WHERE r.code = :role_code
                       AND r.is_system IS TRUE
                    ON CONFLICT DO NOTHING
                    """
                ).bindparams(code=code, role_code=role_code)
            )
        op.execute(
            sa.text(
                "UPDATE roles SET permissions_version = permissions_version + 1 "
                "WHERE is_system IS TRUE AND code = :role_code"
            ).bindparams(role_code=role_code)
        )


def downgrade() -> None:
    codes = tuple(p[0] for p in _NEW_PERMISSIONS)
    op.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code IN :codes").bindparams(
            sa.bindparam("codes", value=codes, expanding=True)
        )
    )
    op.execute(
        "UPDATE roles SET permissions_version = permissions_version + 1 "
        "WHERE is_system IS TRUE AND code IN ('principal', 'accountant')"
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE code IN :codes").bindparams(
            sa.bindparam("codes", value=codes, expanding=True)
        )
    )

    for table in ("whatsapp_messages", "whatsapp_settings", "whatsapp_groups"):
        teardown_tenant_table(table)
        op.drop_table(table)
