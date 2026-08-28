"""Search SQL -- one ranked, scoped query per provider.

WHY THIS FILE EXISTS
    Every provider needs the same four things done identically: match the caller's
    terms, exclude what they negated, apply the tenant and campus boundary, and
    produce a comparable relevance score. Written per module, those four would drift
    -- and the one that drifts on the boundary leaks a row across campuses.

    So the boundary and the ranking are written ONCE here, and each provider
    contributes only the part that is genuinely its own: which columns are
    searchable, what the title says, and which filters mean something.

RESPONSIBILITY
    SQL construction and execution. No permission checks (`providers.permitted`
    already decided this query may be built at all) and no presentation (`service`
    turns rows into `SearchHit`s).

=============================================================================
WHAT MAKES A ROW MATCH
=============================================================================
    Every needle must be found in at least one of the provider's searchable
    columns -- AND across needles, OR across columns. That is the reading people
    expect: `ahmed 2026` means a row about Ahmed *and* about 2026, not either.

    "Found" is three things in order of strength:

      exact      lower(column) = term                          100
      prefix     column ILIKE 'term%'                           55
      contains   column ILIKE '%term%'                          25
      fuzzy      column %% term   (pg_trgm, typo tolerance)      0..20

    A row scores the BEST column per needle (`greatest`), summed over needles. Best
    rather than sum-across-columns on purpose: a student whose name, guardian name
    and emergency contact all contain "khan" is not three times the answer to
    "khan" -- that would rank large families above the person actually named.

=============================================================================
FUZZY MATCHING, AND WHY IT IS NOT ALWAYS ON
=============================================================================
    `pg_trgm`'s `%` operator is what makes "muhamad" find "Muhammad" -- the single
    most valuable behaviour in a school directory, where names are transliterated
    inconsistently and staff type them from memory.

    It is enabled only for needles of 4+ characters. Below that, trigram similarity
    is nearly meaningless ("10" shares trigrams with a great deal) and it would turn
    a two-character query into a full-table fuzzy scan that returns noise. Short
    needles stay exact/prefix/contains, which is also what someone typing a section
    name or a grade level actually wants.

=============================================================================
SCOPING: THE PART THAT IS NOT ALLOWED TO BE CLEVER
=============================================================================
    PostgreSQL RLS gives us the organization boundary for free on every table --
    nothing here has to remember it, and nothing here can turn it off.

    The CAMPUS boundary is this module's job, because RLS deliberately permits an
    organization-level member to span campuses. `_scope_condition` applies it to
    every provider, and the resolved scope arrives from the service as a value --
    it is never read from a request parameter here. A campus-scoped member cannot
    widen it; see `service.resolve_scope`.

    Models whose `school_id` is nullable (roles, memberships, invitations, audit
    rows) match their campus OR the organization-level rows, because an org-level
    role genuinely does apply to the campus being viewed. Excluding those would
    hide the principal from a staff search run inside a branch.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    DateTime,
    Select,
    String,
    and_,
    case,
    cast,
    false,
    func,
    literal,
    literal_column,
    or_,
    select,
    true,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.academics.models import SchoolClass, Section
from app.modules.auth.models import User
from app.modules.fees.models import (
    FeeHead,
    FeeStructure,
    FeeStructureStatus,
    FeeVoucher,
    VoucherStatus,
)
from app.modules.invitations.models import Invitation, InvitationStatus
from app.modules.rbac.models import AuditLog, Membership, MembershipStatus, Role
from app.modules.search.providers import ProviderDef, SearchEntity
from app.modules.search.query import ParsedQuery
from app.modules.students.models import Student, StudentStatus
from app.modules.tenancy.models import School, SchoolStatus

# --- Ranking constants -----------------------------------------------------

_EXACT = 100.0
_PREFIX = 55.0
_CONTAINS = 25.0
_FUZZY_MAX = 20.0
"""Fuzzy tops out BELOW `contains` deliberately. A real substring match is always a
better answer than a trigram-similar one, and a scoring scheme where a typo can
outrank a literal hit is the fastest way to lose trust in a search box."""

_FUZZY_MIN_LENGTH = 4

_LIKE_ESCAPE = "\\"

_EMPTY: ColumnElement[str] = literal_column("''")
"""The empty string as a SQL literal rather than a bind parameter. See `_text` --
this is what lets the trigram indexes match the expressions built here."""


@dataclass(frozen=True, slots=True)
class SearchScope:
    """The boundary this search runs inside. Resolved once, by the service.

    A value object rather than a set of parameters because it is threaded through
    every provider, and "which campus are we in?" answered differently by two
    providers in one response is precisely the bug worth designing out.
    """

    organization_id: UUID
    school_id: UUID | None
    """None means every campus in the organization -- only reachable by an
    organization-level member. See `service.resolve_scope`."""

    @property
    def cross_school(self) -> bool:
        return self.school_id is None


@dataclass(frozen=True, slots=True)
class RawHit:
    """One row, before the service applies the caller's role weighting."""

    entity: SearchEntity
    id: UUID
    title: str
    subtitle: str | None
    context: str | None
    status: str | None
    school_id: UUID | None
    school_name: str | None
    score: float


