"""Wire contracts for global search.

WHY THE HIT IS FLAT AND UNIFORM
    The omnibar renders a student, a fee voucher and a role in the same list, with
    the same keyboard navigation. If each type had its own payload shape the
    frontend would need a renderer per type and a discriminated union to pick
    between them -- and every new provider would become a frontend release.

    So every provider projects onto ONE shape: title, subtitle, context, status,
    url. The type is carried as a discriminator for the icon and the group heading,
    not as a switch over the payload. Adding a provider is then a backend-only
    change, which is the property that makes the registry in `providers.py` worth
    having at all.

WHY THE RESPONSE CARRIES `parsed` AND `warnings`
    An advanced query language is only usable if the box tells you how it read what
    you typed. `parsed` lets the UI show "status = pending, class = Grade 10" as
    chips, and `warnings` is how `foo:bar` explains itself without the search
    failing. Both are presentation aids for a feature that is otherwise silent about
    its own behaviour.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import Field

from app.common.schemas import BaseSchema
from app.modules.search.providers import SearchEntity


class SearchHit(BaseSchema):
    """One result, in the shape every provider projects onto."""

    type: SearchEntity
    id: UUID

    title: str = Field(description='Primary label, e.g. "Ahmed Raza" or "V-2026-0042".')
    subtitle: str | None = Field(
        default=None, description="Secondary identifier, e.g. an admission number or email."
    )
    context: str | None = Field(
        default=None,
        description='Where this sits, e.g. "Grade 10 — A" or "Tuition · 2026-2027".',
    )

    status: str | None = Field(
        default=None, description="Lifecycle state, rendered as a badge by the UI."
    )
    school_id: UUID | None = None
    school_name: str | None = Field(
        default=None,
        description=(
            "Which campus this belongs to. Only meaningful for an organization-level "
            "caller searching across campuses; the UI shows it only when the results "
            "actually span more than one."
        ),
    )

    url: str = Field(description="Frontend deep link for this result.")

    matched_on: str | None = Field(
        default=None,
        description=(
            "Which field the search term was found in — 'name', 'subtitle', 'context'. "
            "Lets the UI explain a match that is not visible in the title, which is "
            "otherwise the single most confusing thing a fuzzy search can do."
        ),
    )
    score: float = Field(description="Relevance, after the caller's role profile is applied.")


class SearchGroup(BaseSchema):
    """All hits of one entity type, plus how many there were in total."""

    type: SearchEntity
    label: str
    icon: str

    hits: list[SearchHit]
    total: int = Field(
        description=(
            "Total matches of this type, not just the ones returned. Drives the "
            '"see all 47" link — a truncated list with no count is indistinguishable '
            "from a complete one."
        )
    )
    truncated: bool


class ParsedQueryRead(BaseSchema):
    """How the server read the query string. Rendered as filter chips by the UI."""

    terms: list[str]
    phrases: list[str]
    exclusions: list[str]
    filters: dict[str, list[str]]
    negated_filters: dict[str, list[str]]
    summary: list[str] = Field(description="Plain-English rendering of the above.")


class SearchResponse(BaseSchema):
    """The full fan-out result."""

    query: str
    parsed: ParsedQueryRead

    groups: list[SearchGroup] = Field(
        description="Non-empty groups only, ordered by the caller's role profile."
    )
    total: int = Field(description="Sum of every group's total.")

    searched_types: list[SearchEntity] = Field(
        description="Which providers actually ran. Reflects permissions and `type:`."
    )
    cross_school: bool = Field(
        description="True when this search spanned every campus rather than one."
    )
    took_ms: int
    warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal notes: unknown filters, ignored dates, capped terms.",
    )


class SearchSuggestion(BaseSchema):
    """A typeahead row: the same hit, minus everything the dropdown does not draw."""

    type: SearchEntity
    id: UUID
    title: str
    subtitle: str | None
    url: str
    icon: str


class SearchScopeRead(BaseSchema):
    """One entity kind this caller may search, as the UI needs to describe it."""

    type: SearchEntity
    label: str
    icon: str
    filters: list[str] = Field(description="Filter keys that do something for this type.")
    in_default_scan: bool = Field(
        description="False means it is only searched when named with `type:`."
    )


class SearchConfigResponse(BaseSchema):
    """What THIS caller's search box should look like.

    Fetched once when the omnibar mounts. Everything in it is derived from the
    caller's permissions and role, so a teacher's box offers different scopes and
    different examples from an accountant's -- without the frontend holding a copy
    of the permission catalog or a role-to-feature table that would drift from the
    backend's.
    """

    scopes: list[SearchScopeRead] = Field(
        description="Searchable types, ordered by what this role usually wants first."
    )
    filter_keys: list[str] = Field(description="Every recognised `key:` in the query language.")
    examples: list[str] = Field(
        description="Ready-made queries worth showing on an empty box, chosen for this role."
    )
    cross_school_available: bool = Field(
        description=(
            "Whether `school:all` does anything for this caller. True only for an "
            "organization-level member; a campus-scoped one cannot widen their scope."
        )
    )
    max_query_length: int
