"""guardians: parent registry, phone identity, and the portal auth surface

Revision ID: e8a0c2b4d6f8
Revises: d7f9b1c3e5a7
Create Date: 2026-08-28 06:00:00+00:00

WHY THIS MIGRATION EXISTS
    `d7f9b1c3e5a7` closed three of the four foundation gaps and said explicitly why it
    left the fourth: the guardian aggregate needs a global identity that spans
    campuses and an OTP surface, which is a bigger design than a link table. This is
    that design.

    `students.guardian_name` / `guardian_phone` / `guardian_email` cannot express any
    of the four cases a parent portal is made of:

      * ONE GUARDIAN, N CHILDREN -- a father's number typed three times, changed once.
      * N GUARDIANS, ONE CHILD   -- mother, father, and the uncle who does the school
                                    run, with different rights at the gate.
      * ACROSS CAMPUSES          -- one child at the boys' school, one at the girls'.
                                    One person, one login.
      * NO EMAIL                 -- the staff identity surface is keyed on a globally
                                    unique email. Most guardians in the target market
                                    have none.

=============================================================================
FOUR TABLES, AND TWO OF THEM ARE DELIBERATELY OUTSIDE RLS
=============================================================================
    `guardians` and `guardian_students` are tenant-owned and get `setup_tenant_table()`
    like every other table in this schema.

    `guardian_identities` and `guardian_otp_codes` get `setup_platform_table()` --
    GRANT without a policy. That is an exception to the rule stated in
    `auth/models.py` ("every other table gets `setup_tenant_table()`, no exceptions"),
    and it is the SAME exception, for the same two reasons that put `users` outside
    tenancy:

      1. A CHICKEN-AND-EGG PROBLEM AT LOGIN. Evaluating a policy needs
         `app.current_org_id`, which comes from the token; minting a token needs the
         person found by phone first. At that moment the GUC is empty, and a policy
         comparing against an empty GUC matches ZERO rows -- so an RLS-protected
         identity table makes login structurally impossible.

      2. THE HUMAN GENUINELY SPANS ORGANIZATIONS. A parent with a child in two
         school groups is one person with one handset. An `organization_id` on their
         identity would force two accounts for one phone.

    WHAT PROTECTS THEM INSTEAD: neither table is ever enumerated. `guardian_identities`
    is reachable by primary key or by an exact E.164 match supplied by a caller who is
    about to have to prove control of that handset; `guardian_otp_codes` only by
    identity id. No endpoint lists either.

WHAT AUTOGENERATE WOULD NOT HAVE PRODUCED
    1. RLS on the two tenant tables, as always.

    2. FOUR PARTIAL UNIQUE INDEXES, none of which a `UniqueConstraint` can express:

           uq_guardian_identities_phone_active   one live identity per phone. Partial
                                                 on `deleted_at IS NULL` so a number
                                                 released when a family leaves can be
                                                 re-registered -- carriers recycle
                                                 Pakistani mobile numbers, and burning
                                                 one permanently would lock out a
                                                 future, unrelated parent.
           uq_guardians_organization_identity_active
                                                 one record per person per org.
           uq_guardian_students_primary_per_student
                                                 AT MOST ONE primary contact per
                                                 child. A plain
                                                 UNIQUE(student_id, is_primary_contact)
                                                 would instead allow one true AND one
                                                 false, and forbid a second
                                                 non-primary guardian entirely --
                                                 the opposite of the rule.

    3. `ck_guardian_identities_phone_is_e164`. The phone is a LOGIN IDENTIFIER, and
       an identifier with several spellings is not an identifier. The application
       normalises in `core/phone.py`; this constraint is what stops a seed script, an
       import or a support fix from writing `0300-1234567` and silently creating a
       second identity for a parent who then sees one of their two children.

    4. THE `sessions` REWORK. Guardians share the staff session table -- and therefore
       its rotation and reuse detection -- rather than getting a duplicate of the most
       security-sensitive logic in the system. Two nullable columns and a rewritten
       CHECK. See the note on that constraint below.

    5. THE PERMISSION BACKFILL. `guardian:portal` is new here; the other four
       `guardian:*` codes were already seeded by `d7f9b1c3e5a7` and are only
       re-categorised. `_PRINCIPAL_PERMISSIONS` is `ALL_CODES`, so without the
       backfill every principal provisioned before today would get a 403 on the two
       portal routes the moment this ships.

    6. THE `permissions_version` BUMP, so a warm Redis cache does not keep serving the
       pre-migration set and 403 the new routes for as long as it lives.

WHAT THIS MIGRATION DELIBERATELY DOES NOT DO
    It does not backfill `guardians` from `students.guardian_name/phone/email`, and it
    does not drop those columns. Backfilling would mint a portal LOGIN for every phone
    number a school ever typed into a free-text field -- including the ones that are a
    landline, a sibling's number, or a typo -- and a login handed to the wrong handset
    is not a data-quality problem, it is a disclosure. Schools migrate families
    deliberately, through the registry UI, and the legacy columns stay as the
    denormalised fallback until they have.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql
from alembic.rls import setup_platform_table, setup_tenant_table, teardown_tenant_table

revision: str = "e8a0c2b4d6f8"
down_revision: str | None = "d7f9b1c3e5a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The one genuinely new code. The other four `guardian:*` already exist; this
# migration only moves them into their own category, which is a cosmetic change to the
# role editor's grouping and not a grant.
_NEW_PERMISSIONS = (
    (
        "guardian:portal",
        "guardian",
        "portal",
        "Guardians",
        "Change a guardian's sign-in number or portal access.",
        "school",
        True,
    ),
)

_RECATEGORISED = (
    ("guardian:read", "Guardians", "View guardians and their linked students."),
    ("guardian:create", "Guardians", "Register guardians."),
    ("guardian:update", "Guardians", "Edit guardians and their student links."),
    ("guardian:delete", "Guardians", "Remove a guardian record."),
)

_TENANT_TABLES = ("guardians", "guardian_students")
_GLOBAL_TABLES = ("guardian_identities", "guardian_otp_codes")

# Reused across both tenant tables. `organization_id` CASCADEs from `organizations` so
# offboarding a tenant removes its family data in one statement -- the GDPR erasure
# path.
_RELATIONSHIP = sa.Enum(
    "father",
    "mother",
    "grandparent",
    "sibling",
    "uncle",
    "aunt",
    "legal_guardian",
    "other",
    name="relationship_type",
    native_enum=False,
    create_constraint=True,
    length=32,
)


def upgrade() -> None:
    # =====================================================================
    # 1. guardian_identities -- global, no tenant column. See the header.
    # =====================================================================
    op.create_table(
        "guardian_identities",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        # 20, not 32: E.164 caps at `+` plus 15 digits. A wider column would quietly
        # accept the un-normalised input this design depends on rejecting.
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("email", postgresql.CITEXT(), nullable=True),
        sa.Column(
            "preferred_locale",
            sa.String(length=10),
            server_default="en",
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "suspended",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_otp_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guardian_identities")),
        # See header item 3. The application normalises; this stops everything else.
        sa.CheckConstraint(
            r"phone ~ '^\+[1-9][0-9]{6,14}$'",
            name=op.f("ck_guardian_identities_phone_is_e164"),
        ),
    )
    op.create_index(op.f("ix_guardian_identities_status"), "guardian_identities", ["status"])
    op.create_index(
        op.f("ix_guardian_identities_deleted_at"), "guardian_identities", ["deleted_at"]
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_guardian_identities_phone_active "
        "ON guardian_identities (phone) WHERE deleted_at IS NULL"
    )

    # =====================================================================
    # 2. guardian_otp_codes -- global, for the same pre-authentication reason
    # =====================================================================
    op.create_table(
        "guardian_otp_codes",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "guardian_portal_login",
                "guardian_phone_change",
                name="purpose",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            server_default="guardian_portal_login",
            nullable=False,
        ),
        # 64 = SHA-256 hex. The plaintext code exists only in memory and in the SMS;
        # the digest is peppered with SECRET_KEY, so a database dump yields nothing
        # usable because the key is not in the database.
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ip", sa.String(length=45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["guardian_identities.id"],
            name=op.f("fk_guardian_otp_codes_identity_id_guardian_identities"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guardian_otp_codes")),
    )
    op.create_index(
        op.f("ix_guardian_otp_codes_identity_id"), "guardian_otp_codes", ["identity_id"]
    )
    # The verify hot path: newest live code for this identity and purpose.
    op.create_index(
        "ix_guardian_otp_codes_identity_purpose",
        "guardian_otp_codes",
        ["identity_id", "purpose", "created_at"],
    )
    # The purge job, and the per-day request quota, which counts rows in a window.
    op.create_index(op.f("ix_guardian_otp_codes_expires_at"), "guardian_otp_codes", ["expires_at"])

    # =====================================================================
    # 3. guardians -- the tenant-scoped record. NO `school_id`, on purpose.
    # =====================================================================
    #
    # Every other academic table here carries a NOT NULL `school_id`. This one does
    # not, and the omission is the design: the parent of two children at two campuses
    # is ONE record in the group, and duplicating them per campus recreates exactly the
    # problem this module exists to solve. Campus reachability is a property of the
    # LINK below, which does carry `school_id` because a student does.
    op.create_table(
        "guardians",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("identity_id", sa.UUID(), nullable=False),
        # NOT a scope key -- see the column docstring on the model. It closes the
        # window between creating a guardian and linking their first child, during
        # which a campus-scoped registrar would otherwise 404 on the record they just
        # created.
        sa.Column("registered_school_id", sa.UUID(), nullable=True),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("cnic", sa.String(length=32), nullable=True),
        sa.Column("occupation", sa.String(length=120), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("alternate_phone", sa.String(length=20), nullable=True),
        sa.Column("portal_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("notes", sa.String(length=1000), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_guardians_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        # RESTRICT, not CASCADE. An identity is only ever soft-deleted in practice, and
        # a hard delete that silently removed a school's entire parent contact list is
        # not a repair anyone would authorise.
        sa.ForeignKeyConstraint(
            ["identity_id"],
            ["guardian_identities.id"],
            name=op.f("fk_guardians_identity_id_guardian_identities"),
            ondelete="RESTRICT",
        ),
        # SET NULL, not the CASCADE every school-scoped table uses. Archiving a campus
        # must not delete a parent who still has a child at the other one; the record
        # simply stops being attributable to a campus and stays org-level, which is
        # what it always was.
        sa.ForeignKeyConstraint(
            ["registered_school_id"],
            ["schools.id"],
            name=op.f("fk_guardians_registered_school_id_schools"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guardians")),
    )
    op.create_index(op.f("ix_guardians_organization_id"), "guardians", ["organization_id"])
    op.create_index(op.f("ix_guardians_identity_id"), "guardians", ["identity_id"])
    op.create_index(
        op.f("ix_guardians_registered_school_id"), "guardians", ["registered_school_id"]
    )
    op.create_index(op.f("ix_guardians_deleted_at"), "guardians", ["deleted_at"])
    # One record per person per organization, over live rows only. Without it, two
    # clerks registering the same father a week apart produce two rows with half his
    # children hanging off each -- the denormalised state this module replaced.
    op.execute(
        "CREATE UNIQUE INDEX uq_guardians_organization_identity_active "
        "ON guardians (organization_id, identity_id) WHERE deleted_at IS NULL"
    )

    # =====================================================================
    # 4. guardian_students -- who this person is to which child
    # =====================================================================
    op.create_table(
        "guardian_students",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("guardian_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("relationship_type", _RELATIONSHIP, server_default="other", nullable=False),
        sa.Column("relationship_label", sa.String(length=60), nullable=True),
        sa.Column("is_primary_contact", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_emergency_contact", sa.Boolean(), server_default="false", nullable=False),
        # Every flag defaults to the SAFE value, not the convenient one. Handing a
        # child to an unauthorised adult is the worst outcome this table can produce.
        sa.Column("can_pickup", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("receives_notifications", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("can_view_results", sa.Boolean(), server_default="true", nullable=False),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_guardian_students_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_guardian_students_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["guardian_id"],
            ["guardians.id"],
            name=op.f("fk_guardian_students_guardian_id_guardians"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name=op.f("fk_guardian_students_student_id_students"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guardian_students")),
        sa.UniqueConstraint(
            "guardian_id", "student_id", name="uq_guardian_students_guardian_student"
        ),
        # Mirrors the service-layer check. The constraint is the guarantee; the service
        # provides the error message, because a raw violation reaches a clerk as a 500.
        sa.CheckConstraint(
            "relationship_type <> 'other' OR relationship_label IS NOT NULL",
            name=op.f("ck_guardian_students_other_relationship_needs_label"),
        ),
    )
    op.create_index(
        op.f("ix_guardian_students_organization_id"), "guardian_students", ["organization_id"]
    )
    op.create_index(op.f("ix_guardian_students_school_id"), "guardian_students", ["school_id"])
    op.create_index(op.f("ix_guardian_students_guardian_id"), "guardian_students", ["guardian_id"])
    op.create_index(op.f("ix_guardian_students_student_id"), "guardian_students", ["student_id"])
    op.create_index(op.f("ix_guardian_students_deleted_at"), "guardian_students", ["deleted_at"])
    # The notification fan-out: "every contactable guardian of these students".
    op.create_index(
        "ix_guardian_students_school_id_student_id",
        "guardian_students",
        ["school_id", "student_id"],
    )
    # See header item 2: exactly one primary contact per child, over live rows.
    op.execute(
        "CREATE UNIQUE INDEX uq_guardian_students_primary_per_student "
        "ON guardian_students (student_id) "
        "WHERE is_primary_contact IS TRUE AND deleted_at IS NULL"
    )

    # =====================================================================
    # 5. RLS -- two policies, two deliberate omissions
    # =====================================================================
    for table in _TENANT_TABLES:
        setup_tenant_table(table)
    for table in _GLOBAL_TABLES:
        # GRANT without a policy, and `setup_platform_table` rather than a bare
        # `grant_app_role` precisely so the omission reads as a decision. See the
        # header: an RLS-protected identity table makes phone login impossible.
        setup_platform_table(table)

    # =====================================================================
    # 6. sessions gains a third principal
    # =====================================================================
    op.add_column("sessions", sa.Column("guardian_identity_id", sa.UUID(), nullable=True))
    op.add_column("sessions", sa.Column("guardian_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_sessions_guardian_identity_id_guardian_identities"),
        "sessions",
        "guardian_identities",
        ["guardian_identity_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_sessions_guardian_id_guardians"),
        "sessions",
        "guardians",
        ["guardian_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(op.f("ix_sessions_guardian_identity_id"), "sessions", ["guardian_identity_id"])
    op.create_index(op.f("ix_sessions_guardian_id"), "sessions", ["guardian_id"])
    op.create_index(
        "ix_sessions_guardian_identity_id_revoked_at",
        "sessions",
        ["guardian_identity_id", "revoked_at"],
    )

    # THE CONSTRAINT REWRITE, and the reason it is not `a <> b <> c`.
    #
    # The old check was `(user_id IS NOT NULL) <> (platform_admin_id IS NOT NULL)`,
    # which reads as "exactly one" for two operands and stops meaning that for three:
    # with all three set, `true <> true <> true` evaluates to TRUE, so the chained form
    # would accept precisely the row this constraint exists to reject -- a session that
    # is simultaneously a member of staff, an operator and a parent, with whichever
    # branch of the refresh logic ran first deciding which. Counting is unambiguous.
    op.drop_constraint(op.f("ck_sessions_exactly_one_principal"), "sessions", type_="check")
    op.create_check_constraint(
        op.f("ck_sessions_exactly_one_principal"),
        "sessions",
        "(CASE WHEN user_id IS NOT NULL THEN 1 ELSE 0 END)"
        " + (CASE WHEN platform_admin_id IS NOT NULL THEN 1 ELSE 0 END)"
        " + (CASE WHEN guardian_identity_id IS NOT NULL THEN 1 ELSE 0 END) = 1",
    )
    # A guardian record may only be named by a session that belongs to a guardian.
    # Without this, `guardian_id` could be set on a staff session and the portal's
    # authorisation filter would read a value the staff surface put there.
    op.create_check_constraint(
        op.f("ck_sessions_guardian_id_requires_guardian_session"),
        "sessions",
        "guardian_id IS NULL OR guardian_identity_id IS NOT NULL",
    )

    # =====================================================================
    # 7. Permission catalog + backfill
    # =====================================================================
    #
    # Order matters: the catalog row must exist before `role_permissions` can
    # reference it (FK on `permissions.code`).
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

    # Cosmetic only: moves the four existing codes out of the "Students" group in the
    # role editor and into their own. No grant changes, so no version bump for these.
    for code, category, description in _RECATEGORISED:
        op.execute(
            sa.text(
                "UPDATE permissions SET category = :category, description = :description "
                "WHERE code = :code"
            ).bindparams(category=category, description=description, code=code)
        )

    # The principal holds the ENTIRE catalog by definition. Without this, every
    # principal created before today gets a 403 on both portal routes the moment this
    # ships -- a broken release, not a seed gap.
    op.execute(
        """
        INSERT INTO role_permissions (role_id, organization_id, permission_code)
        SELECT r.id, r.organization_id, 'guardian:portal'
          FROM roles r
         WHERE r.code = 'principal'
           AND r.is_system IS TRUE
        ON CONFLICT DO NOTHING
        """
    )

    # Deliberately NOT granted to teacher or accountant. Both already hold
    # `guardian:read` from the previous migration, which is what they need to phone a
    # parent. `guardian:portal` hands out a LOGIN, and neither role has any reason to.
    op.execute(
        """
        UPDATE roles
           SET permissions_version = permissions_version + 1
         WHERE is_system IS TRUE
           AND code = 'principal'
        """
    )


def downgrade() -> None:
    # Grants first: `role_permissions.permission_code` is RESTRICT, so the catalog row
    # cannot be removed while any role still references it.
    op.execute("DELETE FROM role_permissions WHERE permission_code = 'guardian:portal'")
    op.execute(
        "UPDATE roles SET permissions_version = permissions_version + 1 "
        "WHERE is_system IS TRUE AND code = 'principal'"
    )
    op.execute("DELETE FROM permissions WHERE code = 'guardian:portal'")

    # Restore the two-principal check BEFORE dropping the columns it would reference.
    op.drop_constraint(
        op.f("ck_sessions_guardian_id_requires_guardian_session"), "sessions", type_="check"
    )
    op.drop_constraint(op.f("ck_sessions_exactly_one_principal"), "sessions", type_="check")
    # Any guardian session is unrepresentable under the old constraint, so it has to
    # go. These are transient security artefacts, not business records -- the affected
    # parents simply sign in again.
    op.execute("DELETE FROM sessions WHERE guardian_identity_id IS NOT NULL")
    op.create_check_constraint(
        op.f("ck_sessions_exactly_one_principal"),
        "sessions",
        "(user_id IS NOT NULL) <> (platform_admin_id IS NOT NULL)",
    )

    op.drop_index("ix_sessions_guardian_identity_id_revoked_at", table_name="sessions")
    op.drop_index(op.f("ix_sessions_guardian_id"), table_name="sessions")
    op.drop_index(op.f("ix_sessions_guardian_identity_id"), table_name="sessions")
    op.drop_constraint(op.f("fk_sessions_guardian_id_guardians"), "sessions", type_="foreignkey")
    op.drop_constraint(
        op.f("fk_sessions_guardian_identity_id_guardian_identities"),
        "sessions",
        type_="foreignkey",
    )
    op.drop_column("sessions", "guardian_id")
    op.drop_column("sessions", "guardian_identity_id")

    for table in _TENANT_TABLES:
        teardown_tenant_table(table)

    op.execute("DROP INDEX IF EXISTS uq_guardian_students_primary_per_student")
    op.drop_table("guardian_students")
    op.execute("DROP INDEX IF EXISTS uq_guardians_organization_identity_active")
    op.drop_table("guardians")
    op.drop_table("guardian_otp_codes")
    op.execute("DROP INDEX IF EXISTS uq_guardian_identities_phone_active")
    op.drop_table("guardian_identities")