# ---------------------------------------------------------------------------
# Text matching primitives
# ---------------------------------------------------------------------------


def _escape_like(value: str) -> str:
    """Neutralise LIKE metacharacters in user input.

    Without this, a user typing `%` matches every row and `_` matches any character
    -- which reads as "search is broken" rather than "you used a wildcard". The
    escape character itself must be escaped first or it eats the escapes we add.
    """
    return value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")


def _text(column: Any) -> ColumnElement[str]:
    """A never-NULL, text-typed version of a column, safe to compare and concatenate.

    NULL is the default state of most of the columns worth searching -- a guardian
    email, a school's city -- and `NULL ILIKE '%x%'` is NULL, not false, which
    poisons an OR chain in ways that are tedious to debug.

    =========================================================================
    THE SHAPE OF THIS EXPRESSION IS LOAD-BEARING FOR THE TRIGRAM INDEXES
    =========================================================================
        PostgreSQL matches an expression index only against a SYNTACTICALLY
        identical expression. The GIN indexes added in migration `f3a5c7e9b1d3`
        are built on `lower(coalesce(<column>, ''))`, so an unconditional
        `CAST(... AS VARCHAR)` here would produce
        `lower(coalesce(cast(name AS VARCHAR), ''))` -- a different expression, and
        every fuzzy search would fall back to a sequential scan while the indexes
        sat unused and unqueried.

        So the cast is applied only where it is actually needed: a non-text column
        such as `classes.level`, which has no trigram index and is small enough not
        to want one.

        For the same reason the empty-string default is `_EMPTY`, a SQL literal,
        rather than the Python `""` a bind parameter would be built from. The
        planner folds `coalesce(name, '')` into the indexed expression; it cannot
        fold `coalesce(name, $1)`, because a parameter is not a constant until
        execution and index matching happens before that.

        Changing this function means revisiting that migration.
    """
    if isinstance(getattr(column, "type", None), String):
        return func.coalesce(column, _EMPTY)
    return func.coalesce(cast(column, String), _EMPTY)


def _needle_score(columns: Sequence[Any], needle: str) -> ColumnElement[float]:
    """Best score any one column achieves for this needle. See the module docstring."""
    lowered = needle.lower()
    escaped = _escape_like(lowered)
    fuzzy = len(lowered) >= _FUZZY_MIN_LENGTH

    branches: list[ColumnElement[float]] = []
    for column in columns:
        text = _text(column)
        graded = case(
            (func.lower(text) == lowered, literal(_EXACT)),
            (text.ilike(f"{escaped}%", escape=_LIKE_ESCAPE), literal(_PREFIX)),
            (text.ilike(f"%{escaped}%", escape=_LIKE_ESCAPE), literal(_CONTAINS)),
            else_=(
                # `similarity` is 0..1; scaled so a perfect trigram match still
                # loses to a literal `contains`.
                func.similarity(func.lower(text), lowered) * literal(_FUZZY_MAX)
                if fuzzy
                else literal(0.0)
            ),
        )
        branches.append(graded)

    score = branches[0]
    for branch in branches[1:]:
        score = func.greatest(score, branch)
    return score


def _needle_match(columns: Sequence[Any], needle: str) -> ColumnElement[bool]:
    """Whether this needle appears in any of the columns, typos included."""
    lowered = needle.lower()
    escaped = _escape_like(lowered)
    clauses: list[ColumnElement[bool]] = [
        _text(column).ilike(f"%{escaped}%", escape=_LIKE_ESCAPE) for column in columns
    ]
    if len(lowered) >= _FUZZY_MIN_LENGTH:
        # pg_trgm's `%` operator, not `similarity() > x`: only the operator can use
        # the GIN trigram index, and it honours `pg_trgm.similarity_threshold`
        # rather than hardcoding a cutoff this module would have to tune blind.
        clauses.extend(
            func.lower(_text(column)).op("%", is_comparison=True)(lowered) for column in columns
        )
    return or_(*clauses)


