"""diary agent: WhatsApp photo -> class group, replacing the typed class diary

Revision ID: b8d0f2a4c6e8
Revises: a7c9e1f3b5d7
Create Date: 2026-10-16 02:00:00+00:00

WHY THIS MIGRATION EXISTS
    The typed diary (`diary_entries`, the Diary screen) is replaced by the diary
    agent: a teacher photographs the day's diary page and sends it to the school's
    WhatsApp number; the agent writes it in the campus's format and posts it to the
    class group once the teacher confirms. See `app/modules/diary_agent/models.py`.

WHAT CHANGES
    * `diary_entries` is DROPPED, with its rows. The downgrade recreates the empty
      table; the homework typed into it is not recoverable from here.
    * `diary:read|write|manage` are removed; `whatsapp:diary` is added and granted
      to every role that could write the diary (`diary:write` or `diary:manage`) --
      the seeded teacher role and any custom role built the same way -- plus the
      principal, which holds the whole catalog.
    * `diary_agent_settings` and `diary_drafts` are created (RLS).
    * `whatsapp_groups.chat_id`: the group's WhatsApp id for the WAHA gateway.
    * `whatsapp_messages.kind` accepts `diary`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "b8d0f2a4c6e8"
down_revision: str | None = "a7c9e1f3b5d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match `app/modules/rbac/catalog.py`.
_NEW_CODE = "whatsapp:diary"
_NEW_DESCRIPTION = "Post the class diary to parents' WhatsApp groups by sending a photo of it."
_OLD_PERMISSIONS = (
    ("diary:read", "read", "View class diaries."),
    ("diary:write", "write", "Write the diary for your own classes and subjects."),
    ("diary:manage", "manage", "Write any class's diary, assigned or not."),
)
_OLD_CODES = tuple(code for code, _, _ in _OLD_PERMISSIONS)

_DRAFT_STATUSES = (
    "reading",
    "needs_class",
    "awaiting_confirmation",
    "posted",
    "cancelled",
    "failed",
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


def _bump(codes: Sequence[str]) -> None:
    """Without the bump a warm permission cache keeps serving the old set."""
    op.execute(
        sa.text(
            "UPDATE roles SET permissions_version = permissions_version + 1 "
            "WHERE id IN (SELECT role_id FROM role_permissions WHERE permission_code IN :codes)"
        ).bindparams(sa.bindparam("codes", value=tuple(codes), expanding=True))
    )


def upgrade() -> None:
    # --- permissions: diary:* -> whatsapp:diary ----------------------------
    op.execute(
        sa.text(
            """
            INSERT INTO permissions
                (code, resource, action, category, description, min_scope, is_dangerous)
            VALUES (:code, 'whatsapp', 'diary', 'Communication', :description, 'school', FALSE)
            ON CONFLICT (code) DO UPDATE
                SET category = EXCLUDED.category,
                    description = EXCLUDED.description,
                    min_scope = EXCLUDED.min_scope,
                    is_dangerous = EXCLUDED.is_dangerous
            """
        ).bindparams(code=_NEW_CODE, description=_NEW_DESCRIPTION)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, organization_id, permission_code)
            SELECT DISTINCT r.id, r.organization_id, :code
              FROM roles r
             WHERE (r.is_system IS TRUE AND r.code = 'principal')
                OR EXISTS (SELECT 1 FROM role_permissions rp
                            WHERE rp.role_id = r.id
                              AND rp.permission_code IN ('diary:write', 'diary:manage'))
            ON CONFLICT DO NOTHING
            """
        ).bindparams(code=_NEW_CODE)
    )
    _bump((_NEW_CODE, *_OLD_CODES))
    # Grants first: `role_permissions.permission_code` is RESTRICT.
    op.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code IN :codes").bindparams(
            sa.bindparam("codes", value=_OLD_CODES, expanding=True)
        )
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE code IN :codes").bindparams(
            sa.bindparam("codes", value=_OLD_CODES, expanding=True)
        )
    )

    # --- the typed diary goes ------------------------------------------------
    teardown_tenant_table("diary_entries")
    op.drop_table("diary_entries")

    # --- WhatsApp: group ids for WAHA, and the diary outbox kind -------------
    op.add_column("whatsapp_groups", sa.Column("chat_id", sa.String(length=64), nullable=True))
    op.drop_constraint(op.f("ck_whatsapp_messages_kind"), "whatsapp_messages", type_="check")
    op.create_check_constraint(
        op.f("ck_whatsapp_messages_kind"),
        "whatsapp_messages",
        "kind IN ('fee_notice', 'custom', 'diary')",
    )

    # --- diary agent ---------------------------------------------------------
    op.create_table(
        "diary_agent_settings",
        *_tenant_columns(),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("entry_template", sa.String(length=500), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        *_timestamps(),
        *_tenant_fks("diary_agent_settings"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diary_agent_settings")),
        sa.UniqueConstraint("school_id", name="uq_diary_agent_settings_school_id"),
    )
    op.create_index(
        op.f("ix_diary_agent_settings_organization_id"),
        "diary_agent_settings",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_diary_agent_settings_school_id"), "diary_agent_settings", ["school_id"]
    )
    setup_tenant_table("diary_agent_settings")

    op.create_table(
        "diary_drafts",
        *_tenant_columns(),
        sa.Column("teacher_user_id", sa.UUID(), nullable=True),
        sa.Column("reply_chat_id", sa.String(length=64), nullable=False),
        sa.Column("inbound_message_id", sa.String(length=160), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                *_DRAFT_STATUSES,
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("diary_date", sa.Date(), nullable=True),
        sa.Column("class_hint", sa.String(length=120), nullable=True),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("group_id", sa.UUID(), nullable=True),
        sa.Column("class_label", sa.String(length=120), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("message_id", sa.UUID(), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        *_timestamps(),
        *_tenant_fks("diary_drafts"),
        sa.ForeignKeyConstraint(
            ["teacher_user_id"],
            ["users.id"],
            name=op.f("fk_diary_drafts_teacher_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["whatsapp_groups.id"],
            name=op.f("fk_diary_drafts_group_id_whatsapp_groups"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["whatsapp_messages.id"],
            name=op.f("fk_diary_drafts_message_id_whatsapp_messages"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diary_drafts")),
        sa.UniqueConstraint(
            "school_id",
            "inbound_message_id",
            name="uq_diary_drafts_school_id_inbound_message_id",
        ),
    )
    op.create_index(op.f("ix_diary_drafts_organization_id"), "diary_drafts", ["organization_id"])
    op.create_index(op.f("ix_diary_drafts_school_id"), "diary_drafts", ["school_id"])
    op.create_index(op.f("ix_diary_drafts_teacher_user_id"), "diary_drafts", ["teacher_user_id"])
    op.create_index(
        "ix_diary_drafts_school_id_teacher_status",
        "diary_drafts",
        ["school_id", "teacher_user_id", "status"],
    )
    op.create_index(
        "ix_diary_drafts_school_id_created_at", "diary_drafts", ["school_id", "created_at"]
    )
    setup_tenant_table("diary_drafts")


def downgrade() -> None:
    teardown_tenant_table("diary_drafts")
    op.drop_table("diary_drafts")
    teardown_tenant_table("diary_agent_settings")
    op.drop_table("diary_agent_settings")

    op.execute("DELETE FROM whatsapp_messages WHERE kind = 'diary'")
    op.drop_constraint(op.f("ck_whatsapp_messages_kind"), "whatsapp_messages", type_="check")
    op.create_check_constraint(
        op.f("ck_whatsapp_messages_kind"), "whatsapp_messages", "kind IN ('fee_notice', 'custom')"
    )
    op.drop_column("whatsapp_groups", "chat_id")

    # The typed diary's table comes back EMPTY, as `e6a8b0d2f4c6` created it.
    op.create_table(
        "diary_entries",
        *_tenant_columns(),
        sa.Column("section_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("written_by_user_id", sa.UUID(), nullable=True),
        *_timestamps(),
        *_tenant_fks("diary_entries"),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name=op.f("fk_diary_entries_section_id_sections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subjects.id"],
            name=op.f("fk_diary_entries_subject_id_subjects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["written_by_user_id"],
            ["users.id"],
            name=op.f("fk_diary_entries_written_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "section_id",
            "entry_date",
            "subject_id",
            name="uq_diary_entries_section_id_entry_date_subject_id",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diary_entries")),
    )
    op.create_index(op.f("ix_diary_entries_organization_id"), "diary_entries", ["organization_id"])
    op.create_index(op.f("ix_diary_entries_school_id"), "diary_entries", ["school_id"])
    op.create_index(op.f("ix_diary_entries_section_id"), "diary_entries", ["section_id"])
    op.create_index(op.f("ix_diary_entries_subject_id"), "diary_entries", ["subject_id"])
    op.create_index(
        op.f("ix_diary_entries_written_by_user_id"), "diary_entries", ["written_by_user_id"]
    )
    op.create_index(
        "ix_diary_entries_school_id_entry_date", "diary_entries", ["school_id", "entry_date"]
    )
    setup_tenant_table("diary_entries")

    # Permissions back: the old codes to whoever holds whatsapp:diary (read + write),
    # the principal all three -- as `e6a8b0d2f4c6` granted them.
    for code, action, description in _OLD_PERMISSIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO permissions
                    (code, resource, action, category, description, min_scope, is_dangerous)
                VALUES (:code, 'diary', :action, 'Academics', :description, 'school', FALSE)
                ON CONFLICT (code) DO NOTHING
                """
            ).bindparams(code=code, action=action, description=description)
        )
    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, organization_id, permission_code)
            SELECT rp.role_id, rp.organization_id, c.code
              FROM role_permissions rp
             CROSS JOIN (VALUES ('diary:read'), ('diary:write')) AS c(code)
             WHERE rp.permission_code = :new
            UNION
            SELECT r.id, r.organization_id, 'diary:manage'
              FROM roles r
             WHERE r.is_system IS TRUE AND r.code = 'principal'
            ON CONFLICT DO NOTHING
            """
        ).bindparams(new=_NEW_CODE)
    )
    _bump((_NEW_CODE, *_OLD_CODES))
    op.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code = :code").bindparams(
            code=_NEW_CODE
        )
    )
    op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=_NEW_CODE))
