import pytest

from app.core.errors import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_argon2_hashing_and_verification() -> None:
    password = "SuperSecurePassword123!"
    hashed = hash_password(password)
    assert hashed != password
    assert hashed.startswith("$argon2")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_jwt_access_and_refresh_tokens() -> None:
    subject = "user-1234-uuid"
    role = "citizen"

    access_token = create_access_token(subject=subject, role=role)
    payload = decode_token(access_token)
    assert payload["sub"] == subject
    assert payload["role"] == role
    assert payload["type"] == "access"

    refresh_token = create_refresh_token(subject=subject, role=role)
    r_payload = decode_token(refresh_token)
    assert r_payload["sub"] == subject
    assert r_payload["role"] == role
    assert r_payload["type"] == "refresh"


def test_jwt_tampered_token() -> None:
    token = create_access_token(subject="user-1", role="citizen")
    tampered_token = token[:-4] + "abcd"
    with pytest.raises(UnauthorizedError) as exc_info:
        decode_token(tampered_token)
    assert exc_info.value.code == "INVALID_TOKEN"


def test_jwt_safe_algorithm_fallback() -> None:
    from app.config import settings

    original = settings.JWT_ALGORITHM
    try:
        settings.JWT_ALGORITHM = '"HS256"'
        token = create_access_token(subject="user-safe", role="citizen")
        payload = decode_token(token)
        assert payload["sub"] == "user-safe"

        settings.JWT_ALGORITHM = "unsupported_algo"
        token2 = create_access_token(subject="user-fallback", role="citizen")
        payload2 = decode_token(token2)
        assert payload2["sub"] == "user-fallback"
    finally:
        settings.JWT_ALGORITHM = original

