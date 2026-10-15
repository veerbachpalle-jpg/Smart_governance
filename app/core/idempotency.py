import hashlib
from datetime import datetime, timezone
from typing import Any

from fastapi import Header, Request
from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.errors import BadRequestError, ConflictError
from app.db.base import Base, UUIDMixin


class IdempotencyRecord(Base, UUIDMixin):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    request_path: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class IdempotencyManager:
    @staticmethod
    def compute_payload_hash(raw_body: bytes) -> str:
        return hashlib.sha256(raw_body).hexdigest()

    @staticmethod
    async def get_or_validate(
        session: AsyncSession,
        key: str,
        request_path: str,
        raw_body: bytes,
    ) -> IdempotencyRecord | None:
        """Checks for existing key. Returns cached record on match, or raises 409 on payload divergence."""
        payload_hash = IdempotencyManager.compute_payload_hash(raw_body)
        stmt = select(IdempotencyRecord).where(IdempotencyRecord.key == key)
        result = await session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is not None:
            if record.request_hash == payload_hash:
                return record
            raise ConflictError(
                detail="Idempotency-Key was previously used with a different request payload.",
                code="IDEMPOTENCY_CONFLICT",
            )
        return None

    @staticmethod
    async def record_response(
        session: AsyncSession,
        key: str,
        request_path: str,
        raw_body: bytes,
        status_code: int,
        response_body: dict[str, Any],
    ) -> IdempotencyRecord:
        """Stores the response to allow deterministic replaying on retried requests."""
        payload_hash = IdempotencyManager.compute_payload_hash(raw_body)
        record = IdempotencyRecord(
            key=key,
            request_path=request_path,
            request_hash=payload_hash,
            response_status=status_code,
            response_body=response_body,
        )
        session.add(record)
        await session.flush()
        return record


def extract_idempotency_key(
    request: Request,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> str:
    """Enforces presence and validation of Idempotency-Key HTTP header for mutating operations."""
    if not idempotency_key or not idempotency_key.strip():
        raise BadRequestError(
            detail="The 'Idempotency-Key' request header is required for this operation.",
            code="IDEMPOTENCY_KEY_REQUIRED",
        )
    return idempotency_key.strip()
