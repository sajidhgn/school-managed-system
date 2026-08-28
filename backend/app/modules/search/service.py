"""Global search orchestration -- decide, scope, fan out, rank.

WHY THIS FILE EXISTS
    The pieces around it each know one thing: `query` knows syntax, `providers`
    knows who may see what, `repository` knows SQL. Something has to hold the
    sequence they run in, and that sequence is where the security properties
    actually live:

        1. parse            -- what did they type?
        2. permit           -- which providers may they reach at all?
        3. select           -- which of those did `type:` ask for?
        4. scope            -- which campus, and can they widen it? (they cannot)
        5. fan out          -- one bounded query per surviving provider
        6. rank             -- role profile applied to raw text scores
        7. group            -- most relevant kind first

    Steps 2 and 4 are the boundary. Everything after them is presentation, and
    everything before them is untrusted string handling.

INTERACTIONS
    Imports nothing from `app.api` and nothing from fastapi -- the router hands it
    a `SearchPrincipal` built from `AuthContext`. Keeping the dependency arrow
    pointing inward is what lets this be exercised directly from a test without
    building a request.

=============================================================================
WHAT IS DELIBERATELY NOT LOGGED
=============================================================================
    The query string is not written to the application log. `ahmed raza` typed
    into a school's search box is a child's name, and a log line is the wrong
    place for it -- it outlives the request, it fans out to wherever logs ship,
    and nothing operational needs it. Term COUNTS, provider names and timings are
    logged instead, which is everything required to debug a slow or empty search.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.search import providers as registry
from app.modules.search.providers import ProviderDef, SearchEntity
from app.modules.search.query import (
    ALL_SCOPE,
    FILTER_KEYS,
    MAX_QUERY_LENGTH,
    ParsedQuery,
    describe,
    parse,
)
from app.modules.search.repository import RawHit, SearchRepository, SearchScope
from app.modules.search.schemas import (
    ParsedQueryRead,
    SearchConfigResponse,
    SearchGroup,
    SearchHit,
    SearchResponse,
    SearchScopeRead,
    SearchSuggestion,
)

logger = get_logger(__name__)

DEFAULT_GROUP_LIMIT = 5
"""Hits per type in the omnibar. Five is what fits on screen above the fold with
several groups showing; the group's `total` carries the rest to a "see all" link."""

MAX_GROUP_LIMIT = 25
MAX_PROVIDERS_PER_SEARCH = 10
"""Ceiling on the fan-out: one indexed query per provider, run sequentially.

Set to exactly the number of providers in the default scan today, so it does NOT
bite for any current role -- a principal holds every permission and still searches
their whole set. That is deliberate. Silently dropping two entity kinds from the
broadest role's search is a product regression disguised as a performance guard,
and "why can't I find roles any more?" is not a question this cap should be able to
cause.

What it does buy is that adding a twelfth provider becomes a DECISION about omnibar
latency rather than a silent slowdown: the next one added tips this over, the
lowest-weighted types for each role drop out of the default scan, and the response
says so in `warnings` rather than looking like an empty result."""

SUGGEST_LIMIT = 8


@dataclass(frozen=True, slots=True)
class SearchPrincipal:
    """Who is searching, reduced to only what search needs.

    A deliberate narrowing of `AuthContext`. Search must not be able to read a
    membership id or mint anything; giving it the full context would make that
    possible by accident later.
    """

    organization_id: UUID
    role_code: str
    permissions: frozenset[str]

    membership_school_id: UUID | None
    """From the MEMBERSHIP. None means an organization-level member. This is the
    value that decides whether the caller may search across campuses at all, and it
    never comes from a header or a query parameter."""

    active_school_id: UUID | None
    """The campus currently open in the UI. For an org-level member this arrives
    from the `X-Active-School` header via the request ContextVar; it narrows the
    view and cannot widen authority (see `api/deps._extract_active_school`)."""

    @property
    def is_org_level(self) -> bool:
        return self.membership_school_id is None


