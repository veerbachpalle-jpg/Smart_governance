import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.modules.identity.models.user import CitizenProfile, User
from app.modules.identity.repository.identity_repository import (
    CitizenProfileRepository,
    UserRepository,
)
from app.modules.identity.schemas.identity import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserRole,
)


class IdentityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repo = UserRepository(session)
        self.profile_repo = CitizenProfileRepository(session)

    async def register_citizen(self, req: RegisterRequest) -> User:
        # Check duplicate email
        existing_email = await self.user_repo.get_by_email(req.email)
        if existing_email:
            raise ConflictError(
                detail="A user with this email address already exists.",
                code="EMAIL_ALREADY_EXISTS",
            )

        # Check duplicate phone
        existing_phone = await self.user_repo.get_by_phone(req.phone_number)
        if existing_phone:
            raise ConflictError(
                detail="A user with this phone number already exists.",
                code="PHONE_ALREADY_EXISTS",
            )

        # Hash password with Argon2
        hashed_pwd = hash_password(req.password)

        # Create Citizen User
        user = User(
            email=req.email.strip().lower(),
            phone_number=req.phone_number.strip(),
            password_hash=hashed_pwd,
            role=UserRole.CITIZEN.value,
            is_active=True,
        )
        created_user = await self.user_repo.create(user)

        # Create Citizen Profile
        profile = CitizenProfile(
            user_id=created_user.id,
            full_name=req.full_name.strip(),
            address=req.address.strip() if req.address else None,
            preferred_language=req.preferred_language.strip(),
            notification_preference=req.notification_preference.strip(),
        )
        await self.profile_repo.create(profile)
        created_user.citizen_profile = profile

        return created_user

    async def login(self, req: LoginRequest) -> TokenResponse:
        user = None
        if req.phone_number:
            raw_phone = req.phone_number.strip().replace(" ", "").replace("-", "")
            user = await self.user_repo.get_by_phone(raw_phone)
            if not user and not raw_phone.startswith("+"):
                # Try with Indian country code +91
                user = await self.user_repo.get_by_phone(f"+91{raw_phone}")
            if not user and raw_phone.startswith("+91"):
                # Try without country code
                user = await self.user_repo.get_by_phone(raw_phone[3:])
        elif req.email:
            user = await self.user_repo.get_by_email(req.email)
        else:
            raise UnauthorizedError(
                detail="Either email or phone number is required.",
                code="INVALID_CREDENTIALS",
            )

        if not user or not verify_password(req.password, user.password_hash):
            raise UnauthorizedError(
                detail="Invalid credentials.",
                code="INVALID_CREDENTIALS",
            )

        if not user.is_active:
            raise ForbiddenError(
                detail="Your account has been deactivated.",
                code="ACCOUNT_INACTIVE",
            )

        access_token = create_access_token(subject=str(user.id), role=user.role)
        refresh_token = create_refresh_token(subject=str(user.id), role=user.role)

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="Bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh(self, req: RefreshRequest) -> TokenResponse:
        payload = decode_token(req.refresh_token)

        if payload.get("type") != "refresh":
            raise UnauthorizedError(
                detail="Provided token is not a refresh token.",
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
                detail="Invalid user ID format in token.",
                code="INVALID_TOKEN_CLAIMS",
            ) from err

        user = await self.user_repo.get_by_id(user_id)
        if not user or not user.is_active:
            raise UnauthorizedError(
                detail="User account no longer active or found.",
                code="USER_NOT_ACTIVE",
            )

        access_token = create_access_token(subject=str(user.id), role=user.role)
        new_refresh_token = create_refresh_token(subject=str(user.id), role=user.role)

        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            token_type="Bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def get_me(self, user_id: uuid.UUID) -> User:
        user = await self.user_repo.get_by_id(user_id)
        if not user:
            raise NotFoundError(
                detail="User profile not found.",
                code="USER_NOT_FOUND",
            )
        return user

    def verify_role_access(self, user: User, allowed_roles: Sequence[str]) -> None:
        """Enforces role check within the service layer."""
        if user.role not in allowed_roles:
            raise ForbiddenError(
                detail=f"Access denied for role '{user.role}'. Required one of: {list(allowed_roles)}.",
                code="INSUFFICIENT_PERMISSIONS",
            )
