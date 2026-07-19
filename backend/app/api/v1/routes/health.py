"""Health and readiness endpoints.

WHY THIS FILE EXISTS
    Load balancers, Kubernetes probes and uptime monitors need a cheap, unauthenticated
    endpoint to decide whether this instance should receive traffic.

RESPONSIBILITY
    Report process liveness and dependency readiness. Nothing else.

INTERACTIONS
    Mounted OUTSIDE the versioned API prefix (`/health`, not `/api/v1/health`)
    because infrastructure concerns should not be versioned alongside business
    endpoints -- an orchestrator's probe URL must never break when the API moves
    to v2.

LIVENESS vs READINESS -- the distinction matters operationally
    /health  (liveness):  "is this process alive?" Never touches the database.
                          If it fails, the orchestrator RESTARTS the container.
    /health/ready (readiness): "can this process serve traffic?" Checks the DB.
                          If it fails, the orchestrator stops ROUTING to it but
                          does not restart it.
    Conflating them causes a database blip to trigger a restart storm across every
    instance simultaneously -- turning a brief outage into a total one.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from sqlalchemy import text

from app.api.deps import SettingsDep
from app.common.schemas import HealthStatus
from app.core.logging import get_logger
from app.db.session import get_session_factory

logger = get_logger(__name__)

router = APIRouter(tags=["Health"])

APP_VERSION = "0.1.0"


@router.get("/health", response_model=HealthStatus, summary="Liveness probe")
async def health(settings: SettingsDep) -> HealthStatus:
    """Return 200 whenever the process can serve HTTP. No dependency checks."""
    return HealthStatus(
        status="ok",
        environment=settings.ENVIRONMENT.value,
        version=APP_VERSION,
        database="enabled" if settings.DB_ENABLED else "disabled",
    )


@router.get(
    "/health/ready",
    response_model=HealthStatus,
    summary="Readiness probe",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "A dependency is unavailable"}},
)
async def readiness(settings: SettingsDep) -> HealthStatus:
    """Verify downstream dependencies are reachable.

    While DB_ENABLED is false the database is reported as `disabled` and the probe
    still passes -- that is what allows the skeleton to run in CI and locally before
    PostgreSQL is provisioned.
    """
    db_status = "disabled"

    if settings.DB_ENABLED:
        try:
            factory = get_session_factory()
            async with factory() as session:
                # `SELECT 1` is the cheapest possible round trip that proves the
                # connection is genuinely usable, not merely open.
                await session.execute(text("SELECT 1"))
            db_status = "ok"
        except Exception as exc:
            logger.warning("readiness_check_failed", error=str(exc))
            db_status = "unavailable"

    return HealthStatus(
        status="ok" if db_status != "unavailable" else "degraded",
        environment=settings.ENVIRONMENT.value,
        version=APP_VERSION,
        database=db_status,
    )
