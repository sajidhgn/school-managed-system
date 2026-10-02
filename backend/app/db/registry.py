"""Model registry -- the single import that makes every table visible.

WHY THIS FILE EXISTS
    SQLAlchemy only knows about a model once its module has been imported. Alembic's
    autogenerate compares `Base.metadata` against the live database, so a model that
    was never imported is *absent* from the metadata -- and autogenerate will
    interpret its existing table as "not in the model" and generate a DROP TABLE.

    That failure mode is silent, destructive, and easy to hit. This module makes the
    import explicit and reviewable: adding a model means adding one line here.

RESPONSIBILITY
    Import every ORM model module. It defines nothing itself.

INTERACTIONS
    * `alembic/env.py` imports it before reading `Base.metadata`.
    * `tests/conftest.py` imports it before `create_all`.

RULE
    Every new `app/modules/<name>/models.py` MUST be added below in the same commit
    that creates it.

ON ORDERING
    Foreign keys are declared as strings (`ForeignKey("users.id")`) and resolved
    lazily when mappers are first configured, so import order does not affect
    correctness. The grouping below follows the dependency direction anyway --
    platform, then identity, then tenancy, then everything scoped by it -- because a
    reader tracing where `organization_id` comes from should not have to jump around.
"""

from __future__ import annotations

from app.db.base import Base

# --- Academic modules (scoped by organization_id + school_id) ---------------
# `academics` before `students`: `students.Student.section_id` references
# `sections.id`, and keeping the declaration order aligned with the dependency
# keeps mapper-configuration errors readable when one is misdeclared.
from app.modules.academics import models as academics_models

# --- Attendance: one register per section per day, one record per student --
# Listed here rather than after `students` because ruff sorts this block
# alphabetically; the dependency direction is academics + students -> attendance,
# which import order does not affect (foreign keys resolve lazily -- see ON ORDERING).
from app.modules.attendance import models as attendance_models

# --- Identity (global, no tenant column): users, sessions, email tokens -----
from app.modules.auth import models as auth_models

# --- Billing: subscriptions, invoices, usage counters, webhook ledger -------
from app.modules.billing import models as billing_models

# --- Diary: the daily homework page per section and subject -----------------
from app.modules.diary import models as diary_models

# --- Fees: what a school bills its students (NOT the SaaS subscription) -----
# After `academics` and before `students` in spirit -- `fee_structures.class_id`
# references `classes.id` and `fee_vouchers.student_id` references `students.id`.
from app.modules.fees import models as fees_models

# --- Guardians: the adults responsible for a student, and the family links -
# After `students` in spirit -- `student_guardians.student_id` references
# `students.id` -- and the aggregate that unblocks the parent portal.
from app.modules.guardians import models as guardian_models

# --- Invitations: the only entry path into an existing organization ---------
from app.modules.invitations import models as invitation_models

# --- Platform (no RLS): operators, plan catalog, platform audit -------------
from app.modules.platform_admin import models as platform_models

# --- Access control: permission catalog, roles, memberships, audit ----------
from app.modules.rbac import models as rbac_models
from app.modules.students import models as student_models

# --- Tenancy: organizations (the RLS key) and schools -----------------------
from app.modules.tenancy import models as tenancy_models

__all__ = [
    "Base",
    "academics_models",
    "attendance_models",
    "auth_models",
    "billing_models",
    "diary_models",
    "fees_models",
    "guardian_models",
    "invitation_models",
    "platform_models",
    "rbac_models",
    "student_models",
    "tenancy_models",
]
