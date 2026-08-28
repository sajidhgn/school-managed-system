"""academic foundation: calendar, curriculum, guardians, enrollment history, attendance

Revision ID: d7f9b1c3e5a7
Revises: c6e8f0a2b4d6
Create Date: 2026-08-28 05:00:00+00:00

WHY THIS MIGRATION EXISTS
    The students and academics modules shipped before the module checklist in
    `IMPLEMENTATION_ROADMAP.md` existed, and they are the foundation every deferred
    academic module hangs off. This migration closes the four gaps that were
    blocking the next tier:

        1. NO CALENDAR.   `academic_years` + `terms`. Attendance percentages and
                          report cards need a year's BOUNDS, which the free-text
                          `fees.academic_year` string cannot supply.
        2. NO CURRICULUM. `subjects` + `class_subjects`. The gradebook and the
                          timetable both index into a subject list that did not exist.
        3. NO HISTORY.    `student_enrollments`. `students.section_id` says where a
                          child is NOW; attendance for 12 March needs to know where
                          they were THEN.

    And then builds the first module on top of it: `attendance_sessions` +
    `attendance_records`.

    THE FOURTH GAP -- guardians -- IS NOT CLOSED HERE.
        `students.guardian_name` / `guardian_phone` / `guardian_email` still cannot
        express siblings, a portal login, or two guardians for one child, and that
        remains the blocker on the parent portal. The guardian aggregate is being
        built as its own module (`app/modules/guardians`) with its own migration,
        because a portal login needs a global identity that spans campuses and an
        OTP surface -- a bigger design than a link table, and one that should not be
        half-built here and reshaped there. The ten permission codes below still
        include `guardian:*`: the catalog is seeded ahead of its module on purpose
        (see `rbac/catalog.py`), so a principal can configure who will manage
        families before the screens exist.

THE FIVE THINGS AUTOGENERATE WOULD NOT HAVE PRODUCED
    1. RLS. Alembic has never emitted `ENABLE ROW LEVEL SECURITY` or a `CREATE
       POLICY`. All nine tables here are tenant-owned; every one gets
       `setup_tenant_table()`. Missing it on one silently exposes that table to
       every tenant.

    2. THREE PARTIAL UNIQUE INDEXES. `UniqueConstraint` cannot express a WHERE
       clause, so each is raw DDL with the rule it enforces stated next to it:

           uq_academic_years_one_current   one current year per school
           uq_student_enrollments_one_open one open enrollment per student
           uq_student_enrollments_roll     one roll number per section per year

    3. THE PERMISSION BACKFILL. Ten new codes. `_PRINCIPAL_PERMISSIONS` is
       `ALL_CODES`, so without it every principal provisioned before today would get
       a 403 on every new route the moment this ships. That is a data migration, not
       a seed-time concern.

    4. THE `permissions_version` BUMP. `core/cache.py` keys the cached permission set
       on `(role_id, permissions_version)`. Without the bump, a warm cache keeps
       serving the pre-migration set until it expires -- and the new routes 403 for
       exactly that long.

WHAT THIS MIGRATION DELIBERATELY DOES NOT DO
    * It does not backfill `student_enrollments`. An enrollment needs an academic
      year, and no school has one until it creates one. Existing students get their
      history opened by `POST /classes/academic-years/{id}/enrollments/backfill`,
      which is an explicit registrar action against an explicit year rather than a
      guess made by a migration.
    * It does not re-key `fees.academic_year` onto `academic_years.id`. That is a
      data migration on issued financial records, and nothing in this slice needs it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "d7f9b1c3e5a7"
down_revision: str | None = "c6e8f0a2b4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Created parents-first, dropped children-first.
_TABLES = (
    "academic_years",
    "terms",
    "subjects",
    "class_subjects",
    "student_enrollments",
    "attendance_sessions",
    "attendance_records",
)

# Kept in sync with `app/modules/rbac/catalog.py`; `make seed` upserts the same set,
# so a fresh database and an upgraded one converge on identical data.
_NEW_PERMISSIONS = (
    (
        "student:promote",
        "student",
        "promote",
        "Students",
        "Promote a class or section to the next academic year.",
        "school",
        True,
    ),
    (
        "guardian:read",
        "guardian",
        "read",
        "Students",
        "View guardians and family links.",
        "school",
        False,
    ),
    (
        "guardian:create",
        "guardian",
        "create",
        "Students",
        "Add guardians and link them to students.",
        "school",
        False,
    ),
    (
        "guardian:update",
        "guardian",
        "update",
        "Students",
        "Edit guardian details and family links.",
        "school",
        False,
    ),
    (
        "guardian:delete",
        "guardian",
        "delete",
        "Students",
        "Remove a guardian record.",
        "school",
        True,
    ),
    (
        "attendance:amend",
        "attendance",
        "amend",
        "Academics",
        "Reopen and correct a submitted attendance register.",
        "school",
        True,
    ),
    (
        "calendar:read",
        "calendar",
        "read",
        "Academics",
        "View academic years and terms.",
        "school",
        False,
    ),
    (
        "calendar:manage",
        "calendar",
        "manage",
        "Academics",
        "Define academic years and terms.",
        "school",
        False,
    ),
    (
        "subject:read",
        "subject",
        "read",
        "Academics",
        "View subjects and class curricula.",
        "school",
        False,
    ),
    (
        "subject:manage",
        "subject",
        "manage",
        "Academics",
        "Define subjects and assign them to classes.",
        "school",
        False,
    ),
)

_NEW_CODES = tuple(row[0] for row in _NEW_PERMISSIONS)

# What each seeded system role gains. The principal takes the whole catalog by
# definition; the other two take only what their job needs -- a teacher gets
# `guardian:read` so they can phone a parent about an absence, and explicitly not
# `attendance:amend`, which is the point of that code existing separately.
_TEACHER_CODES = ("guardian:read", "calendar:read", "subject:read")
_ACCOUNTANT_CODES = ("guardian:read", "calendar:read")


def _tenant_columns() -> list[sa.Column]:
    """`organization_id` (the RLS key) and `school_id` (the campus scope).

    Both NOT NULL on every table here: there is no organization-level academic year,
    guardian, enrollment or register. `organization_id` CASCADEs from `organizations`
    so offboarding a tenant removes its academic data in one statement, which is the
    GDPR erasure path.
    """
    return [
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
    ]


def _tenant_constraints(table: str) -> list[sa.schema.SchemaItem]:
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
    """Every RLS policy adds an implicit `WHERE organization_id = ...` to every query
    on the table, so this index sits on the hot path of literally every read."""
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    op.create_index(op.f(f"ix_{table}_school_id"), table, ["school_id"])


def _timestamps(*, soft_delete: bool) -> list[sa.Column]:
    columns = [
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
    if soft_delete:
        columns.append(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    return columns


def _pk() -> sa.Column:
    return sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _enum(*values: str, name: str) -> sa.Enum:
    """A VARCHAR + CHECK enum, matching `db/base.py::str_enum`.

    Deliberately NOT a native PostgreSQL ENUM: `ALTER TYPE ... ADD VALUE` is
    non-transactional and cannot be reversed in a downgrade, which makes adding an
    attendance status later a migration that can only go forwards.
    """
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def upgrade() -> None:
    # =====================================================================
    # 1. academic_years -- the calendar every later module indexes into
    # =====================================================================
    op.create_table(
        "academic_years",
        _pk(),
        *_tenant_columns(),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        *_timestamps(soft_delete=True),
        *_tenant_constraints("academic_years"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_academic_years")),
        sa.UniqueConstraint("school_id", "name", name="uq_academic_years_school_id_name"),
        sa.CheckConstraint("end_date > start_date", name=op.f("ck_academic_years_dates_ordered")),
    )
    _tenant_indexes("academic_years")
    op.create_index(op.f("ix_academic_years_deleted_at"), "academic_years", ["deleted_at"])
    op.create_index(
        "ix_academic_years_school_id_start_date", "academic_years", ["school_id", "start_date"]
    )
    # AT MOST ONE CURRENT YEAR PER SCHOOL. Partial, because every non-current year
    # shares `is_current = false` and a plain unique index would permit exactly one
    # of those per school -- the precise opposite of the intent.
    op.execute(
        "CREATE UNIQUE INDEX uq_academic_years_one_current "
        "ON academic_years (school_id) WHERE is_current AND deleted_at IS NULL"
    )

    # =====================================================================
    # 2. terms -- the reporting periods inside a year
    # =====================================================================
    op.create_table(
        "terms",
        _pk(),
        *_tenant_columns(),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        *_timestamps(soft_delete=True),
        *_tenant_constraints("terms"),
        sa.ForeignKeyConstraint(
            ["academic_year_id"],
            ["academic_years.id"],
            name=op.f("fk_terms_academic_year_id_academic_years"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_terms")),
        sa.UniqueConstraint(
            "academic_year_id", "sequence", name="uq_terms_academic_year_id_sequence"
        ),
        sa.UniqueConstraint("academic_year_id", "name", name="uq_terms_academic_year_id_name"),
        sa.CheckConstraint("end_date > start_date", name=op.f("ck_terms_dates_ordered")),
        sa.CheckConstraint("sequence >= 1", name=op.f("ck_terms_sequence_positive")),
    )
    _tenant_indexes("terms")
    op.create_index(op.f("ix_terms_deleted_at"), "terms", ["deleted_at"])
    op.create_index(op.f("ix_terms_academic_year_id"), "terms", ["academic_year_id"])

    # =====================================================================
    # 3. subjects -- the curriculum catalog
    # =====================================================================
    op.create_table(
        "subjects",
        _pk(),
        *_tenant_columns(),
        sa.Column("code", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", _enum("core", "elective", "activity", name="kind"), nullable=False),
        *_timestamps(soft_delete=True),
        *_tenant_constraints("subjects"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subjects")),
        sa.UniqueConstraint("school_id", "code", name="uq_subjects_school_id_code"),
        sa.UniqueConstraint("school_id", "name", name="uq_subjects_school_id_name"),
    )
    _tenant_indexes("subjects")
    op.create_index(op.f("ix_subjects_deleted_at"), "subjects", ["deleted_at"])

    # =====================================================================
    # 4. class_subjects -- which grade studies which subject
    # =====================================================================
    op.create_table(
        "class_subjects",
        _pk(),
        *_tenant_columns(),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("teacher_id", sa.UUID(), nullable=True),
        sa.Column("weekly_periods", sa.Integer(), nullable=True),
        *_timestamps(soft_delete=True),
        *_tenant_constraints("class_subjects"),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
            name=op.f("fk_class_subjects_class_id_classes"),
            ondelete="CASCADE",
        ),
        # RESTRICT: deleting a subject a grade still studies would silently strip it
        # from the curriculum. The service refuses and names the classes instead.
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subjects.id"],
            name=op.f("fk_class_subjects_subject_id_subjects"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["teacher_id"],
            ["users.id"],
            name=op.f("fk_class_subjects_teacher_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_class_subjects")),
        sa.UniqueConstraint("class_id", "subject_id", name="uq_class_subjects_class_id_subject_id"),
        sa.CheckConstraint(
            "weekly_periods IS NULL OR weekly_periods > 0",
            name=op.f("ck_class_subjects_weekly_periods_positive"),
        ),
    )
    _tenant_indexes("class_subjects")
    op.create_index(op.f("ix_class_subjects_deleted_at"), "class_subjects", ["deleted_at"])
    op.create_index(op.f("ix_class_subjects_class_id"), "class_subjects", ["class_id"])
    op.create_index(op.f("ix_class_subjects_subject_id"), "class_subjects", ["subject_id"])
    op.create_index(op.f("ix_class_subjects_teacher_id"), "class_subjects", ["teacher_id"])
    op.create_index(
        "ix_class_subjects_school_id_class_id", "class_subjects", ["school_id", "class_id"]
    )

    # =====================================================================
    # 5. student_enrollments -- where a student sat, and when
    # =====================================================================
    op.create_table(
        "student_enrollments",
        _pk(),
        *_tenant_columns(),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("roll_number", sa.String(length=16), nullable=True),
        sa.Column("enrolled_on", sa.Date(), nullable=False),
        sa.Column("left_on", sa.Date(), nullable=True),
        sa.Column("is_promotion", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(soft_delete=False),
        *_tenant_constraints("student_enrollments"),
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name=op.f("fk_student_enrollments_student_id_students"),
            ondelete="CASCADE",
        ),
        # RESTRICT on the year and the class: deleting either would erase the record
        # of an entire cohort's placement.
        sa.ForeignKeyConstraint(
            ["academic_year_id"],
            ["academic_years.id"],
            name=op.f("fk_student_enrollments_academic_year_id_academic_years"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
            name=op.f("fk_student_enrollments_class_id_classes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name=op.f("fk_student_enrollments_section_id_sections"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_enrollments")),
    )
    _tenant_indexes("student_enrollments")
    op.create_index(
        op.f("ix_student_enrollments_student_id"), "student_enrollments", ["student_id"]
    )
    op.create_index(
        op.f("ix_student_enrollments_academic_year_id"), "student_enrollments", ["academic_year_id"]
    )
    op.create_index(op.f("ix_student_enrollments_class_id"), "student_enrollments", ["class_id"])
    op.create_index(
        op.f("ix_student_enrollments_section_id"), "student_enrollments", ["section_id"]
    )
    op.create_index(
        "ix_student_enrollments_school_id_section_id",
        "student_enrollments",
        ["school_id", "section_id"],
    )
    op.create_index(
        "ix_student_enrollments_academic_year_id_class_id",
        "student_enrollments",
        ["academic_year_id", "class_id"],
    )
    # ONE OPEN ENROLLMENT PER STUDENT. `left_on IS NULL` is what "currently seated
    # here" means, and two of them would make "which section is this child in?"
    # ambiguous at the exact moment attendance asks it.
    op.execute(
        "CREATE UNIQUE INDEX uq_student_enrollments_one_open "
        "ON student_enrollments (student_id) WHERE left_on IS NULL"
    )
    # ONE ROLL NUMBER PER SECTION PER YEAR. Partial, so any number of unnumbered
    # enrollments may coexist -- a section is often seated before it is numbered.
    op.execute(
        "CREATE UNIQUE INDEX uq_student_enrollments_roll "
        "ON student_enrollments (section_id, academic_year_id, roll_number) "
        "WHERE roll_number IS NOT NULL AND section_id IS NOT NULL"
    )

    # =====================================================================
    # 6. attendance_sessions -- one register per section per date per period
    # =====================================================================
    op.create_table(
        "attendance_sessions",
        _pk(),
        *_tenant_columns(),
        sa.Column("section_id", sa.UUID(), nullable=False),
        sa.Column("academic_year_id", sa.UUID(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        # NOT NULL with 0 = whole day. NULL would make the uniqueness guard below
        # inert, since PostgreSQL treats NULLs as distinct in a unique index.
        sa.Column("period", sa.Integer(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("status", _enum("draft", "submitted", name="status"), nullable=False),
        sa.Column("taken_by_user_id", sa.UUID(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        *_timestamps(soft_delete=False),
        *_tenant_constraints("attendance_sessions"),
        # RESTRICT: dissolving a section must not erase the registers taken for it.
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["sections.id"],
            name=op.f("fk_attendance_sessions_section_id_sections"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["academic_year_id"],
            ["academic_years.id"],
            name=op.f("fk_attendance_sessions_academic_year_id_academic_years"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subjects.id"],
            name=op.f("fk_attendance_sessions_subject_id_subjects"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["taken_by_user_id"],
            ["users.id"],
            name=op.f("fk_attendance_sessions_taken_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attendance_sessions")),
        sa.UniqueConstraint(
            "section_id",
            "session_date",
            "period",
            name="uq_attendance_sessions_section_id_session_date_period",
        ),
        sa.CheckConstraint("period >= 0", name=op.f("ck_attendance_sessions_period_non_negative")),
        sa.CheckConstraint(
            "period > 0 OR subject_id IS NULL",
            name=op.f("ck_attendance_sessions_whole_day_has_no_subject"),
        ),
    )
    _tenant_indexes("attendance_sessions")
    op.create_index(
        op.f("ix_attendance_sessions_section_id"), "attendance_sessions", ["section_id"]
    )
    op.create_index(
        op.f("ix_attendance_sessions_academic_year_id"), "attendance_sessions", ["academic_year_id"]
    )
    op.create_index(
        op.f("ix_attendance_sessions_subject_id"), "attendance_sessions", ["subject_id"]
    )
    op.create_index(op.f("ix_attendance_sessions_status"), "attendance_sessions", ["status"])
    op.create_index(
        op.f("ix_attendance_sessions_taken_by_user_id"), "attendance_sessions", ["taken_by_user_id"]
    )
    op.create_index(
        "ix_attendance_sessions_school_id_session_date",
        "attendance_sessions",
        ["school_id", "session_date"],
    )
    op.create_index(
        "ix_attendance_sessions_section_id_session_date",
        "attendance_sessions",
        ["section_id", "session_date"],
    )

    # =====================================================================
    # 7. attendance_records -- one line per student per register
    # =====================================================================
    op.create_table(
        "attendance_records",
        _pk(),
        *_tenant_columns(),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column(
            "status",
            _enum("present", "absent", "late", "excused", "half_day", name="status"),
            nullable=False,
        ),
        sa.Column("minutes_late", sa.Integer(), nullable=True),
        sa.Column("remarks", sa.String(length=300), nullable=True),
        sa.Column("marked_by_user_id", sa.UUID(), nullable=True),
        *_timestamps(soft_delete=False),
        *_tenant_constraints("attendance_records"),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["attendance_sessions.id"],
            name=op.f("fk_attendance_records_session_id_attendance_sessions"),
            ondelete="CASCADE",
        ),
        # RESTRICT: students are soft-deleted, so this should never fire. It is here
        # so that a future hard delete is refused rather than silently erasing an
        # attendance history a parent or an inspector may later ask about.
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name=op.f("fk_attendance_records_student_id_students"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["marked_by_user_id"],
            ["users.id"],
            name=op.f("fk_attendance_records_marked_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attendance_records")),
        sa.UniqueConstraint(
            "session_id", "student_id", name="uq_attendance_records_session_id_student_id"
        ),
        sa.CheckConstraint(
            "minutes_late IS NULL OR minutes_late >= 0",
            name=op.f("ck_attendance_records_minutes_late_non_negative"),
        ),
    )
    _tenant_indexes("attendance_records")
    op.create_index(op.f("ix_attendance_records_session_id"), "attendance_records", ["session_id"])
    op.create_index(op.f("ix_attendance_records_student_id"), "attendance_records", ["student_id"])
    op.create_index(
        op.f("ix_attendance_records_marked_by_user_id"), "attendance_records", ["marked_by_user_id"]
    )
    op.create_index(
        "ix_attendance_records_student_id_status", "attendance_records", ["student_id", "status"]
    )
    op.create_index(
        "ix_attendance_records_school_id_student_id",
        "attendance_records",
        ["school_id", "student_id"],
    )

    # =====================================================================
    # 8. RLS on all seven tables
    # =====================================================================
    for table in _TABLES:
        setup_tenant_table(table)

    _install_permissions()


def _install_permissions() -> None:
    """Seed the ten new catalog rows and grant them to the roles that need them."""
    # Order matters: the catalog rows must exist before `role_permissions` can
    # reference them (FK on `permissions.code`).
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

    # The principal holds the ENTIRE catalog by definition (`_PRINCIPAL_PERMISSIONS =
    # ALL_CODES`). Without this, every principal created before today would 403 on
    # every new route the moment this ships -- a broken release, not a seed gap.
    for role_code, codes in (
        ("principal", _NEW_CODES),
        ("teacher", _TEACHER_CODES),
        ("accountant", _ACCOUNTANT_CODES),
    ):
        op.execute(
            sa.text(
                """
                INSERT INTO role_permissions (role_id, organization_id, permission_code)
                SELECT r.id, r.organization_id, p.code
                  FROM roles r
                 CROSS JOIN unnest(CAST(:codes AS text[])) AS p(code)
                 WHERE r.code = :role_code
                   AND r.is_system IS TRUE
                ON CONFLICT DO NOTHING
                """
            ).bindparams(codes=list(codes), role_code=role_code)
        )

    # Bump the version on every role whose grants just changed. `core/cache.py` keys
    # the cached permission set on `(role_id, permissions_version)`, so without this
    # a warm cache would keep serving the pre-migration set until it expired -- and
    # the new routes would 403 for exactly as long.
    op.execute(
        """
        UPDATE roles
           SET permissions_version = permissions_version + 1
         WHERE is_system IS TRUE
           AND code IN ('principal', 'teacher', 'accountant')
        """
    )


def downgrade() -> None:
    # Grants first: `role_permissions.permission_code` is RESTRICT, so the catalog
    # rows cannot be removed while any role still references them.
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_code = ANY(CAST(:codes AS text[]))"
        ).bindparams(codes=list(_NEW_CODES))
    )
    op.execute(
        "UPDATE roles SET permissions_version = permissions_version + 1 "
        "WHERE is_system IS TRUE AND code IN ('principal', 'teacher', 'accountant')"
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE code = ANY(CAST(:codes AS text[]))").bindparams(
            codes=list(_NEW_CODES)
        )
    )

    for table in reversed(_TABLES):
        teardown_tenant_table(table)

    for index in (
        "uq_student_enrollments_roll",
        "uq_student_enrollments_one_open",
        "uq_academic_years_one_current",
    ):
        op.execute(f"DROP INDEX IF EXISTS {index}")

    for table in reversed(_TABLES):
        op.drop_table(table)
