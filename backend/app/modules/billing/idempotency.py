"""Tenant-scoped idempotency for customer-initiated billing mutations."""

from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.modules.billing.models import BillingIdempotencyKey


class BillingIdempotencyService:
    """Serialize equal keys and replay the first completed response."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def begin(
        self,
        *,
        organization_id: UUID,
        operation: str,
        key: str | None,
        request_payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        if key is None:
            return None

        request_hash = _request_hash(request_payload)
        lock_name = f"{organization_id}:{operation}:{key}"
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_name, 0))"),
            {"lock_name": lock_name},
        )
        existing = (
            await self.session.execute(
                select(BillingIdempotencyKey).where(
                    BillingIdempotencyKey.organization_id == organization_id,
                    BillingIdempotencyKey.operation == operation,
                    BillingIdempotencyKey.key == key,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            return None
        if existing.request_hash != request_hash:
            raise ConflictError(
                "This Idempotency-Key was already used with a different request.",
                code="IDEMPOTENCY_KEY_REUSED",
            )
        return existing.response_payload

    async def complete(
        self,
        *,
        organization_id: UUID,
        operation: str,
        key: str | None,
        request_payload: dict[str, Any],
        response_payload: dict[str, Any],
    ) -> None:
        if key is None:
            return
        self.session.add(
            BillingIdempotencyKey(
                organization_id=organization_id,
                operation=operation,
                key=key,
                request_hash=_request_hash(request_payload),
                response_payload=response_payload,
            )
        )


def _request_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()
