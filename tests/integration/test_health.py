from unittest.mock import patch

import pytest
from httpx import AsyncClient

from app.config import settings


@pytest.mark.asyncio
async def test_health_probe(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "grievance-api"
    assert "timestamp" in data
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_readiness_probe(client: AsyncClient) -> None:
    response = await client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"
    assert "X-Request-ID" in response.headers


@pytest.mark.asyncio
async def test_custom_request_id_propagation(client: AsyncClient) -> None:
    custom_id = "req-custom-trace-9999"
    response = await client.get("/health", headers={"X-Request-ID": custom_id})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == custom_id


@pytest.mark.asyncio
async def test_health_security_headers(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert response.headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


@pytest.mark.asyncio
async def test_health_hsts_in_production(client: AsyncClient) -> None:
    with patch.object(settings, "ENVIRONMENT", "production"):
        response = await client.get("/health")
        assert response.status_code == 200
        assert (
            response.headers["Strict-Transport-Security"]
            == "max-age=31536000; includeSubDomains"
        )


@pytest.mark.asyncio
async def test_docs_csp_skipped(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"


