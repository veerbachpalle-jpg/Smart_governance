import pytest
from httpx import AsyncClient

from app.modules.identity.models.user import User


@pytest.mark.asyncio
async def test_register_citizen_success(client: AsyncClient) -> None:
    payload = {
        "email": "new.citizen@example.com",
        "phone_number": "+1234567890",
        "password": "StrongPassword123!",
        "full_name": "Bob Smith",
        "address": "123 Elm St, Ward 4",
        "preferred_language": "en",
        "notification_preference": "email",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new.citizen@example.com"
    assert data["role"] == "citizen"
    assert data["is_active"] is True
    assert data["citizen_profile"]["full_name"] == "Bob Smith"
    assert data["citizen_profile"]["address"] == "123 Elm St, Ward 4"


@pytest.mark.asyncio
async def test_register_duplicate_email_conflict(client: AsyncClient, citizen_user: User) -> None:
    payload = {
        "email": citizen_user.email,
        "phone_number": "+1999999999",
        "password": "AnotherPassword123!",
        "full_name": "Duplicate Tester",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    data = response.json()
    assert data["code"] == "EMAIL_ALREADY_EXISTS"
    assert data["status"] == 409
    assert "email" in data["detail"].lower()
    assert "instance" in data


@pytest.mark.asyncio
async def test_register_duplicate_phone_conflict(client: AsyncClient, citizen_user: User) -> None:
    payload = {
        "email": "unique.email@example.com",
        "phone_number": citizen_user.phone_number,
        "password": "AnotherPassword123!",
        "full_name": "Duplicate Phone Tester",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    data = response.json()
    assert data["code"] == "PHONE_ALREADY_EXISTS"
    assert data["status"] == 409


@pytest.mark.asyncio
async def test_register_validation_error(client: AsyncClient) -> None:
    # Invalid email and short password
    payload = {
        "email": "not-an-email",
        "phone_number": "123",
        "password": "short",
        "full_name": "",
    }
    response = await client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    data = response.json()
    assert data["code"] == "VALIDATION_ERROR"
    assert data["status"] == 422
    assert len(data["errors"]) > 0


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, citizen_user: User) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": citizen_user.email, "password": "Password123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "Bearer"
    assert data["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient, citizen_user: User) -> None:
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": citizen_user.email, "password": "IncorrectPassword!"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "INVALID_CREDENTIALS"
    assert data["status"] == 401


@pytest.mark.asyncio
async def test_refresh_token_flow(client: AsyncClient, citizen_user: User) -> None:
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": citizen_user.email, "password": "Password123!"},
    )
    refresh_token = login_res.json()["refresh_token"]

    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid.jwt.token"},
    )
    assert response.status_code == 401
    data = response.json()
    assert data["code"] in {"INVALID_TOKEN", "UNAUTHORIZED"}


@pytest.mark.asyncio
async def test_get_me_authenticated(
    client: AsyncClient, citizen_token: str, citizen_user: User
) -> None:
    response = await client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == citizen_user.email
    assert data["role"] == "citizen"
    assert data["citizen_profile"]["full_name"] == "Alice Citizen"


@pytest.mark.asyncio
async def test_get_me_unauthorized(client: AsyncClient) -> None:
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401
    data = response.json()
    assert data["code"] == "AUTHENTICATION_REQUIRED"
    assert data["status"] == 401
