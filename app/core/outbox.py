import logging
import traceback
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Uuid, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.base import Base, UUIDMixin

logger = logging.getLogger("app.outbox")

# Handler type for outbox consumers: async function taking (event, session)
EventHandler = Callable[["OutboxEvent", AsyncSession], Awaitable[None]]


class OutboxEvent(Base, UUIDMixin):
    __tablename__ = "outbox_events"

    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), index=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32), default="PENDING", index=True, nullable=False
    )  # PENDING, PUBLISHED, FAILED
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeadLetterEvent(Base, UUIDMixin):
    __tablename__ = "dead_letter_events"

    outbox_event_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("outbox_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB, "postgresql"),  # type: ignore[no-untyped-call]
        nullable=False,
    )
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False)
    stack_trace: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class OutboxProcessor:
    """Registry and executor for transactional outbox dispatch with retries and dead-lettering."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._processed_events: set[uuid.UUID] = (
            set()
        )  # In-memory deduplication set for idempotency

    def register_handler(self, event_type: str, handler: EventHandler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    async def enqueue_event(
        self,
        session: AsyncSession,
        event_type: str,
        aggregate_type: str,
        aggregate_id: uuid.UUID,
        payload: dict[str, Any],
        max_retries: int = 5,
    ) -> OutboxEvent:
        """Enqueues an outbox event in the SAME active database transaction."""
        event = OutboxEvent(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=payload,
            status="PENDING",
            retry_count=0,
            max_retries=max_retries,
            next_retry_at=None,
        )
        session.add(event)
        await session.flush()
        return event

    async def process_batch(self, session: AsyncSession, batch_size: int = 20) -> int:
        """Pulls pending outbox events, processes registered handlers, retries or dead-letters."""
        from app.core.chaos import chaos_manager

        can_proceed = await chaos_manager.handle_worker_chaos()
        if not can_proceed:
            return 0

        now = datetime.now(timezone.utc)
        stmt = (
            select(OutboxEvent)
            .where(
                OutboxEvent.status == "PENDING",
                (OutboxEvent.next_retry_at.is_(None)) | (OutboxEvent.next_retry_at <= now),
            )
            .order_by(OutboxEvent.created_at.asc())
            .limit(batch_size)
        )
        result = await session.execute(stmt)
        events = list(result.scalars().all())

        processed_count = 0
        for event in events:
            # Idempotency check: if already processed, finalize immediately
            if event.id in self._processed_events:
                event.status = "PUBLISHED"
                event.processed_at = now
                processed_count += 1
                continue

            handlers = self._handlers.get(event.event_type, [])
            try:
                for handler in handlers:
                    await handler(event, session)
                event.status = "PUBLISHED"
                event.processed_at = datetime.now(timezone.utc)
                self._processed_events.add(event.id)
                processed_count += 1
            except Exception as exc:
                event.retry_count += 1
                tb = traceback.format_exc()
                logger.warning(
                    "Error dispatching outbox event %s (attempt %d/%d): %s",
                    event.id,
                    event.retry_count,
                    event.max_retries,
                    str(exc),
                )
                if event.retry_count >= event.max_retries:
                    event.status = "FAILED"
                    dead_letter = DeadLetterEvent(
                        outbox_event_id=event.id,
                        event_type=event.event_type,
                        aggregate_type=event.aggregate_type,
                        aggregate_id=event.aggregate_id,
                        payload=event.payload,
                        failure_reason=str(exc),
                        stack_trace=tb,
                    )
                    session.add(dead_letter)
                else:
                    backoff_seconds = 2**event.retry_count
                    event.next_retry_at = datetime.now(timezone.utc) + timedelta(
                        seconds=backoff_seconds
                    )

        await session.flush()
        return processed_count


# Global singleton processor instance
outbox_processor = OutboxProcessor()


async def enqueue_outbox_event(
    session: AsyncSession,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID,
    payload: dict[str, Any],
    max_retries: int = 5,
) -> OutboxEvent:
    return await outbox_processor.enqueue_event(
        session=session,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        payload=payload,
        max_retries=max_retries,
    )
