import uuid
from collections.abc import Callable
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.session import get_db
from app.modules.identity.models.user import User
from app.modules.identity.repository.identity_repository import UserRepository
from app.modules.identity.schemas.identity import UserRole

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    auth: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Extracts, validates, and loads the authenticated user from the Bearer JWT token."""
    if not auth or not auth.credentials:
        raise UnauthorizedError(
            detail="Missing or invalid Bearer authentication token.",
            code="AUTHENTICATION_REQUIRED",
        )

    payload = decode_token(auth.credentials)
    if payload.get("type") != "access":
        raise UnauthorizedError(
            detail="Provided token is not a valid access token.",
            code="INVALID_TOKEN_TYPE",
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise UnauthorizedError(
            detail="Token subject claim is missing.",
            code="INVALID_TOKEN_CLAIMS",
        )

    try:
        user_id = uuid.UUID(user_id_str)
    except ValueError as err:
        raise UnauthorizedError(
            detail="Malformed user ID claim in token.",
            code="INVALID_TOKEN_CLAIMS",
        ) from err

    user_repo = UserRepository(session)
    user = await user_repo.get_by_id(user_id)
    if not user:
        raise UnauthorizedError(
            detail="User associated with token does not exist.",
            code="USER_NOT_FOUND",
        )

    if not user.is_active:
        raise ForbiddenError(
            detail="User account is deactivated.",
            code="ACCOUNT_INACTIVE",
        )

    return user


def require_roles(*allowed_roles: str | UserRole) -> Callable[..., Any]:
    """Dependency factory enforcing Role-Based Access Control (RBAC)."""
    normalized_roles: list[str] = [
        role.value if isinstance(role, UserRole) else str(role) for role in allowed_roles
    ]

    async def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in normalized_roles:
            raise ForbiddenError(
                detail=f"Operation not permitted. Required roles: {normalized_roles}. Current role: '{current_user.role}'.",
                code="FORBIDDEN_ROLE",
            )
        return current_user

    return role_checker
