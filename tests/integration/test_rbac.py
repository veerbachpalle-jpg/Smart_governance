import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole
from app.modules.identity.service.identity_service import IdentityService


@pytest.mark.asyncio
async def test_citizen_denied_officer_area(client: AsyncClient, citizen_token: str) -> None:
    response = await client.get(
        "/api/v1/users/officer-area",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert response.status_code == 403
    data = response.json()
    assert data["code"] == "FORBIDDEN_ROLE"
    assert data["status"] == 403
    assert "not permitted" in data["detail"].lower()


@pytest.mark.asyncio
async def test_officer_allowed_officer_area(client: AsyncClient, officer_token: str) -> None:
    response = await client.get(
        "/api/v1/users/officer-area",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "officer" in data["message"].lower()
    assert data["role"] == "officer"


@pytest.mark.asyncio
async def test_supervisor_allowed_officer_area(client: AsyncClient, supervisor_token: str) -> None:
    response = await client.get(
        "/api/v1/users/officer-area",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "supervisor"


@pytest.mark.asyncio
async def test_service_layer_role_verification(
    db_session: AsyncSession, citizen_user: User
) -> None:
    service = IdentityService(db_session)
    with pytest.raises(ForbiddenError) as exc_info:
        service.verify_role_access(
            citizen_user,
            [UserRole.OFFICER.value, UserRole.SUPERVISOR.value],
        )
    assert exc_info.value.code == "INSUFFICIENT_PERMISSIONS"
    assert exc_info.value.status == 403
