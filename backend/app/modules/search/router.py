"""Global search HTTP endpoints.

=============================================================================
WHY THESE ROUTES CARRY NO `require(...)`
=============================================================================
    Every other route in this codebase names a permission. These three do not, and
    that is not an oversight -- it is the only correct shape for this endpoint.

    A `require("search:read")` would be a NEW permission that grants nothing on its
    own and, worse, would have to be added to every existing custom role or search
    would 403 for them. And a `require("student:read")` would lock the accountant
    out of searching vouchers, which they may read, over a student permission they
    may not hold.

    So authorisation is per RESULT, not per ROUTE: `providers.permitted()` runs the
    caller's permission set against each entity kind, and a provider that fails is
    never queried. The endpoint is reachable by any authenticated member and
    returns the union of what they could already have read one page at a time.

    `CurrentAuth` -- not `require(...)` -- is therefore the correct dependency: it
    still re-reads the membership on every request, so a suspended member's search
    stops working immediately, exactly like every other route.

WHY THERE IS NO WRITE HERE
    Search records nothing. No "recent searches" table, no popularity counter. A
    row per keystroke per user is a surprising amount of write traffic and a
    surprising amount of retained personal data (the names staff look up) for a
    feature whose entire job is to read. Recent searches live in the browser, where
    they belong to the person who typed them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentAuth, DbSession
from app.core.context import get_school_id
from app.modules.search.query import MAX_QUERY_LENGTH
from app.modules.search.schemas import (
    SearchConfigResponse,
    SearchResponse,
    SearchSuggestion,
)
from app.modules.search.service import (
    DEFAULT_GROUP_LIMIT,
    MAX_GROUP_LIMIT,
    SUGGEST_LIMIT,
    SearchPrincipal,
    SearchService,
)

router = APIRouter()

_QUERY_DESCRIPTION = (
    "Search text. Supports `key:value` filters (`type:`, `status:`, `class:`, "
    "`section:`, `role:`, `year:`, `school:`, `after:`, `before:`), "
    '`"quoted phrases"`, and `-exclusions`. Unknown filters are searched as text.'
)

SearchTerm = Annotated[
    str | None,
    Query(max_length=MAX_QUERY_LENGTH, description=_QUERY_DESCRIPTION),
]


def _principal(ctx: CurrentAuth) -> SearchPrincipal:
    """Narrow the auth context to what search is allowed to know.

    `get_school_id()` rather than `ctx.school_id`: for an organization-level caller
    those differ, and the difference is the point. `ctx.school_id` is the MEMBERSHIP
    scope (None for a principal, and what decides whether widening is permitted at
    all); the ContextVar additionally carries the campus they currently have open,
    which narrows the view. Passing both keeps that distinction explicit in
    `SearchService.resolve_scope` instead of collapsing it here.
    """
    return SearchPrincipal(
        organization_id=ctx.organization_id,
        role_code=ctx.role_code,
        permissions=ctx.permissions,
        membership_school_id=ctx.school_id,
        active_school_id=get_school_id(),
    )


@router.get(
    "",
    response_model=SearchResponse,
    summary="Search everything this member can see",
)
async def search(
    ctx: CurrentAuth,
    db: DbSession,
    q: SearchTerm = None,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_GROUP_LIMIT, description="Results per entity type."),
    ] = DEFAULT_GROUP_LIMIT,
) -> SearchResponse:
    """Grouped, ranked results across every entity kind the caller may read.

    An empty or whitespace-only `q` returns an empty result rather than a 422: the
    omnibar calls this as the user clears the box, and an error there would render
    as a failure toast for the act of deleting text.
    """
    return await SearchService(db, _principal(ctx)).search(q, group_limit=limit)


@router.get(
    "/suggest",
    response_model=list[SearchSuggestion],
    summary="Typeahead suggestions",
)
async def suggest(
    ctx: CurrentAuth,
    db: DbSession,
    q: SearchTerm = None,
    limit: Annotated[int, Query(ge=1, le=20)] = SUGGEST_LIMIT,
) -> list[SearchSuggestion]:
    """A flat, ranked list for the dropdown under the input.

    Same ranking as `/search`, by construction -- see `SearchService.suggest`.
    """
    return await SearchService(db, _principal(ctx)).suggest(q, limit=limit)


@router.get(
    "/config",
    response_model=SearchConfigResponse,
    summary="What this member's search box can do",
)
async def config(ctx: CurrentAuth, db: DbSession) -> SearchConfigResponse:
    """The scopes, filters and example queries available to THIS caller.

    Fetched once when the omnibar mounts. It is derived entirely from the caller's
    permissions and role, which is what keeps the frontend from having to hold its
    own copy of the permission catalog -- a copy that would drift the first time a
    permission is renamed.
    """
    return SearchService(db, _principal(ctx)).config()
