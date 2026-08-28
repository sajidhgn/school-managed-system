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
    reason is concrete: `school:create` on a school-scoped role would let a campus
    role manufacture campuses the organization has not paid for, and `billing:manage`
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

# Guardians are PEOPLE DATA, not academic data, and get their own category so a
# principal configuring "who may see parent phone numbers" finds one checkbox list
# rather than hunting through the students section.
#
# NOT FOLDED INTO `student:*`. A guardian record is contact data about an ADULT, and
# the receptionist who updates a phone number is not necessarily the registrar who may
# edit a child's record. The split is also what lets a school give the parent-portal
# support desk read access to families without exposing student academic data.
#
# FIVE CODES, and the split that matters is the last one. `guardian:portal` guards the
# two actions that hand out or take away a LOGIN -- changing the number a parent signs
# in with, and enabling or disabling portal access. Folding those into
# `guardian:update` would mean the clerk who fixes a misspelt name can also re-point a
# father's login at their own handset, which is an account takeover that looks like
# ordinary data entry in every log.
GUARDIAN_PERMISSIONS: tuple[PermissionDef, ...] = (
    _school("guardian:read", "Guardians", "View guardians and their linked students."),
    _school("guardian:create", "Guardians", "Register guardians."),
    _school("guardian:update", "Guardians", "Edit guardians and their student links."),
    _school("guardian:delete", "Guardians", "Remove a guardian record.", dangerous=True),
    _school(
        "guardian:portal",
        "Guardians",
        "Change a guardian's sign-in number or portal access.",
        dangerous=True,
    ),
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
    # Bulk promotion moves an entire cohort up a grade for a new year. It is separate
    # from `student:update` because it is whole-school, once-a-year and looks
    # irreversible from the UI -- exactly the shape of action that should require an
    # explicit grant rather than riding along with "edit a student".
    _school(
        "student:promote",
        "Students",
        "Promote a class or section to the next academic year.",
        dangerous=True,
    ),
    _school("class:read", "Academics", "View classes and sections."),
    _school("class:create", "Academics", "Create classes and sections."),
    _school("class:update", "Academics", "Edit classes and sections."),
    _school("class:delete", "Academics", "Delete classes and sections.", dangerous=True),
    _school("teacher:read", "Academics", "View teaching staff assignments."),
    _school("teacher:manage", "Academics", "Assign teachers to classes."),
    _school("attendance:read", "Academics", "View attendance records."),
    _school("attendance:mark", "Academics", "Mark attendance."),
    # The counterpart of `fee:void`, and separate for the same reason. `attendance:mark`
    # lets a teacher assert today's register; `attendance:amend` lets someone rewrite a
    # register that was already submitted. A system where the person who records
    # absences can quietly erase them has no attendance record, only an attendance
    # opinion.
    _school(
        "attendance:amend",
        "Academics",
        "Reopen and correct a submitted attendance register.",
        dangerous=True,
    ),
    # The academic calendar and the subject list. Two codes, not eight: these are
    # setup screens a registrar touches a few times a year, and a permission matrix
    # that distinguishes "create a term" from "rename a term" is a matrix nobody
    # configures correctly.
    _school("calendar:read", "Academics", "View academic years and terms."),
    _school("calendar:manage", "Academics", "Define academic years and terms."),
    _school("subject:read", "Academics", "View subjects and class curricula."),
    _school("subject:manage", "Academics", "Define subjects and assign them to classes."),
    _school("grade:read", "Academics", "View grades."),
    _school("grade:manage", "Academics", "Enter and edit grades."),
    # FIVE fee codes, not one. `fee:collect` and `fee:void` are separate because the
    # person who records money coming in must not be the person who can make a record
    # of money disappear -- the oldest control in bookkeeping. See
    # docs/modules/fees.md §4.
    _school("fee:read", "Finance", "View fee heads, structures, vouchers and payments."),
    _school("fee:manage", "Finance", "Define fee heads and fee structures.", dangerous=True),
    _school("fee:issue", "Finance", "Generate and issue fee vouchers."),
    _school("fee:collect", "Finance", "Record fee payments and issue receipts."),
    _school(
        "fee:void",
        "Finance",
        "Void a fee voucher or reverse a recorded payment.",
        dangerous=True,
    ),
    _school("timetable:read", "Academics", "View the timetable."),
    _school("timetable:manage", "Academics", "Edit the timetable."),
)

