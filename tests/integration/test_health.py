import pytest
from httpx import AsyncClient


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