def _text_conditions(
    parsed: ParsedQuery, columns: Sequence[Any]
) -> tuple[list[ColumnElement[bool]], ColumnElement[float]]:
    """The WHERE fragments and the ORDER BY score for a provider's searchable columns."""
    conditions: list[ColumnElement[bool]] = [
        _needle_match(columns, needle) for needle in parsed.needles
    ]

    for excluded in parsed.exclusions:
        escaped = _escape_like(excluded.lower())
        conditions.append(
            ~or_(*(_text(column).ilike(f"%{escaped}%", escape=_LIKE_ESCAPE) for column in columns))
        )

    if not parsed.needles:
        # A filter-only query (`type:voucher status:overdue`) is legitimate and
        # everything ties at zero -- the provider's own recency ordering breaks it.
        return conditions, literal(0.0)

    score = _needle_score(columns, parsed.needles[0])
    for needle in parsed.needles[1:]:
        score = score + _needle_score(columns, needle)
    return conditions, score


# ---------------------------------------------------------------------------
# Filter primitives
# ---------------------------------------------------------------------------


def _enum_condition(
    column: Any,
    enum_cls: type[StrEnum],
    values: Sequence[str],
    *,
    negate: bool = False,
) -> ColumnElement[bool] | None:
    """`status:` applied to one provider's own enum.

    =========================================================================
    AN UNRECOGNISED VALUE MATCHES NOTHING, AND THAT IS THE FEATURE
    =========================================================================
        `status:paid` is a voucher status. In a fan-out it is evaluated against
        students too, where "paid" is not a status at all. Skipping the filter there
        would dump the entire student directory into a search that plainly meant
        vouchers; returning nothing is what the user asked for.

        Negation inverts that reading: `-status:paid` excludes nothing from students,
        because no student was ever paid.
    """
    if not values:
        return None
    valid = {member.value for member in enum_cls}
    matched = [value for value in values if value in valid]
    if not matched:
        return true() if negate else false()
    condition: ColumnElement[bool] = column.in_(matched)
    return ~condition if negate else condition


def _date_conditions(parsed: ParsedQuery, column: Any) -> list[ColumnElement[bool]]:
    """`after:`/`before:` as inclusive whole-day bounds on a date or timestamp column.

    Both ends are inclusive because that is how a person reads them: `before:
    2026-03-31` means "up to and including the 31st", not "up to midnight on the
    30th". The upper bound is therefore the START of the next day with a strict `<`,
    which is the only formulation that is correct for a timestamp column regardless
    of the row's time-of-day.
    """
    conditions: list[ColumnElement[bool]] = []
    is_timestamp = isinstance(column.type, DateTime)

    if (lower := parsed.date_bound("after")) is not None:
        conditions.append(column >= (_start_of(lower) if is_timestamp else lower))
    if (upper := parsed.date_bound("before")) is not None:
        if is_timestamp:
            conditions.append(column < _start_of(date.fromordinal(upper.toordinal() + 1)))
        else:
            conditions.append(column <= upper)
    return conditions


def _start_of(day: date) -> datetime:
    """Midnight UTC on `day`. Timestamps are stored timezone-aware throughout."""
    return datetime.combine(day, time.min, tzinfo=UTC)


def _like_any(columns: Sequence[Any], values: Sequence[str]) -> ColumnElement[bool] | None:
    """A free-text filter such as `class:` or `role:`, matched across columns."""
    if not values:
        return None
    clauses: list[ColumnElement[bool]] = []
    for value in values:
        escaped = _escape_like(value.lower())
        clauses.extend(
            _text(column).ilike(f"%{escaped}%", escape=_LIKE_ESCAPE) for column in columns
        )
    return or_(*clauses)


def _maybe_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# The repository
# ---------------------------------------------------------------------------

_ID = "id"
_TITLE = "title"
_SUBTITLE = "subtitle"
_CONTEXT = "context"
_STATUS = "status"
_SCHOOL_ID = "school_id"
_SCHOOL_NAME = "school_name"
_SCORE = "score"
_TOTAL = "total"