class SearchService:
    """One search, end to end."""

    def __init__(self, session: AsyncSession, principal: SearchPrincipal) -> None:
        self.session = session
        self.principal = principal
        self.repo = SearchRepository(session)

    # -- the boundary -------------------------------------------------------

    def resolve_scope(self, parsed: ParsedQuery) -> tuple[SearchScope, list[str]]:
        """Which campus this search runs in.

        =====================================================================
        `school:all` IS THE ONLY WIDENING OPERATOR, AND ONLY ONE ROLE HAS IT
        =====================================================================
            A campus-scoped member's scope is their membership's school, full stop.
            `school:all` from them is acknowledged with a warning and otherwise
            ignored -- not an error, because the syntax is legal and they may have
            copied the query from a colleague, but not honoured either.

            An organization-level member (the principal) already spans campuses by
            definition: their membership carries no school and RLS bounds them to
            the organization. For them `school:all` does not grant anything new, it
            just sets aside the campus they happen to have open in the UI. That is
            why it is safe -- it removes a view preference, not a boundary.
        """
        warnings: list[str] = []
        wants_all = ALL_SCOPE in parsed.filter_values("school")

        if not self.principal.is_org_level:
            if wants_all:
                warnings.append(
                    "`school:all` needs organization-level access; searched your campus only."
                )
            return SearchScope(
                organization_id=self.principal.organization_id,
                school_id=self.principal.membership_school_id,
            ), warnings

        school_id = None if wants_all else self.principal.active_school_id
        return SearchScope(
            organization_id=self.principal.organization_id, school_id=school_id
        ), warnings

    # -- the search --------------------------------------------------------

    async def search(
        self,
        raw_query: str | None,
        *,
        group_limit: int = DEFAULT_GROUP_LIMIT,
    ) -> SearchResponse:
        started = time.perf_counter()
        parsed = parse(raw_query)
        warnings = list(parsed.warnings)

        available = registry.ordered_for(
            self.principal.role_code,
            self.principal.permissions,
            # `type:audit` must be able to reach a provider that is out of the
            # default scan -- otherwise "unavailable" would be a lie for a caller
            # who holds `audit:read`.
            include_hidden=True,
        )
        selected, selection_warnings = registry.resolve_requested(
            parsed.requested_types, parsed.excluded_types, available
        )
        warnings.extend(selection_warnings)

        scope, scope_warnings = self.resolve_scope(parsed)
        warnings.extend(scope_warnings)

        if parsed.is_empty or not selected:
            return self._empty(parsed, selected, scope, started, warnings)

        if len(selected) > MAX_PROVIDERS_PER_SEARCH:
            dropped = selected[MAX_PROVIDERS_PER_SEARCH:]
            selected = selected[:MAX_PROVIDERS_PER_SEARCH]
            # Never truncate silently: a search that quietly skipped four types
            # reads as "there is nothing there", which is the one wrong answer a
            # search box must not give.
            warnings.append(
                "Searched the "
                + str(MAX_PROVIDERS_PER_SEARCH)
                + " most relevant types for your role. Narrow with `type:` to reach: "
                + ", ".join(f"`{p.entity.value}`" for p in dropped)
                + "."
            )

        profile = registry.profile_for(self.principal.role_code, self.principal.permissions)
        limit = max(1, min(group_limit, MAX_GROUP_LIMIT))

        groups: list[SearchGroup] = []
        for provider in selected:
            # Sequential, not gathered: one AsyncSession is a single connection and
            # concurrent statements on it are a runtime error, not a speedup. The
            # per-provider limit and the provider cap are what keep the total bounded.
            rows, total = await self.repo.run(provider, parsed, scope, limit=limit)
            if not rows:
                continue
            weight = profile[provider.entity]
            groups.append(
                SearchGroup(
                    type=provider.entity,
                    label=provider.label,
                    icon=provider.icon,
                    hits=[self._to_hit(provider, row, weight, parsed) for row in rows],
                    total=total,
                    truncated=total > len(rows),
                )
            )

        groups.sort(key=lambda g: (-max(h.score for h in g.hits), -profile[g.type], g.label))

        took_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "search_executed",
            # The query itself is never logged -- see the module docstring.
            term_count=len(parsed.needles),
            filter_count=len(parsed.filters),
            types=[p.entity.value for p in selected],
            groups=len(groups),
            cross_school=scope.cross_school,
            took_ms=took_ms,
        )

        return SearchResponse(
            query=parsed.raw,
            parsed=_parsed_read(parsed),
            groups=groups,
            total=sum(g.total for g in groups),
            searched_types=[p.entity for p in selected],
            cross_school=scope.cross_school,
            took_ms=took_ms,
            warnings=warnings,
        )

    async def suggest(
        self, raw_query: str | None, *, limit: int = SUGGEST_LIMIT
    ) -> list[SearchSuggestion]:
        """Flat, ranked typeahead rows for the dropdown.

        Deliberately a thin wrapper over `search` rather than a second query path.
        A suggest endpoint that ranked differently from the full search is a
        promise the results page then breaks -- you click "see all" and the row you
        were looking at is somewhere else.
        """
        response = await self.search(raw_query, group_limit=3)
        flat = [hit for group in response.groups for hit in group.hits]
        flat.sort(key=lambda hit: hit.score, reverse=True)

        icons = {group.type: group.icon for group in response.groups}
        return [
            SearchSuggestion(
                type=hit.type,
                id=hit.id,
                title=hit.title,
                subtitle=hit.subtitle,
                url=hit.url,
                icon=icons.get(hit.type, "Search"),
            )
            for hit in flat[:limit]
        ]

    # -- the caller's own search box ---------------------------------------

    def config(self) -> SearchConfigResponse:
        """Everything the omnibar needs to render itself for THIS caller.

        The frontend holds no copy of the permission catalog and no role-to-scope
        table: it asks. Which means a permission edit in the roles screen changes
        what the search box offers on the next page load, with no deploy.
        """
        scopes = registry.ordered_for(
            self.principal.role_code, self.principal.permissions, include_hidden=True
        )
        return SearchConfigResponse(
            scopes=[
                SearchScopeRead(
                    type=p.entity,
                    label=p.label,
                    icon=p.icon,
                    filters=list(p.filters),
                    in_default_scan=p.in_default_scan,
                )
                for p in scopes
            ],
            filter_keys=sorted(FILTER_KEYS),
            examples=_examples_for(scopes, cross_school=self.principal.is_org_level),
            cross_school_available=self.principal.is_org_level,
            max_query_length=MAX_QUERY_LENGTH,
        )

    # -- helpers -----------------------------------------------------------

    def _empty(
        self,
        parsed: ParsedQuery,
        selected: Sequence[ProviderDef],
        scope: SearchScope,
        started: float,
        warnings: list[str],
    ) -> SearchResponse:
        return SearchResponse(
            query=parsed.raw,
            parsed=_parsed_read(parsed),
            groups=[],
            total=0,
            searched_types=[p.entity for p in selected],
            cross_school=scope.cross_school,
            took_ms=int((time.perf_counter() - started) * 1000),
            warnings=warnings,
        )

    def _to_hit(
        self, provider: ProviderDef, row: RawHit, weight: float, parsed: ParsedQuery
    ) -> SearchHit:
        return SearchHit(
            type=row.entity,
            id=row.id,
            title=row.title,
            subtitle=row.subtitle,
            context=row.context,
            status=row.status,
            school_id=row.school_id,
            school_name=row.school_name,
            url=_url_for(provider, row),
            matched_on=_matched_on(row, parsed),
            # The role profile multiplies the TEXT score rather than being added to
            # it. Multiplication keeps a strong literal match ahead of a weak match
            # in a favoured type -- an accountant searching a student's exact name
            # still gets that student first, ahead of a fuzzily-matched voucher.
            score=round(row.score * weight, 4),
        )


