import logging
from abc import ABC, abstractmethod
from typing import Any

from app.core.chaos import chaos_manager

logger = logging.getLogger("app.notifications.channels")


class NotificationDeliveryError(Exception):
    """Raised when an outbound notification channel fails delivery."""

    pass


class NotificationChannel(ABC):
    """Abstract interface for pluggable delivery channels (console, email, sms, push)."""

    @abstractmethod
    async def send(
        self,
        recipient: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Dispatches notification to destination recipient."""
        pass


class ConsoleNotificationChannel(NotificationChannel):
    """Default local & test notification channel outputting structured logs."""

    async def send(
        self,
        recipient: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        # Check chaos failure simulation
        if chaos_manager.state.fail_notifications:
            logger.warning(
                "Simulated notification delivery failure to %s: chaos 'fail_notifications' active",
                recipient,
            )
            raise NotificationDeliveryError(
                f"Simulated delivery channel fault when contacting recipient '{recipient}'"
            )

        logger.info(
            "[NOTIFICATION_DISPATCH] [Channel: Console] To: %s | Title: %s | Body: %s | Meta: %s",
            recipient,
            title,
            message,
            metadata or {},
        )
        return True
