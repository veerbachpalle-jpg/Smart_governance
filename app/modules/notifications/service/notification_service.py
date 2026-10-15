import logging
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox import DeadLetterEvent
from app.modules.notifications.models.notification import NotificationLog
from app.modules.notifications.service.channels import (
    ConsoleNotificationChannel,
    NotificationChannel,
)

logger = logging.getLogger("app.notifications.service")


class NotificationService:
    """Manages outbound alert dispatch, retries, dead-lettering, and failure decoupling."""

    def __init__(
        self,
        session: AsyncSession,
        channel: Optional[NotificationChannel] = None,
    ) -> None:
        self.session = session
        self.channel = channel or ConsoleNotificationChannel()

    async def send_notification(
        self,
        recipient: str,
        title: str,
        message: str,
        notification_type: str = "CASE_UPDATE",
        metadata: Optional[dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> NotificationLog:
        """Dispatches notification with automatic retries and dead-letter event persistence upon exhaustion."""
        log_entry = NotificationLog(
            id=uuid.uuid4(),
            recipient=recipient,
            channel="console",
            notification_type=notification_type,
            title=title,
            message=message,
            status="PENDING",
            retry_count=0,
            max_retries=max_retries,
            metadata_json=metadata or {},
        )
        self.session.add(log_entry)
        await self.session.flush()

        last_error: Optional[str] = None
        for attempt in range(1, max_retries + 1):
            try:
                await self.channel.send(
                    recipient=recipient,
                    title=title,
                    message=message,
                    metadata=metadata,
                )
                # Success
                now = datetime.now(timezone.utc)
                log_entry.status = "SENT"
                log_entry.sent_at = now
                await self.session.flush()
                return log_entry
            except Exception as exc:
                last_error = str(exc)
                log_entry.retry_count = attempt
                logger.warning(
                    "Notification attempt %d/%d failed for recipient '%s': %s",
                    attempt,
                    max_retries,
                    recipient,
                    last_error,
                )

        # All retries exhausted -> persist to dead_letter_events
        log_entry.status = "DEAD_LETTER"
        log_entry.error_message = last_error

        dead_letter = DeadLetterEvent(
            event_type="notification.dispatch",
            aggregate_type="notification_log",
            aggregate_id=log_entry.id,
            payload={
                "notification_id": str(log_entry.id),
                "recipient": recipient,
                "title": title,
                "notification_type": notification_type,
                "retries": log_entry.retry_count,
            },
            failure_reason=last_error or "Notification max retries exceeded",
            stack_trace=traceback.format_exc(),
        )
        self.session.add(dead_letter)
        await self.session.flush()
        return log_entry

    async def notify_case_event_safely(
        self,
        case_id: uuid.UUID,
        event_type: str,
        recipient: str,
        title: str,
        message: str,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Optional[NotificationLog]:
        """CRITICAL INVARIANT: Case state and main workflow MUST NEVER BE AFFECTED by notification delivery failures."""
        try:
            return await self.send_notification(
                recipient=recipient,
                title=title,
                message=message,
                notification_type=event_type,
                metadata={**(metadata or {}), "case_id": str(case_id)},
            )
        except Exception as exc:
            logger.error(
                "Safe notification wrapper caught unexpected exception for case %s: %s (case workflow unaffected)",
                case_id,
                exc,
            )
            return None