def _url_for(provider: ProviderDef, row: RawHit) -> str:
    """Fill the provider's deep link.

    Three destinations are a record (`/students/{id}`); the rest are the module's
    list page, because those modules have no detail page and no filter to point at.
    Both shapes are expressed as a template so the difference lives in the registry
    rather than in a branch here -- see `ProviderDef.url_template`.
    """
    return provider.url_template.replace("{id}", str(row.id))


def _matched_on(row: RawHit, parsed: ParsedQuery) -> str | None:
    """Which visible field the match is in -- or None when it is in none of them.

    A `None` here is the interesting case, not a failure: it means the row matched
    on a column the result card does not show (a guardian's phone number, a
    voucher's notes). The UI says "matched elsewhere", which turns a baffling result
    into an explained one.
    """
    if not parsed.needles:
        return None
    for label, value in (
        ("title", row.title),
        ("subtitle", row.subtitle),
        ("context", row.context),
    ):
        if value and any(needle.lower() in value.lower() for needle in parsed.needles):
            return label
    return None


def _parsed_read(parsed: ParsedQuery) -> ParsedQueryRead:
    return ParsedQueryRead(
        terms=list(parsed.terms),
        phrases=list(parsed.phrases),
        exclusions=list(parsed.exclusions),
        filters={key: list(values) for key, values in parsed.filters.items()},
        negated_filters={key: list(values) for key, values in parsed.negated_filters.items()},
        summary=list(describe(parsed)),
    )


# Example queries, keyed by the entity they demonstrate. Only examples for types the
# caller can actually reach are offered -- showing an accountant `type:attendance`
# teaches them a query that returns nothing.
_EXAMPLES: dict[SearchEntity, str] = {
    SearchEntity.STUDENT: "type:student status:pending",
    SearchEntity.VOUCHER: "type:voucher -status:paid",
    SearchEntity.MEMBER: "type:member role:teacher",
    SearchEntity.SECTION: 'class:"Grade 10"',
    SearchEntity.CLASS: 'class:"Grade 10"',
    SearchEntity.INVITATION: "type:invitation status:pending",
    SearchEntity.FEE_STRUCTURE: "type:fee_structure year:2026-2027",
    SearchEntity.FEE_HEAD: "type:fee_head status:active",
    SearchEntity.ROLE: "type:role status:custom",
    SearchEntity.AUDIT: "type:audit after:2026-01-01",
    SearchEntity.SCHOOL: "type:school status:active",
}


def _examples_for(scopes: Sequence[ProviderDef], *, cross_school: bool) -> list[str]:
    """Three or four queries worth showing on an empty search box, for this role.

    Taken in the caller's own relevance order, so a teacher's first example is about
    students and an accountant's is about vouchers. An empty box is the only moment
    a user will read documentation for a query language; this is that documentation.
    """
    seen: set[str] = set()
    examples: list[str] = []
    for provider in scopes:
        example = _EXAMPLES.get(provider.entity)
        if example and example not in seen:
            seen.add(example)
            examples.append(example)
        if len(examples) == 3:
            break
    if cross_school:
        examples.append('school:all "grade 10"')
    return examples
