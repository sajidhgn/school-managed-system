"""The permission catalog and the default permission sets for system roles.

WHY THIS FILE EXISTS
    Spec §5.1 defines the catalog as data, seeded into the `permissions` table. But
    the seed has to come from somewhere reviewable, and scattering permission strings
    as literals across services is how a system ends up with `member:invite` in one
    place and `members:invite` in another -- a typo that fails OPEN, because a
    permission nobody holds is a route nobody can reach until someone "fixes" it by
    loosening the check.

    Declaring them here once means the seed, the tests and the route decorators all
    read from the same constants, and a typo is an AttributeError at import time.

RESPONSIBILITY
    Enumerate every permission with its metadata, and define which permissions each
    seeded system role starts with. No database access, no HTTP -- pure data, so it
    can be imported by the seeder, the service layer and the test suite alike.

INTERACTIONS
    * `app/cli.py::seed` upserts `CATALOG` into the `permissions` table.
    * `modules/rbac/service.py` reads `SYSTEM_ROLE_PERMISSIONS` when provisioning a
      new organization or school.
    * `api/deps.py::require("member:invite")` -- codes appear as literals in routes,
      validated against this catalog by a test.

=============================================================================
`min_scope` IS THE PART THAT MATTERS
=============================================================================
    A permission marked ORG may only ever be attached to an org-level role. The
    reason is concrete: `school:create` on a school-scoped role would let a principal
    manufacture campuses the organization has not paid for, and `billing:manage`
    would let a teacher at one campus change the plan for the whole group. Both are
    privilege escalations that look like ordinary role configuration in a UI.

    Attaching an ORG permission to a school role returns 422. That check lives in the
    service, and it is one of the spec's release-gate tests.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.rbac.models import PermissionScope, SystemRole


@dataclass(frozen=True, slots=True)
class PermissionDef:
    """One catalog entry. Frozen because the catalog is a constant, not state."""

    code: str
    category: str
    description: str
    min_scope: PermissionScope = PermissionScope.SCHOOL
    is_dangerous: bool = False

    @property
    def resource(self) -> str:
        return self.code.split(":", 1)[0]

    @property
    def action(self) -> str:
        return self.code.split(":", 1)[1]


def _org(code: str, category: str, description: str, *, dangerous: bool = False) -> PermissionDef:
    return PermissionDef(code, category, description, PermissionScope.ORG, dangerous)


def _school(
    code: str, category: str, description: str, *, dangerous: bool = False
) -> PermissionDef:
    return PermissionDef(code, category, description, PermissionScope.SCHOOL, dangerous)


# ---------------------------------------------------------------------------
# The catalog (spec §5.1)
# ---------------------------------------------------------------------------

ORGANIZATION_PERMISSIONS: tuple[PermissionDef, ...] = (
    _org("org:read", "Organization", "View organization profile and settings."),
    _org("org:update", "Organization", "Edit organization profile and settings."),
    _org("org:delete", "Organization", "Delete the organization.", dangerous=True),
    _org(
        "org:transfer_ownership",
        "Organization",
        "Transfer ownership to another member.",
        dangerous=True,
    ),
)

BILLING_PERMISSIONS: tuple[PermissionDef, ...] = (
    _org("billing:read", "Billing", "View the subscription and current plan."),
    _org(
        "billing:manage", "Billing", "Change plan, update payment details, cancel.", dangerous=True
    ),
    _org("invoice:read", "Billing", "View invoices."),
    _org("invoice:download", "Billing", "Download invoice PDFs."),
)

SCHOOL_PERMISSIONS: tuple[PermissionDef, ...] = (
    # `school:create` is ORG-scoped: creating a campus spends the organization's
    # plan allowance, so it is an organization decision, not a campus one.
    _org("school:create", "Schools", "Create a new school in the organization."),
    _school("school:read", "Schools", "View school profile."),
    _school("school:update", "Schools", "Edit school profile and settings."),
    _school("school:archive", "Schools", "Archive a school.", dangerous=True),
)

PEOPLE_PERMISSIONS: tuple[PermissionDef, ...] = (
    _school("member:read", "People & access", "View staff members."),
    _school("member:invite", "People & access", "Invite new staff members."),
    _school("member:update", "People & access", "Change a member's role."),
    _school("member:suspend", "People & access", "Suspend a member's access."),
    _school("member:remove", "People & access", "Remove a member.", dangerous=True),
    _school("role:read", "People & access", "View roles."),
    _school("role:create", "People & access", "Create custom roles."),
    _school("role:update", "People & access", "Rename or describe a role."),
    _school("role:delete", "People & access", "Delete a custom role.", dangerous=True),
    _school(
        "role:assign_permissions",
        "People & access",
        "Change which permissions a role grants.",
        dangerous=True,
    ),
    _school("invitation:read", "People & access", "View pending invitations."),
    _school("invitation:resend", "People & access", "Resend an invitation email."),
    _school("invitation:revoke", "People & access", "Revoke a pending invitation."),
)

AUDIT_PERMISSIONS: tuple[PermissionDef, ...] = (
    _school("audit:read", "Audit", "View the audit log."),
)

# Wired but unimplemented -- the academic modules ship later (spec §5.1).
#
# WHY SEED THEM NOW: roles are configured by customers, and a permission that
# appears only when its module lands means every existing custom role silently
# lacks it on the day of that release. Seeding the codes up front lets a principal
# configure "who will be able to mark attendance" before attendance exists, and
# makes the module's arrival a UI change rather than a re-permissioning exercise.
ACADEMIC_PERMISSIONS: tuple[PermissionDef, ...] = (
    _school("student:read", "Students", "View student records."),
    _school("student:create", "Students", "Enrol new students."),
    _school("student:update", "Students", "Edit student records."),
    _school("student:delete", "Students", "Remove student records.", dangerous=True),
    _school("class:read", "Academics", "View classes and sections."),
    _school("class:create", "Academics", "Create classes and sections."),
    _school("class:update", "Academics", "Edit classes and sections."),
    _school("class:delete", "Academics", "Delete classes and sections.", dangerous=True),
    _school("teacher:read", "Academics", "View teaching staff assignments."),
    _school("teacher:manage", "Academics", "Assign teachers to classes."),
    _school("attendance:read", "Academics", "View attendance records."),
    _school("attendance:mark", "Academics", "Mark attendance."),
    _school("grade:read", "Academics", "View grades."),
    _school("grade:manage", "Academics", "Enter and edit grades."),
    _school("fee:read", "Finance", "View fee records."),
    _school("fee:manage", "Finance", "Create and adjust fees.", dangerous=True),
    _school("timetable:read", "Academics", "View the timetable."),
    _school("timetable:manage", "Academics", "Edit the timetable."),
)

CATALOG: tuple[PermissionDef, ...] = (
    *ORGANIZATION_PERMISSIONS,
    *BILLING_PERMISSIONS,
    *SCHOOL_PERMISSIONS,
    *PEOPLE_PERMISSIONS,
    *AUDIT_PERMISSIONS,
    *ACADEMIC_PERMISSIONS,
)

BY_CODE: dict[str, PermissionDef] = {p.code: p for p in CATALOG}

ALL_CODES: frozenset[str] = frozenset(BY_CODE)

ORG_SCOPED_CODES: frozenset[str] = frozenset(
    p.code for p in CATALOG if p.min_scope is PermissionScope.ORG
)

SCHOOL_SCOPED_CODES: frozenset[str] = ALL_CODES - ORG_SCOPED_CODES


# ---------------------------------------------------------------------------
# Default permission sets for the seeded system roles (spec §5.2)
# ---------------------------------------------------------------------------

# The owner holds everything. This is the only role for which that is true, and it
# is why `org:transfer_ownership` and `billing:manage` exist as separate codes at
# all -- so that no other role can be given them by accident.
_OWNER_PERMISSIONS: frozenset[str] = ALL_CODES

# The principal runs one school: every school-scoped permission, plus full control
# of roles, members, invitations and the audit log for that school.
#
# EXPLICITLY WITHOUT `billing:*` AND `school:create`. Those are org-level codes, so
# the scope rule would reject them anyway -- but stating the exclusion here means a
# reader does not have to reconstruct it from `min_scope` metadata, and a future
# change that re-scopes a billing permission cannot silently widen the principal.
_PRINCIPAL_PERMISSIONS: frozenset[str] = SCHOOL_SCOPED_CODES

# Deliberately minimal. Spec §5.2 gives the teacher `member:read` plus academic
# access; the academic reads are included because a teacher who cannot see the class
# list cannot do the job, while every write beyond attendance and grades is left for
# the principal to grant explicitly.
_TEACHER_PERMISSIONS: frozenset[str] = frozenset(
    {
        "member:read",
        "school:read",
        "student:read",
        "class:read",
        "teacher:read",
        "attendance:read",
        "attendance:mark",
        "grade:read",
        "grade:manage",
        "timetable:read",
    }
)

_ACCOUNTANT_PERMISSIONS: frozenset[str] = frozenset(
    {
        "member:read",
        "school:read",
        "student:read",
        "invoice:read",
        "fee:read",
        "fee:manage",
    }
)

SYSTEM_ROLE_PERMISSIONS: dict[SystemRole, frozenset[str]] = {
    SystemRole.OWNER: _OWNER_PERMISSIONS,
    SystemRole.PRINCIPAL: _PRINCIPAL_PERMISSIONS,
    SystemRole.TEACHER: _TEACHER_PERMISSIONS,
    SystemRole.ACCOUNTANT: _ACCOUNTANT_PERMISSIONS,
}

# Human-facing names and descriptions for the seeded roles.
SYSTEM_ROLE_META: dict[SystemRole, tuple[str, str]] = {
    SystemRole.OWNER: (
        "Owner",
        "Owns billing and the organization. Can create schools and appoint principals.",
    ),
    SystemRole.PRINCIPAL: (
        "Principal",
        "Runs one school: staff, roles, invitations and all school data. No billing rights.",
    ),
    SystemRole.TEACHER: ("Teacher", "Teaching staff. Marks attendance and enters grades."),
    SystemRole.ACCOUNTANT: ("Accountant", "Handles fees and invoices for the school."),
}

# `owner` and `principal` are locked (spec §5.3 rule 2): a principal must not be
# able to widen its own role or the owner's. `teacher` and `accountant` are starting
# points that each customer is expected to tailor.
LOCKED_ROLE_CODES: frozenset[str] = frozenset({SystemRole.OWNER.value, SystemRole.PRINCIPAL.value})

# Roles created for every new school. The owner role is org-level and is created once
# per organization at signup, so it is deliberately absent here.
SCHOOL_SYSTEM_ROLES: tuple[SystemRole, ...] = (
    SystemRole.PRINCIPAL,
    SystemRole.TEACHER,
    SystemRole.ACCOUNTANT,
)


def scope_violations(codes: frozenset[str], *, is_school_scoped: bool) -> frozenset[str]:
    """Return the codes in `codes` that may not be attached to a role of this scope.

    Spec §5.3 rule 3. Returns the offending set rather than a bool so the 422 can
    name exactly which permissions were rejected -- a role editor that says only
    "invalid selection" for a 60-checkbox matrix is unusable.
    """
    if not is_school_scoped:
        return frozenset()
    return codes & ORG_SCOPED_CODES


def unknown_codes(codes: frozenset[str]) -> frozenset[str]:
    """Return codes that are not in the catalog at all.

    Checked before the scope rule so that a typo reports as "no such permission"
    rather than as a scope error, which would send the reader hunting in the wrong
    direction entirely.
    """
    return codes - ALL_CODES
