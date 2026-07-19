"""Smoke tests for the application skeleton.

These verify the wiring itself -- app factory, middleware chain, exception
handlers, routing -- independently of any business module. If these fail, nothing
else in the suite can be trusted.
"""

from __future__ import annotations

from httpx import AsyncClient


async def test_liveness_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    assert body["database"] == "disabled"


async def test_readiness_passes_when_database_is_disabled(client: AsyncClient) -> None:
    """The skeleton must be deployable before PostgreSQL exists."""
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["database"] == "disabled"


async def test_request_id_header_is_returned(client: AsyncClient) -> None:
    """Every response must carry a correlation id for log lookup."""
    response = await client.get("/health")

    assert "X-Request-ID" in response.headers
    assert response.headers["X-Request-ID"]


async def test_inbound_request_id_is_propagated(client: AsyncClient) -> None:
    """A gateway-assigned id must survive, so traces span services."""
    response = await client.get("/health", headers={"X-Request-ID": "trace-abc-123"})

    assert response.headers["X-Request-ID"] == "trace-abc-123"


async def test_server_timing_header_is_present(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.headers["Server-Timing"].startswith("app;dur=")


async def test_unknown_route_returns_problem_details(client: AsyncClient) -> None:
    """404s must use the same RFC 9457 shape as every other error."""
    response = await client.get("/api/v1/does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["code"] == "HTTP_404"
    assert body["status"] == 404
    # The request id is echoed in the body so a user can quote it in a ticket.
    assert body["instance"]


async def test_openapi_schema_is_generated(client: AsyncClient) -> None:
    """A broken route signature usually surfaces first as an OpenAPI failure."""
    response = await client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    assert schema["info"]["title"]
    assert "/health" in schema["paths"]
