import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import PaginatedResponse
from app.modules.audit.models.audit import GENESIS_HASH, AuditEvent, compute_audit_hash
from app.modules.audit.repository.audit_repository import AuditRepository
from app.modules.audit.schemas.audit import (
    AuditEventResponse,
    AuditFilterParams,
    AuditVerifyResponse,
)


class AuditService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AuditRepository(session)

    async def record_event(
        self,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        actor_id: uuid.UUID | None = None,
        actor_role: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        old_state: dict[str, Any] | None = None,
        new_state: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditEvent:
        """Appends a new immutable audit node linking to the cryptographic hash of the prior node."""
        if occurred_at is None:
            occurred_at = datetime.now(timezone.utc)

        latest = await self.repo.get_latest_event()
        if latest is None:
            sequence_number = 1
            previous_hash = GENESIS_HASH
        else:
            sequence_number = latest.sequence_number + 1
            previous_hash = latest.current_hash

        current_hash = compute_audit_hash(
            sequence_number=sequence_number,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_id=actor_id,
            actor_role=actor_role,
            old_state=old_state,
            new_state=new_state,
            occurred_at=occurred_at,
            previous_hash=previous_hash,
        )

        event = AuditEvent(
            sequence_number=sequence_number,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor_id=actor_id,
            actor_role=actor_role,
            ip_address=ip_address,
            user_agent=user_agent,
            old_state=old_state,
            new_state=new_state,
            occurred_at=occurred_at,
            previous_hash=previous_hash,
            current_hash=current_hash,
        )
        return await self.repo.insert_event(event)

    async def list_events(self, params: AuditFilterParams) -> PaginatedResponse[AuditEventResponse]:
        items, next_cursor, has_more, total_count = await self.repo.list_events(params)
        return PaginatedResponse[AuditEventResponse](
            items=[AuditEventResponse.model_validate(e) for e in items],
            next_cursor=next_cursor,
            has_more=has_more,
            total_count=total_count,
        )

    async def verify_chain(self) -> AuditVerifyResponse:
        """Walks the full audit event sequence and verifies cryptographic integrity of every link."""
        events = await self.repo.get_all_ordered()
        if not events:
            return AuditVerifyResponse(
                is_valid=True,
                total_events=0,
                message="Audit chain is empty. Verification passed.",
            )

        expected_prev = GENESIS_HASH
        for event in events:
            # 1. Verify link to previous node
            if event.previous_hash != expected_prev:
                return AuditVerifyResponse(
                    is_valid=False,
                    total_events=len(events),
                    broken_at_sequence=event.sequence_number,
                    event_id=str(event.id),
                    message=f"Hash chain broken at sequence {event.sequence_number}: previous_hash does not match.",
                    expected_hash=expected_prev,
                    actual_hash=event.previous_hash,
                )

            # 2. Recompute node hash to detect any in-place tampering
            computed_current = compute_audit_hash(
                sequence_number=event.sequence_number,
                entity_type=event.entity_type,
                entity_id=event.entity_id,
                action=event.action,
                actor_id=event.actor_id,
                actor_role=event.actor_role,
                old_state=event.old_state,
                new_state=event.new_state,
                occurred_at=event.occurred_at,
                previous_hash=event.previous_hash,
            )
            if event.current_hash != computed_current:
                return AuditVerifyResponse(
                    is_valid=False,
                    total_events=len(events),
                    broken_at_sequence=event.sequence_number,
                    event_id=str(event.id),
                    message=f"Node integrity violated at sequence {event.sequence_number}: payload hash mismatch.",
                    expected_hash=computed_current,
                    actual_hash=event.current_hash,
                )

            expected_prev = event.current_hash

        return AuditVerifyResponse(
            is_valid=True,
            total_events=len(events),
            message=f"All {len(events)} audit events verified intact with cryptographic hash continuity.",
        )