CATALOG: tuple[PermissionDef, ...] = (
    *ORGANIZATION_PERMISSIONS,
    *BILLING_PERMISSIONS,
    *SCHOOL_PERMISSIONS,
    *PEOPLE_PERMISSIONS,
    *GUARDIAN_PERMISSIONS,
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

# The principal runs the organization: billing, campuses, staff, roles and every
# school-scoped capability across all of them. It is the ONLY role that holds
# everything, and it is org-level -- there is no school-scoped variant of it.
#
# This is why `org:transfer_ownership` and `billing:manage` exist as separate codes
# at all: so that no OTHER role can be given them by accident. A custom role built
# by a principal is still bounded by the escalation guard, but these two are the
# ones that would be catastrophic to hand out, so they stay individually named.
_PRINCIPAL_PERMISSIONS: frozenset[str] = ALL_CODES

# Deliberately minimal. Spec §5.2 gives the teacher `member:read` plus academic
# access; the academic reads are included because a teacher who cannot see the class
# list cannot do the job, while every write beyond attendance and grades is left for
# the principal to grant explicitly.
_TEACHER_PERMISSIONS: frozenset[str] = frozenset(
    {
        "member:read",
        "school:read",
        "student:read",
        # A teacher phoning a parent about an absence needs the number. Read only:
        # correcting family records is a front-office job, and `attendance:amend` is
        # absent for the same separation reason.
        "guardian:read",
        "class:read",
        "calendar:read",
        "subject:read",
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
        # The name on the challan and the number a fee reminder goes to.
        "guardian:read",
        "calendar:read",
        "invoice:read",
        "fee:read",
        "fee:manage",
        "fee:issue",
        "fee:collect",
        # `fee:void` is deliberately ABSENT. An accountant who mis-keys a receipt asks
        # a principal to reverse it, and that reversal carries both identities in the
        # audit trail. Customers who want their accountant to hold it grant it
        # explicitly -- it is simply not the default.
    }
)

SYSTEM_ROLE_PERMISSIONS: dict[SystemRole, frozenset[str]] = {
    SystemRole.PRINCIPAL: _PRINCIPAL_PERMISSIONS,
    SystemRole.TEACHER: _TEACHER_PERMISSIONS,
    SystemRole.ACCOUNTANT: _ACCOUNTANT_PERMISSIONS,
}

# Human-facing names and descriptions for the seeded roles.
SYSTEM_ROLE_META: dict[SystemRole, tuple[str, str]] = {
    SystemRole.PRINCIPAL: (
        "Principal",
        "Runs the organization: billing, campuses, staff, roles and all school data.",
    ),
    SystemRole.TEACHER: ("Teacher", "Teaching staff. Marks attendance and enters grades."),
    SystemRole.ACCOUNTANT: ("Accountant", "Handles fees and invoices for the school."),
}

# `principal` is locked (spec §5.3 rule 2): the role that defines the organization's
# top authority must not be editable by the person holding it, in either direction.
# `teacher` and `accountant` are starting points that each customer is expected to
# tailor.
LOCKED_ROLE_CODES: frozenset[str] = frozenset({SystemRole.PRINCIPAL.value})

# Roles created for every new school. `principal` is deliberately absent: it is
# org-level and created once per organization at signup. Seeding a second,
# school-scoped "Principal" per campus is exactly the duplicate this design removes
# -- it would put two roles of the same name in the picker, one of which silently
# lacks billing, and hand the founder a second membership they never asked for.
SCHOOL_SYSTEM_ROLES: tuple[SystemRole, ...] = (
    SystemRole.TEACHER,
    SystemRole.ACCOUNTANT,
)

# Which roles put someone in front of a class -- used to populate teacher pickers
# (the class-teacher field on a section, the teacher on a curriculum entry).
#
# DEFINED BY CAPABILITY, NOT BY ROLE CODE. Matching `role.code == "teacher"` would
# have been shorter and is wrong: the seeded `teacher` role is explicitly "a starting
# point each customer is expected to tailor" (see above), so a school that renames it
# to "Senior Teacher", or adds a second "Head of Curriculum" role, would get an EMPTY
# picker while its staff list is full of teachers. Asking what the role can DO
# survives that renaming, which is the same reason the UI gates on permissions rather
# than on role names.
#
# `attendance:mark` and `grade:manage` are the two that mean "runs a classroom": one
# asserts who was present, the other enters what they scored. A role holding either
# is doing the job a class teacher does. Read-only academic access (`class:read`,
# `attendance:read`) is deliberately NOT here -- an accountant has those and is not a
# teacher.
#
# The principal role holds every code, including these, and so would match. It is
# excluded structurally instead: principals are ORG-level (`school_id IS NULL`) and
# the query filters on membership in the branch, so they never reach this test.
TEACHING_PERMISSIONS: frozenset[str] = frozenset({"attendance:mark", "grade:manage"})


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
