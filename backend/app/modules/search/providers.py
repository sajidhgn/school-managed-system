"""What is searchable, who may search it, and what each role cares about first.

WHY THIS FILE EXISTS
    "Global search" is not one query. It is a fan-out over a dozen entity kinds, and
    every one of them is behind a different permission. Which means the honest
    statement of the feature is:

        Global search returns the union of everything THIS CALLER is already
        allowed to read -- ranked by what a person in THIS ROLE is usually
        looking for.

    Both halves of that sentence live here. The first half is a hard boundary; the
    second is a ranking preference. Confusing the two is the bug this file exists to
    prevent, so they are deliberately different mechanisms: `permissions` is a
    frozenset that gates, `weight` is a float that sorts.

=============================================================================
ROLE-AWARENESS, THE PART THAT IS ACCESS CONTROL
=============================================================================
    A provider is unreachable unless the caller holds ALL of its `permissions`.
    Those are the same codes the module's own routes use -- `student:read` for
    students, `fee:read` for vouchers -- resolved from the same `AuthContext`.

    That is what makes search safe to ship as a single endpoint. There is no
    "search everything" permission to grant, and no way for a provider to leak a
    row its own module's list endpoint would have refused: search runs the same
    permission check and the same tenant/campus scoping.

    Concretely, out of the box (spec §5.2):
      * a PRINCIPAL holds every code, so they search all eleven kinds
      * a TEACHER holds `student:read`, `class:read`, `member:read`, `school:read`
        -- so vouchers, roles, invitations and the audit log are simply not part of
        their search. Not hidden. Not empty. Not queried.
      * an ACCOUNTANT holds `fee:read` and `student:read` but not `class:read`, so
        they search students, vouchers, fee heads and structures.
      * a CUSTOM role gets exactly the intersection its principal configured, with
        no code change -- which is the entire reason this keys on permissions and
        not on role names.

=============================================================================
ROLE-AWARENESS, THE PART THAT IS JUST GOOD MANNERS
=============================================================================
    Two people typing `10` mean different things. A teacher means Grade 10. An
    accountant means voucher 10, or a Rs 10,000 balance. Both are permitted to see
    students, so permissions alone cannot order the results usefully.

    `profile_for()` therefore derives a per-caller weight map. It starts from a
    baseline (people and students outrank configuration objects for everyone), then
    boosts the entities the caller's own permission set says they WORK on rather
    than merely read: holding `fee:collect` boosts vouchers, `attendance:mark`
    boosts students, `role:assign_permissions` boosts roles.

    Derived from permissions rather than hardcoded per role name, for the same
    reason the gate is: a school that builds a "Registrar" role gets sensible
    ordering on day one, and a principal who takes fee access away from a role
    changes that role's search ordering in the same edit.

    The three seeded roles get a small explicit nudge on top, because their intent
    is known and their permission sets are broad enough to be ambiguous -- a
    principal holds every code, so a purely derived profile would rank everything
    equally for the one role that most needs an opinionated order.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum


class SearchEntity(StrEnum):
    """The kinds of thing global search can return.

    The value is the `type:` filter token AND the discriminator on the wire, so the
    frontend switches on the same string the user types. One vocabulary, not three.
    """

    STUDENT = "student"
    CLASS = "class"
    SECTION = "section"
    MEMBER = "member"
    INVITATION = "invitation"
    ROLE = "role"
    SCHOOL = "school"
    VOUCHER = "voucher"
    FEE_HEAD = "fee_head"
    FEE_STRUCTURE = "fee_structure"
    AUDIT = "audit"


@dataclass(frozen=True, slots=True)
class ProviderDef:
    """One searchable entity kind: its gate, its filters, and its default rank."""

    entity: SearchEntity

    label: str
    """Plural heading for the result group. Rendered as-is by the UI."""

    icon: str
    """Lucide icon name. Sent from the server so a newly added provider needs no
    frontend change to render with the right glyph -- the omnibar is generic."""

    permissions: frozenset[str]
    """ALL of these are required. `all`, never `any`: a provider needing two codes
    describes a read that genuinely spans both, and `any` semantics there is the
    quiet way a partial grant becomes a full one. Mirrors `AuthContext.has`."""

    filters: tuple[str, ...]
    """Which `key:` filters do anything for this provider. Returned by
    `/search/config` so the UI can offer the right chips per scope instead of a
    fixed list that is wrong for most of them."""

    weight: float
    """Baseline relevance multiplier, before the caller's profile is applied.
    A student named "Ahmed" should outrank a fee head whose description mentions
    him, even at identical text-match strength."""

    in_default_scan: bool = True
    """False for providers that are noisy or expensive enough that they should only
    run when explicitly asked for with `type:`. The audit log is the only one:
    it matches almost any term (it stores action names and entity types) and would
    otherwise drown the omnibar in rows nobody was looking for."""

    url_template: str = ""
    """Frontend deep link, `{id}`-interpolated by the provider's row mapper. Kept
    here so "where does clicking a result go?" is answerable in one place.

    =========================================================================
    ONLY THREE OF THESE ARE PRECISE, AND THE REST SAY SO BY NOT PRETENDING
    =========================================================================
        Students, vouchers and campuses have detail pages, so their links land on
        the exact record. The other eight modules have list pages with no filter UI
        and no `q` parameter, so their links land on the LIST.

        An earlier version of this carried `?q=…` and `?role=…` on those templates.
        It looked more precise and was not: nothing reads those parameters, so the
        user got an unfiltered list plus a query string implying a filter that was
        never applied. A link that quietly does less than its URL claims is worse
        than one that is honestly coarse.

        When those pages grow a filter, add the parameter here and it becomes a
        precise link for every caller at once -- which is the point of the templates
        living in the registry rather than in the frontend."""


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
#
# Ordered by baseline weight, descending, which is also roughly the order a school
# administrator thinks in: people first, then the structures people sit in, then the
# money, then the configuration behind all of it.

PROVIDERS: tuple[ProviderDef, ...] = (
    ProviderDef(
        entity=SearchEntity.STUDENT,
        label="Students",
        icon="GraduationCap",
        permissions=frozenset({"student:read"}),
        filters=("status", "class", "section", "school", "after", "before"),
        weight=1.00,
        url_template="/students/{id}",
    ),
    ProviderDef(
        entity=SearchEntity.MEMBER,
        label="Staff",
        icon="Users",
        permissions=frozenset({"member:read"}),
        filters=("status", "role", "school"),
        weight=0.95,
        url_template="/members",
    ),
    ProviderDef(
        entity=SearchEntity.VOUCHER,
        label="Fee vouchers",
        icon="Receipt",
        permissions=frozenset({"fee:read"}),
        filters=("status", "year", "school", "after", "before"),
        weight=0.90,
        url_template="/fees/{id}",
    ),
    ProviderDef(
        entity=SearchEntity.CLASS,
        label="Classes",
        icon="Layers",
        permissions=frozenset({"class:read"}),
        filters=("school",),
        weight=0.85,
        url_template="/classes",
    ),
    ProviderDef(
        entity=SearchEntity.SECTION,
        label="Sections",
        icon="Layers",
        permissions=frozenset({"class:read"}),
        filters=("class", "school"),
        weight=0.80,
        url_template="/classes",
    ),
    ProviderDef(
        entity=SearchEntity.SCHOOL,
        label="Campuses",
        icon="School",
        permissions=frozenset({"school:read"}),
        filters=("status",),
        weight=0.75,
        url_template="/schools/{id}",
    ),
    ProviderDef(
        entity=SearchEntity.INVITATION,
        label="Invitations",
        icon="Mail",
        permissions=frozenset({"invitation:read"}),
        filters=("status", "role", "school", "after", "before"),
        weight=0.65,
        url_template="/invitations",
    ),
    ProviderDef(
        entity=SearchEntity.FEE_STRUCTURE,
        label="Fee structures",
        icon="ScrollText",
        permissions=frozenset({"fee:read"}),
        filters=("status", "year", "class", "school"),
        weight=0.60,
        url_template="/fees/setup",
    ),
    ProviderDef(
        entity=SearchEntity.FEE_HEAD,
        label="Fee heads",
        icon="Receipt",
        permissions=frozenset({"fee:read"}),
        filters=("status", "school"),
        weight=0.55,
        url_template="/fees/setup",
    ),
    ProviderDef(
        entity=SearchEntity.ROLE,
        label="Roles",
        icon="ShieldCheck",
        permissions=frozenset({"role:read"}),
        filters=("school",),
        weight=0.50,
        url_template="/roles",
    ),
    ProviderDef(
        entity=SearchEntity.AUDIT,
        label="Audit log",
        icon="ScrollText",
        permissions=frozenset({"audit:read"}),
        filters=("school", "after", "before"),
        weight=0.40,
        in_default_scan=False,  # see ProviderDef.in_default_scan
        url_template="/audit",
    ),
)

BY_ENTITY: Mapping[SearchEntity, ProviderDef] = {p.entity: p for p in PROVIDERS}


# ---------------------------------------------------------------------------
# Per-caller ranking profile
# ---------------------------------------------------------------------------

# A permission that means "this person DOES this job", mapped to the entities that
# job is about. Read codes are deliberately absent: nearly everyone can read
# students, so `student:read` says nothing about what someone is looking for.
# Holding `attendance:mark` does.
_WORK_SIGNALS: tuple[tuple[str, tuple[SearchEntity, ...], float], ...] = (
    ("attendance:mark", (SearchEntity.STUDENT, SearchEntity.SECTION), 0.30),
    ("grade:manage", (SearchEntity.STUDENT, SearchEntity.SECTION), 0.25),
    ("student:create", (SearchEntity.STUDENT,), 0.20),
    ("student:update", (SearchEntity.STUDENT,), 0.15),
    # Weighted towards the voucher, not evenly: whoever collects fees looks a
    # student up in order to reach their voucher, so the voucher is the
    # destination and the student is the route. Splitting this evenly ranked
    # students above vouchers for a cashier, which is backwards.
    ("fee:collect", (SearchEntity.VOUCHER,), 0.45),
    ("fee:collect", (SearchEntity.STUDENT,), 0.20),
    ("fee:issue", (SearchEntity.VOUCHER, SearchEntity.FEE_STRUCTURE), 0.30),
    ("fee:manage", (SearchEntity.FEE_HEAD, SearchEntity.FEE_STRUCTURE), 0.30),
    ("fee:void", (SearchEntity.VOUCHER,), 0.15),
    ("class:update", (SearchEntity.CLASS, SearchEntity.SECTION), 0.20),
    ("timetable:manage", (SearchEntity.CLASS, SearchEntity.SECTION), 0.15),
    ("member:invite", (SearchEntity.MEMBER, SearchEntity.INVITATION), 0.30),
    ("member:update", (SearchEntity.MEMBER,), 0.20),
    ("invitation:revoke", (SearchEntity.INVITATION,), 0.20),
    ("role:assign_permissions", (SearchEntity.ROLE, SearchEntity.MEMBER), 0.25),
    ("role:create", (SearchEntity.ROLE,), 0.15),
    ("school:create", (SearchEntity.SCHOOL,), 0.25),
    ("school:update", (SearchEntity.SCHOOL,), 0.15),
    ("audit:read", (SearchEntity.AUDIT,), 0.10),
)

# An explicit nudge for the seeded roles, applied on top of the derived profile.
#
# WHY THESE THREE ARE SPECIAL-CASED AT ALL: a principal holds every permission, so
# every work-signal fires and the derived profile flattens out into "everything is
# important" -- which is no ordering at all for the role that most needs one. The
# nudges are small (they reorder ties, they cannot promote something past a much
# stronger text match) and they are keyed on `Role.code`, which is stable for
# system roles and never collides with a customer's custom role code.
_SYSTEM_ROLE_NUDGE: Mapping[str, Mapping[SearchEntity, float]] = {
    # Runs the organization: campuses, staff and access are their daily objects,
    # and they are the only role that routinely searches ACROSS campuses.
    "principal": {
        SearchEntity.SCHOOL: 0.35,
        SearchEntity.MEMBER: 0.20,
        SearchEntity.ROLE: 0.20,
        SearchEntity.INVITATION: 0.15,
    },
    # In front of a class. Students and the section they sit in, nothing else.
    "teacher": {
        SearchEntity.STUDENT: 0.40,
        SearchEntity.SECTION: 0.30,
        SearchEntity.CLASS: 0.25,
        SearchEntity.MEMBER: -0.20,
    },
    # At the front desk taking payments. The voucher IS the job; a student is
    # looked up in order to find their voucher.
    "accountant": {
        SearchEntity.VOUCHER: 0.50,
        SearchEntity.STUDENT: 0.15,
        SearchEntity.FEE_STRUCTURE: 0.20,
        SearchEntity.FEE_HEAD: 0.15,
    },
}


def permitted(permissions: frozenset[str]) -> tuple[ProviderDef, ...]:
    """The providers this permission set may reach. THE access-control decision.

    Everything else in this module is presentation. If a provider is not in this
    tuple its SQL is never built, never parameterised and never executed -- the
    caller cannot tell the difference between "no matches" and "not for you",
    because there is no query either way.
    """
    return tuple(p for p in PROVIDERS if permissions.issuperset(p.permissions))


def profile_for(role_code: str, permissions: frozenset[str]) -> Mapping[SearchEntity, float]:
    """Relevance multiplier per entity for this specific caller.

    Returns a weight for EVERY entity, including ones the caller cannot reach --
    callers intersect with `permitted()` themselves, and a complete map is easier to
    reason about (and to snapshot in a test) than a sparse one.
    """
    profile: dict[SearchEntity, float] = {p.entity: p.weight for p in PROVIDERS}

    for code, entities, boost in _WORK_SIGNALS:
        if code in permissions:
            for entity in entities:
                profile[entity] += boost

    for entity, nudge in _SYSTEM_ROLE_NUDGE.get(role_code.lower(), {}).items():
        profile[entity] += nudge

    # Clamped low rather than allowed to go negative: a negative multiplier would
    # invert ranking so that the WORST text match came first, which is a far more
    # confusing failure than a de-prioritised group.
    return {entity: max(0.05, weight) for entity, weight in profile.items()}


def ordered_for(
    role_code: str,
    permissions: frozenset[str],
    *,
    include_hidden: bool = False,
) -> Sequence[ProviderDef]:
    """Providers this caller may use, most relevant to them first.

    Drives both the default scan order and the scope chips in the omnibar, so the
    list a teacher sees is ordered the way a teacher thinks -- and an accountant's
    starts with vouchers -- from the same call.
    """
    profile = profile_for(role_code, permissions)
    allowed = [p for p in permitted(permissions) if include_hidden or p.in_default_scan]
    return sorted(allowed, key=lambda p: (-profile[p.entity], p.label))


def resolve_requested(
    parsed_types: Sequence[str],
    excluded_types: Sequence[str],
    available: Sequence[ProviderDef],
) -> tuple[tuple[ProviderDef, ...], tuple[str, ...]]:
    """Apply `type:` / `-type:` to the caller's available providers.

    Returns the providers to run and any warnings. A `type:` naming something the
    caller cannot reach produces the SAME message as one naming a typo:

        Unknown or unavailable type

    That wording is deliberate. Distinguishing "no such type" from "not permitted"
    would turn the search box into a probe for which modules a tenant has enabled
    and which permissions the caller is missing -- a small leak, but a free one to
    avoid, and the user's next action ("search something else") is identical either
    way.
    """
    warnings: list[str] = []
    by_value = {p.entity.value: p for p in available}

    excluded = set(excluded_types)
    selected: list[ProviderDef]

    if parsed_types:
        selected = []
        for value in parsed_types:
            provider = by_value.get(value)
            if provider is None:
                warnings.append(f"Unknown or unavailable type `{value}`.")
                continue
            selected.append(provider)
        if not selected and not warnings:
            warnings.append("No searchable types matched `type:`.")
    else:
        # No explicit `type:` -- scan everything in the caller's default set. This is
        # where `in_default_scan` keeps the audit log out unless asked for by name.
        selected = [p for p in available if p.in_default_scan]

    selected = [p for p in selected if p.entity.value not in excluded]
    return tuple(selected), tuple(warnings)
