"""Tenant audit-log reads (spec §8 `GET /schools/{school_id}/audit-logs`).

WHY A SEPARATE FILE
    The audit trail is written by `common/audit.py` from every service, but READING
    it is one narrow, permission-gated endpoint. Putting it in `rbac/router.py`
    alongside roles and members would bury it; giving it a module makes the retention
    and redaction reasoning below findable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import AuthContext, DbSession, require
from app.common.schemas import BaseSchema
from app.modules.rbac.models import AuditLog
from app.modules.rbac.router import _assert_school_scope

router = APIRouter()


class AuditLogRead(BaseSchema):
    """One audit entry.

    `before`/`after` carry only the fields that changed, never whole rows -- see the
    model. A full snapshot would turn this endpoint into a second, less-protected
    copy of the student database with a longer retention period.
    """

    id: UUID
    school_id: UUID | None
    actor_user_id: UUID | None
    actor_membership_id: UUID | None
    action: str
    entity_type: str | None
    entity_id: UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ip: str | None
    created_at: datetime


@router.get("/{school_id}/audit-logs", response_model=list[AuditLogRead])
async def list_audit_logs(
    school_id: UUID,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("audit:read"))],
    action: Annotated[str | None, Query(max_length=100)] = None,
    entity_type: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    before: Annotated[datetime | None, Query()] = None,
) -> list[AuditLog]:
    """This school's audit trail, newest first.

    KEYSET PAGINATION, not offset. The audit log is the one table in this system that
    grows without bound, and `OFFSET 50000` makes PostgreSQL walk and discard fifty
    thousand rows on every page. `before=<timestamp>` seeks straight into the index
    instead, so page 1000 costs what page 1 costs.

    It is also stable under concurrent writes: new entries arrive constantly, and
    offset paging would shift rows between pages and show duplicates.

    RLS has already confined this to the caller's organization; `_assert_school_scope`
    narrows it to their campus inside that.
    """
    _assert_school_scope(ctx, school_id)

    stmt = select(AuditLog).where(AuditLog.school_id == school_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if before:
        stmt = stmt.where(AuditLog.created_at < before)

    rows = await session.execute(stmt.order_by(AuditLog.created_at.desc()).limit(limit))
    return list(rows.scalars().all())
