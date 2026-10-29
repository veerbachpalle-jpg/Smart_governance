from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from app.config import settings
from app.core.errors import UnauthorizedError

_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=65536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Hashes a plaintext password using Argon2id."""
    return _hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plaintext password against an Argon2 hash."""
    try:
        return _hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError):
        return False


def _safe_jwt_algorithm() -> str:
    alg = getattr(settings, "JWT_ALGORITHM", "HS256")
    if isinstance(alg, str):
        cleaned = alg.strip().strip("'\"").upper()
        if cleaned in {"HS256", "HS384", "HS512"}:
            return cleaned
    return "HS256"


def create_access_token(subject: str, role: str, extra_claims: dict[str, Any] | None = None) -> str:
    """Generates a short-lived JWT access token."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=_safe_jwt_algorithm())


def create_refresh_token(subject: str, role: str) -> str:
    """Generates a long-lived JWT refresh token."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=_safe_jwt_algorithm())


def decode_token(token: str) -> dict[str, Any]:
    """Decodes and validates a JWT token signature and expiration."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[_safe_jwt_algorithm(), "HS256", "HS384", "HS512"],
        )
        return payload  # type: ignore[no-any-return]
    except jwt.ExpiredSignatureError as err:
        raise UnauthorizedError(detail="Token has expired", code="TOKEN_EXPIRED") from err
    except jwt.InvalidTokenError as err:
        raise UnauthorizedError(
            detail="Invalid token signature or payload", code="INVALID_TOKEN"
        ) from err