class SearchRepository:
    """Executes one provider's query at a time against a tenant-bound session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def run(
        self,
        provider: ProviderDef,
        parsed: ParsedQuery,
        scope: SearchScope,
        *,
        limit: int,
    ) -> tuple[list[RawHit], int]:
        """Rows for one provider, plus how many there were before truncation.

        The total comes from `count(*) OVER ()` in the SAME query rather than a
        second COUNT round trip. A fan-out over ten providers would otherwise be
        twenty queries per keystroke; this makes it ten. The window function is
        safe here in a way it is not in `BaseRepository.list` because these selects
        project explicit columns and never eager-load a collection -- so there are
        no join-duplicated rows for the window to over-count.
        """
        builder = _BUILDERS.get(provider.entity)
        if builder is None:  # pragma: no cover - registry and builders ship together
            return [], 0

        stmt = builder(parsed, scope)
        if stmt is None:
            return [], 0

        stmt = stmt.add_columns(func.count().over().label(_TOTAL)).limit(limit)
        rows = (await self.session.execute(stmt)).mappings().all()

        hits = [
            RawHit(
                entity=provider.entity,
                id=row[_ID],
                title=row[_TITLE] or "—",
                subtitle=row.get(_SUBTITLE),
                context=row.get(_CONTEXT),
                status=row.get(_STATUS),
                school_id=row.get(_SCHOOL_ID),
                school_name=row.get(_SCHOOL_NAME),
                score=float(row[_SCORE] or 0.0),
            )
            for row in rows
        ]
        total = int(rows[0][_TOTAL]) if rows else 0
        return hits, total


# ---------------------------------------------------------------------------
# Scoping helpers shared by every builder
# ---------------------------------------------------------------------------


def _scope_condition(column: Any, scope: SearchScope, *, nullable: bool) -> ColumnElement[bool]:
    """The campus boundary for one model's `school_id`.

    `nullable=True` additionally admits organization-level rows -- a principal's
    membership, an org-wide role -- which genuinely belong to every campus.
    """
    if scope.school_id is None:
        return true()
    match = column == scope.school_id
    return or_(match, column.is_(None)) if nullable else match


def _school_filter(parsed: ParsedQuery, column: Any) -> ColumnElement[bool] | None:
    """An explicit `school:` narrowing, on top of the resolved scope.

    NARROWS ONLY. The scope is already applied by the caller, and this is ANDed
    onto it, so `school:<some other campus>` from a campus-scoped member yields
    nothing rather than that campus's rows. Accepts an id, and falls through to a
    name/code match against the joined `schools` row for the far more likely case
    of someone typing `school:north`.
    """
    values = [v for v in parsed.filter_values("school") if v != "all"]
    if not values:
        return None
    ids = [parsed_id for value in values if (parsed_id := _maybe_uuid(value)) is not None]
    names = [value for value in values if _maybe_uuid(value) is None]

    clauses: list[ColumnElement[bool]] = []
    if ids:
        clauses.append(column.in_(ids))
    if names:
        named = _like_any([School.name, School.code], names)
        if named is not None:
            clauses.append(named)
    return or_(*clauses) if clauses else None


def _apply(stmt: Select[Any], conditions: Sequence[ColumnElement[bool] | None]) -> Select[Any]:
    """AND every non-None condition onto the statement."""
    real = [condition for condition in conditions if condition is not None]
    return stmt.where(and_(*real)) if real else stmt


def _order(stmt: Select[Any], score: ColumnElement[float], tiebreak: Any) -> Select[Any]:
    """Score first, then the provider's own notion of "most relevant otherwise".

    The final `id` is not decoration: without a total ordering, two rows with equal
    score and equal timestamp can swap places between the search call and the
    "see all" call, and the result list appears to shuffle under the cursor.
    """
    return stmt.order_by(score.desc(), tiebreak.desc(), literal_column_id(stmt))


def literal_column_id(stmt: Select[Any]) -> Any:
    """The `id` column already projected by the statement, for a stable final sort."""
    return stmt.selected_columns[_ID]


# ---------------------------------------------------------------------------
# Per-provider query builders
#
# Each returns a Select projecting the uniform column set, or None when the query
# cannot match this provider at all (a `class:` filter on fee heads, say) -- which
# skips the round trip entirely rather than running SQL known to return nothing.
# ---------------------------------------------------------------------------


def _build_student(parsed: ParsedQuery, scope: SearchScope) -> Select[Any] | None:
    full_name = func.concat(Student.first_name, " ", Student.last_name)
    columns = [
        full_name,
        Student.first_name,
        Student.last_name,
        Student.admission_number,
        Student.guardian_name,
        Student.guardian_phone,
        Student.guardian_email,
        Student.emergency_contact_name,
        Student.emergency_contact_phone,
    ]
    text_conditions, score = _text_conditions(parsed, columns)

    class_label = func.concat(
        func.coalesce(SchoolClass.name, ""),
        case((Section.name.is_(None), ""), else_=func.concat(" — ", Section.name)),
    )

    stmt = (
        select(
            Student.id.label(_ID),
            full_name.label(_TITLE),
            Student.admission_number.label(_SUBTITLE),
            func.nullif(class_label, "").label(_CONTEXT),
            cast(Student.status, String).label(_STATUS),
            Student.school_id.label(_SCHOOL_ID),
            School.name.label(_SCHOOL_NAME),
            score.label(_SCORE),
        )
        .outerjoin(Section, Section.id == Student.section_id)
        .outerjoin(SchoolClass, SchoolClass.id == Section.class_id)
        .outerjoin(School, School.id == Student.school_id)
    )

    stmt = _apply(
        stmt,
        [
            Student.deleted_at.is_(None),
            _scope_condition(Student.school_id, scope, nullable=False),
            _school_filter(parsed, Student.school_id),
            *text_conditions,
            _enum_condition(Student.status, StudentStatus, parsed.filter_values("status")),
            _enum_condition(
                Student.status,
                StudentStatus,
                parsed.negated_filters.get("status", ()),
                negate=True,
            ),
            _like_any(
                [SchoolClass.name, cast(SchoolClass.level, String)], parsed.filter_values("class")
            ),
            _like_any([Section.name], parsed.filter_values("section")),
            *_date_conditions(parsed, Student.created_at),
        ],
    )
    return _order(stmt, score, Student.created_at)


def _build_member(parsed: ParsedQuery, scope: SearchScope) -> Select[Any] | None:
    columns = [User.full_name, User.email, User.phone, Role.name]
    text_conditions, score = _text_conditions(parsed, columns)

    stmt = (
        select(
            Membership.id.label(_ID),
            User.full_name.label(_TITLE),
            cast(User.email, String).label(_SUBTITLE),
            Role.name.label(_CONTEXT),
            cast(Membership.status, String).label(_STATUS),
            Membership.school_id.label(_SCHOOL_ID),
            School.name.label(_SCHOOL_NAME),
            score.label(_SCORE),
        )
        .join(User, User.id == Membership.user_id)
        .join(Role, Role.id == Membership.role_id)
        .outerjoin(School, School.id == Membership.school_id)
    )

    stmt = _apply(
        stmt,
        [
            Membership.deleted_at.is_(None),
            User.deleted_at.is_(None),
            _scope_condition(Membership.school_id, scope, nullable=True),
            _school_filter(parsed, Membership.school_id),
            *text_conditions,
            _enum_condition(Membership.status, MembershipStatus, parsed.filter_values("status")),
            _enum_condition(
                Membership.status,
                MembershipStatus,
                parsed.negated_filters.get("status", ()),
                negate=True,
            ),
            _like_any([Role.name, Role.code], parsed.filter_values("role")),
        ],
    )
    return _order(stmt, score, Membership.created_at)


def _build_voucher(parsed: ParsedQuery, scope: SearchScope) -> Select[Any] | None:
    student_name = func.concat(Student.first_name, " ", Student.last_name)
    columns = [
        FeeVoucher.voucher_number,
        student_name,
        Student.admission_number,
        FeeVoucher.period_label,
        FeeVoucher.academic_year,
        FeeVoucher.notes,
    ]
    text_conditions, score = _text_conditions(parsed, columns)

    stmt = (
        select(
            FeeVoucher.id.label(_ID),
            FeeVoucher.voucher_number.label(_TITLE),
            student_name.label(_SUBTITLE),
            func.concat(FeeVoucher.period_label, " · ", FeeVoucher.academic_year).label(_CONTEXT),
            cast(FeeVoucher.status, String).label(_STATUS),
            FeeVoucher.school_id.label(_SCHOOL_ID),
            School.name.label(_SCHOOL_NAME),
            score.label(_SCORE),
        )
        .join(Student, Student.id == FeeVoucher.student_id)
        .outerjoin(School, School.id == FeeVoucher.school_id)
    )

    stmt = _apply(
        stmt,
        [
            _scope_condition(FeeVoucher.school_id, scope, nullable=False),
            _school_filter(parsed, FeeVoucher.school_id),
            *text_conditions,
            _enum_condition(FeeVoucher.status, VoucherStatus, parsed.filter_values("status")),
            _enum_condition(
                FeeVoucher.status,
                VoucherStatus,
                parsed.negated_filters.get("status", ()),
                negate=True,
            ),
            _like_any([FeeVoucher.academic_year], parsed.filter_values("year")),
            # Dated on ISSUE date, not `created_at`: an accountant asking for
            # `after:2026-04-01` means vouchers *for* April, not rows a batch job
            # happened to write then.
            *_date_conditions(parsed, FeeVoucher.issue_date),
        ],
    )
    return _order(stmt, score, FeeVoucher.issue_date)


def _build_class(parsed: ParsedQuery, scope: SearchScope) -> Select[Any] | None:
    columns = [SchoolClass.name, cast(SchoolClass.level, String)]
    text_conditions, score = _text_conditions(parsed, columns)

    stmt = select(
        SchoolClass.id.label(_ID),
        SchoolClass.name.label(_TITLE),
        func.concat("Level ", cast(SchoolClass.level, String)).label(_SUBTITLE),
        literal(None, String).label(_CONTEXT),
        literal(None, String).label(_STATUS),
        SchoolClass.school_id.label(_SCHOOL_ID),
        School.name.label(_SCHOOL_NAME),
        score.label(_SCORE),
    ).outerjoin(School, School.id == SchoolClass.school_id)

    stmt = _apply(
        stmt,
        [
            SchoolClass.deleted_at.is_(None),
            _scope_condition(SchoolClass.school_id, scope, nullable=False),
            _school_filter(parsed, SchoolClass.school_id),
            *text_conditions,
            # A class has no lifecycle state, so any `status:` at all rules it out.
            false() if parsed.filter_values("status") else None,
        ],
    )
    return _order(stmt, score, SchoolClass.level)


def _build_section(parsed: ParsedQuery, scope: SearchScope) -> Select[Any] | None:
    label = func.concat(SchoolClass.name, " — ", Section.name)
    columns = [label, Section.name, SchoolClass.name]
    text_conditions, score = _text_conditions(parsed, columns)

    stmt = (
        select(
            Section.id.label(_ID),
            label.label(_TITLE),
            case(
                (Section.capacity.is_(None), literal(None, String)),
                else_=func.concat("Capacity ", cast(Section.capacity, String)),
            ).label(_SUBTITLE),
            SchoolClass.name.label(_CONTEXT),
            literal(None, String).label(_STATUS),
            Section.school_id.label(_SCHOOL_ID),
            School.name.label(_SCHOOL_NAME),
            score.label(_SCORE),
        )
        .join(SchoolClass, SchoolClass.id == Section.class_id)
        .outerjoin(School, School.id == Section.school_id)
    )

    stmt = _apply(
        stmt,
        [
            Section.deleted_at.is_(None),
            SchoolClass.deleted_at.is_(None),
            _scope_condition(Section.school_id, scope, nullable=False),
            _school_filter(parsed, Section.school_id),
            *text_conditions,
            _like_any(
                [SchoolClass.name, cast(SchoolClass.level, String)], parsed.filter_values("class")
            ),
            false() if parsed.filter_values("status") else None,
        ],
    )
    return _order(stmt, score, SchoolClass.level)


def _build_school(parsed: ParsedQuery, scope: SearchScope) -> Select[Any] | None:
    columns = [School.name, School.code, School.city, School.email, School.phone]
    text_conditions, score = _text_conditions(parsed, columns)

    stmt = select(
        School.id.label(_ID),
        School.name.label(_TITLE),
        School.code.label(_SUBTITLE),
        School.city.label(_CONTEXT),
        cast(School.status, String).label(_STATUS),
        School.id.label(_SCHOOL_ID),
        School.name.label(_SCHOOL_NAME),
        score.label(_SCORE),
    )

    stmt = _apply(
        stmt,
        [
            School.deleted_at.is_(None),
            # The campus boundary applies to the campus LIST as well: a member
            # confined to one branch searches one branch, including here.
            _scope_condition(School.id, scope, nullable=False),
            _school_filter(parsed, School.id),
            *text_conditions,
            _enum_condition(School.status, SchoolStatus, parsed.filter_values("status")),
            _enum_condition(
                School.status, SchoolStatus, parsed.negated_filters.get("status", ()), negate=True
            ),
        ],
    )
    return _order(stmt, score, School.name)


def _build_invitation(parsed: ParsedQuery, scope: SearchScope) -> Select[Any] | None:
    columns = [Invitation.email, Invitation.full_name, Role.name]
    text_conditions, score = _text_conditions(parsed, columns)

    stmt = (
        select(
            Invitation.id.label(_ID),
            func.coalesce(Invitation.full_name, cast(Invitation.email, String)).label(_TITLE),
            cast(Invitation.email, String).label(_SUBTITLE),
            Role.name.label(_CONTEXT),
            cast(Invitation.status, String).label(_STATUS),
            Invitation.school_id.label(_SCHOOL_ID),
            School.name.label(_SCHOOL_NAME),
            score.label(_SCORE),
        )
        .join(Role, Role.id == Invitation.role_id)
        .outerjoin(School, School.id == Invitation.school_id)
    )

    stmt = _apply(
        stmt,
        [
            _scope_condition(Invitation.school_id, scope, nullable=True),
            _school_filter(parsed, Invitation.school_id),
            *text_conditions,
            _enum_condition(Invitation.status, InvitationStatus, parsed.filter_values("status")),
            _enum_condition(
                Invitation.status,
                InvitationStatus,
                parsed.negated_filters.get("status", ()),
                negate=True,
            ),
            _like_any([Role.name, Role.code], parsed.filter_values("role")),
            *_date_conditions(parsed, Invitation.created_at),
        ],
    )
    return _order(stmt, score, Invitation.created_at)


def _build_role(parsed: ParsedQuery, scope: SearchScope) -> Select[Any] | None:
    columns = [Role.name, Role.code, Role.description]
    text_conditions, score = _text_conditions(parsed, columns)

    stmt = select(
        Role.id.label(_ID),
        Role.name.label(_TITLE),
        Role.code.label(_SUBTITLE),
        Role.description.label(_CONTEXT),
        case((Role.is_system, literal("system")), else_=literal("custom")).label(_STATUS),
        Role.school_id.label(_SCHOOL_ID),
        School.name.label(_SCHOOL_NAME),
        score.label(_SCORE),
    ).outerjoin(School, School.id == Role.school_id)

    stmt = _apply(
        stmt,
        [
            _scope_condition(Role.school_id, scope, nullable=True),
            _school_filter(parsed, Role.school_id),
            *text_conditions,
            # `status:system` / `status:custom` -- the only lifecycle a role has.
            _role_status(parsed.filter_values("status")),
        ],
    )
    return _order(stmt, score, Role.created_at)


def _role_status(values: Sequence[str]) -> ColumnElement[bool] | None:
    if not values:
        return None
    wants_system = "system" in values
    wants_custom = "custom" in values
    if wants_system and wants_custom:
        return None
    if wants_system:
        return Role.is_system.is_(True)
    if wants_custom:
        return Role.is_system.is_(False)
    return false()


def _build_fee_head(parsed: ParsedQuery, scope: SearchScope) -> Select[Any] | None:
    columns = [FeeHead.name, FeeHead.code, FeeHead.description]
    text_conditions, score = _text_conditions(parsed, columns)

    stmt = select(
        FeeHead.id.label(_ID),
        FeeHead.name.label(_TITLE),
        FeeHead.code.label(_SUBTITLE),
        cast(FeeHead.recurrence, String).label(_CONTEXT),
        case((FeeHead.is_active, literal("active")), else_=literal("inactive")).label(_STATUS),
        FeeHead.school_id.label(_SCHOOL_ID),
        School.name.label(_SCHOOL_NAME),
        score.label(_SCORE),
    ).outerjoin(School, School.id == FeeHead.school_id)

    stmt = _apply(
        stmt,
        [
            FeeHead.deleted_at.is_(None),
            _scope_condition(FeeHead.school_id, scope, nullable=False),
            _school_filter(parsed, FeeHead.school_id),
            *text_conditions,
            _active_status(FeeHead.is_active, parsed.filter_values("status")),
        ],
    )
    return _order(stmt, score, FeeHead.sort_order)


def _active_status(column: Any, values: Sequence[str]) -> ColumnElement[bool] | None:
    """`status:active` / `status:inactive` against a boolean `is_active` column.

    Asking for both is the same as asking for neither, so it drops the filter rather
    than building `is_active IN (true, false)` -- same rows, one less predicate.
    Anything else (`status:paid` reaching a fee head in a fan-out) matches nothing,
    for the reason `_enum_condition` documents at length.
    """
    if not values:
        return None
    wants_active = "active" in values
    wants_inactive = "inactive" in values
    if wants_active and wants_inactive:
        return None
    if wants_active:
        is_active: ColumnElement[bool] = column.is_(True)
        return is_active
    if wants_inactive:
        is_inactive: ColumnElement[bool] = column.is_(False)
        return is_inactive
    return false()


def _build_fee_structure(parsed: ParsedQuery, scope: SearchScope) -> Select[Any] | None:
    columns = [FeeStructure.name, FeeStructure.academic_year, SchoolClass.name]
    text_conditions, score = _text_conditions(parsed, columns)

    stmt = (
        select(
            FeeStructure.id.label(_ID),
            FeeStructure.name.label(_TITLE),
            FeeStructure.academic_year.label(_SUBTITLE),
            SchoolClass.name.label(_CONTEXT),
            cast(FeeStructure.status, String).label(_STATUS),
            FeeStructure.school_id.label(_SCHOOL_ID),
            School.name.label(_SCHOOL_NAME),
            score.label(_SCORE),
        )
        .join(SchoolClass, SchoolClass.id == FeeStructure.class_id)
        .outerjoin(School, School.id == FeeStructure.school_id)
    )

    stmt = _apply(
        stmt,
        [
            FeeStructure.deleted_at.is_(None),
            _scope_condition(FeeStructure.school_id, scope, nullable=False),
            _school_filter(parsed, FeeStructure.school_id),
            *text_conditions,
            _enum_condition(
                FeeStructure.status, FeeStructureStatus, parsed.filter_values("status")
            ),
            _enum_condition(
                FeeStructure.status,
                FeeStructureStatus,
                parsed.negated_filters.get("status", ()),
                negate=True,
            ),
            _like_any([FeeStructure.academic_year], parsed.filter_values("year")),
            _like_any(
                [SchoolClass.name, cast(SchoolClass.level, String)], parsed.filter_values("class")
            ),
        ],
    )
    return _order(stmt, score, FeeStructure.created_at)


def _build_audit(parsed: ParsedQuery, scope: SearchScope) -> Select[Any] | None:
    columns = [AuditLog.action, AuditLog.entity_type, User.full_name]
    text_conditions, score = _text_conditions(parsed, columns)

    stmt = (
        select(
            AuditLog.id.label(_ID),
            AuditLog.action.label(_TITLE),
            User.full_name.label(_SUBTITLE),
            AuditLog.entity_type.label(_CONTEXT),
            literal(None, String).label(_STATUS),
            AuditLog.school_id.label(_SCHOOL_ID),
            School.name.label(_SCHOOL_NAME),
            score.label(_SCORE),
        )
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .outerjoin(School, School.id == AuditLog.school_id)
    )

    stmt = _apply(
        stmt,
        [
            _scope_condition(AuditLog.school_id, scope, nullable=True),
            _school_filter(parsed, AuditLog.school_id),
            *text_conditions,
            *_date_conditions(parsed, AuditLog.created_at),
        ],
    )
    return _order(stmt, score, AuditLog.created_at)


_BUILDERS: dict[SearchEntity, Any] = {
    SearchEntity.STUDENT: _build_student,
    SearchEntity.MEMBER: _build_member,
    SearchEntity.VOUCHER: _build_voucher,
    SearchEntity.CLASS: _build_class,
    SearchEntity.SECTION: _build_section,
    SearchEntity.SCHOOL: _build_school,
    SearchEntity.INVITATION: _build_invitation,
    SearchEntity.ROLE: _build_role,
    SearchEntity.FEE_HEAD: _build_fee_head,
    SearchEntity.FEE_STRUCTURE: _build_fee_structure,
    SearchEntity.AUDIT: _build_audit,
}
