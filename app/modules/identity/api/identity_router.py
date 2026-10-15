from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    UserRole,
)
from app.modules.identity.service.identity_service import IdentityService

auth_router = APIRouter(prefix="/auth", tags=["Identity & Auth"])
users_router = APIRouter(prefix="/users", tags=["Users"])


@auth_router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new citizen account",
)
async def register_citizen(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = IdentityService(session)
    user = await service.register_citizen(payload)
    return UserResponse.model_validate(user)


@auth_router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate user and obtain JWT tokens",
)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    service = IdentityService(session)
    return await service.login(payload)


@auth_router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token using refresh token",
)
async def refresh_token(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> TokenResponse:
    service = IdentityService(session)
    return await service.refresh(payload)


@users_router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get current authenticated user profile",
)
async def get_me(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserResponse:
    service = IdentityService(session)
    user = await service.get_me(current_user.id)
    return UserResponse.model_validate(user)


@users_router.get(
    "/officer-area",
    response_model=dict[str, str],
    status_code=status.HTTP_200_OK,
    summary="Protected area restricted to officer and supervisor roles",
)
async def officer_area(
    current_user: User = Depends(
        require_roles(
            UserRole.OFFICER, UserRole.SUPERVISOR, UserRole.ADMIN, UserRole.DEPARTMENT_LEAD
        )
    ),
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    # Invariant: Verify role check also in service layer
    service = IdentityService(session)
    service.verify_role_access(
        current_user,
        [
            UserRole.OFFICER.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
            UserRole.DEPARTMENT_LEAD.value,
        ],
    )
    return {
        "message": f"Welcome to the municipal officer console, {current_user.email}!",
        "role": current_user.role,
    }
