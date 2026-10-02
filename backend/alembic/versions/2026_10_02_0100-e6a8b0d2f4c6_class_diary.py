"""class diary: daily homework per section and subject, plus diary permissions

Revision ID: e6a8b0d2f4c6
Revises: d5f7a9c1e3b5
Create Date: 2026-10-02 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    The storage behind the daily diary a section takes home: one row per section,
    date and subject, holding that subject's homework. See
    `app/modules/diary/models.py` for the modelling rationale.

THREE NEW PERMISSIONS, BACKFILLED
    `diary:read`, `diary:write`, `diary:manage`. Unlike exams these were not seeded
    ahead of the module, so existing roles need them granted here or the feature
    ships as a 403 for every organization that already exists:

        principal (system)   all three -- it holds the entire catalog by definition
        teacher   (system)   read + write -- the class/subject assignment, enforced in
                             the service, bounds what write reaches

    Custom roles are left alone: a customer who built "Head of Year" decides
    whether it writes the diary.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "e6a8b0d2f4c6"
down_revision: str | None = "d5f7a9c1e3b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, resource, action, category, description, min_scope, dangerous) -- must
# match `app/modules/rbac/catalog.py`.
_NEW_PERMISSIONS = (
    ("diary:read", "diary", "read", "Academics", "View class diaries.", "school", False),
    (
        "diary:write",
        "diary",
        "write",
        "Academics",
        "Write the diary for your own classes and subjects.",
        "school",
        False,
    ),
    (
        "diary:manage",
        "diary",
        "manage",
        "Academics",
        "Write any class's diary, assigned or not.",
        "school",
        False,
    ),
)

_GRANTS = (
    ("principal", ("diary:read", "diary:write", "diary:manage")),
    ("teacher", ("diary:read", "diary:write")),
)


def upgrade() -> None:
    op.create_table(
        "diary_entries",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("written_by_user_id", sa.UUID(), nullable=True),
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
            name=op.f("fk_diary_entries_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_diary_entries_school_id_schools"),
            ondelete="CASCADE",
        ),
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

    # Catalog rows first: `role_permissions.permission_code` references them.
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
        # Without the bump a warm permission cache keeps serving the old set and the
        # new grants appear only after it expires.
        op.execute(
            sa.text(
                "UPDATE roles SET permissions_version = permissions_version + 1 "
                "WHERE is_system IS TRUE AND code = :role_code"
            ).bindparams(role_code=role_code)
        )


def downgrade() -> None:
    codes = tuple(p[0] for p in _NEW_PERMISSIONS)
    # Grants first: `role_permissions.permission_code` is RESTRICT.
    op.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code IN :codes").bindparams(
            sa.bindparam("codes", value=codes, expanding=True)
        )
    )
    op.execute(
        "UPDATE roles SET permissions_version = permissions_version + 1 "
        "WHERE is_system IS TRUE AND code IN ('principal', 'teacher')"
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE code IN :codes").bindparams(
            sa.bindparam("codes", value=codes, expanding=True)
        )
    )

    teardown_tenant_table("diary_entries")
    op.drop_table("diary_entries")
