"""Cross-cutting Pydantic schemas shared by every module.

WHY THIS FILE EXISTS
    Pagination, sorting and error payloads look identical for students, invoices,
    teachers and inventory items. Defining them once means the frontend learns one
    response shape and reuses one TypeScript type across the entire API.

RESPONSIBILITY
    Generic, domain-agnostic request/response contracts. No business rules here.

INTERACTIONS
    * `Page[T]` is the declared `response_model` of every list endpoint.
    * `PageParams`/`SortParams` are FastAPI dependencies on those endpoints.
    * `ProblemDetail` is what `api/errors.py` renders for every failure.

DESIGN DECISION -- no success envelope
    A tempting pattern is wrapping everything as `{"success": true, "data": {...}}`.
    We deliberately do not. HTTP already encodes success in the status code, and the
    envelope makes OpenAPI-generated client types markedly worse (every response
    becomes a generic wrapper the caller must unwrap). Errors DO get a structured
    body because HTTP does not standardise one -- that is what RFC 9457 is for.
"""

from __future__ import annotations

from enum import StrEnum
from math import ceil
from typing import Annotated, Any, Self

from fastapi import Query
from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """Base for every schema in the project.

    `from_attributes=True` lets a schema be built directly from a SQLAlchemy ORM
    object (`StudentRead.model_validate(student_orm)`), which is how services
    convert models into responses.

    NOTE (deviation from the skill playbook): the playbook calls `.dict()`, removed
    in Pydantic v2. Use `.model_dump()`.
    """

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,  # " Ahmed " -> "Ahmed"; prevents duplicate-looking rows
        use_enum_values=False,
    )


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


class PageParams(BaseModel):
    """Offset pagination query parameters, used as a FastAPI dependency.

    WHY OFFSET AND NOT CURSOR: the primary consumers are admin tables that need
    "jump to page 7" and a total count. Offset pagination degrades on very deep
    pages (the database must skip N rows), which is irrelevant for a single school's
    few thousand students. If a listing ever grows unbounded -- an audit log, say --
    that specific endpoint should switch to keyset pagination.
    """

    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1
    size: Annotated[int, Query(ge=1, le=100, description="Items per page")] = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.size

    @property
    def limit(self) -> int:
        return self.size


class SortDirection(StrEnum):
    ASC = "asc"
    DESC = "desc"


class SortParams(BaseModel):
    """Sorting parameters.

    SECURITY NOTE: `sort_by` is a raw string from the client and must never be
    interpolated into SQL. `BaseRepository.apply_sort` resolves it against an
    explicit per-repository allowlist of sortable columns and rejects anything
    else -- an allowlist, not a denylist.
    """

    sort_by: Annotated[str | None, Query(description="Field name to sort by")] = None
    sort_dir: Annotated[SortDirection, Query(description="Sort direction")] = SortDirection.ASC


class PageMeta(BaseModel):
    """Pagination metadata; everything a table UI needs to render its controls."""

    page: int
    size: int
    total: int
    pages: int
    has_next: bool
    has_prev: bool


class Page[T](BaseModel):
    """Generic paginated response: `Page[StudentRead]`.

    Uses PEP 695 generic syntax (Python 3.12+) rather than `Generic[T]`.
    FastAPI renders each concrete parameterisation as its own OpenAPI schema, so
    the frontend gets a precise `PageStudentRead` type instead of `Page<any>`.
    """

    items: list[T]
    meta: PageMeta

    @classmethod
    def create(cls, items: list[T], total: int, params: PageParams) -> Self:
        pages = ceil(total / params.size) if total else 0
        return cls(
            items=items,
            meta=PageMeta(
                page=params.page,
                size=params.size,
                total=total,
                pages=pages,
                has_next=params.page < pages,
                has_prev=params.page > 1,
            ),
        )


# ---------------------------------------------------------------------------
# Errors -- RFC 9457 Problem Details
# ---------------------------------------------------------------------------


class ProblemDetail(BaseModel):
    """RFC 9457 (formerly RFC 7807) error body.

    WHY A STANDARD INSTEAD OF AN AD-HOC SHAPE: RFC 9457 is what modern HTTP clients,
    API gateways and observability tools already understand. Adopting it means our
    errors are machine-readable by default.

    Fields:
      type     -- stable URI identifying the error class (documentation anchor)
      title    -- short human summary, stable per error type
      status   -- HTTP status code, duplicated in the body for logging convenience
      detail   -- human explanation specific to *this* occurrence
      instance -- the request id, so a user can quote it in a support ticket and we
                  can find the exact log line
      code     -- our stable machine code (e.g. NOT_FOUND); what frontends branch on
      errors   -- optional field-level validation failures
    """

    type: str = "about:blank"
    title: str
    status: int
    detail: str
    instance: str | None = None
    code: str
    errors: list[FieldError] | None = None
    meta: dict[str, Any] | None = None


class FieldError(BaseModel):
    """A single field-level validation failure."""

    field: str = Field(description="Dotted path to the offending field, e.g. 'address.city'")
    message: str
    type: str | None = None


# Resolve the forward reference used above.
ProblemDetail.model_rebuild()


class HealthStatus(BaseModel):
    """Response for the health endpoints."""

    status: str
    environment: str
    version: str
    database: str
