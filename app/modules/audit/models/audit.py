import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, String, Uuid, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, UUIDMixin

GENESIS_HASH = "0" * 64


def compute_audit_hash(
    sequence_number: int,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    old_state: Any,
    new_state: Any,
    occurred_at: datetime,
    previous_hash: str,
) -> str:
    """Computes deterministic SHA-256 hash for a tamper-evident audit chain node."""
    if occurred_at.tzinfo is None:
        norm_occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    else:
        norm_occurred_at = occurred_at.astimezone(timezone.utc)

    payload: dict[str, Any] = {
        "sequence_number": sequence_number,
        "entity_type": entity_type,
        "entity_id": str(entity_id),
        "action": action,
        "actor_id": str(actor_id) if actor_id else None,
        "actor_role": actor_role,
        "old_state": old_state,
        "new_state": new_state,
        "occurred_at": norm_occurred_at.isoformat(),
        "previous_hash": previous_hash,
    }
    canonical_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


class AuditEvent(Base, UUIDMixin):
    __tablename__ = "audit_events"

    sequence_number: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"),  # type: ignore[no-untyped-call]
        unique=True,
        index=True,
        nullable=False,
    )
    entity_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), index=True, nullable=True
    )
    actor_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    old_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=True,
    )
    new_state: Mapped[dict[str, Any] | None] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=True,
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_hash: Mapped[str] = mapped_column(String(64), nullable=False)


# Enforce append-only immutability at the ORM / session level
@event.listens_for(AuditEvent, "before_update")
def block_audit_update(mapper: Any, connection: Any, target: Any) -> None:
    raise RuntimeError("audit_events is append-only: UPDATE operations are strictly prohibited.")


@event.listens_for(AuditEvent, "before_delete")
def block_audit_delete(mapper: Any, connection: Any, target: Any) -> None:
    raise RuntimeError("audit_events is append-only: DELETE operations are strictly prohibited.")
