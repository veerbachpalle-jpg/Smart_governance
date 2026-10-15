import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.core.errors import AppException, ForbiddenError

logger = logging.getLogger("app.chaos")


class DBInjectedChaosError(AppException):
    def __init__(self, detail: str = "Simulated database fault injected by chaos engine.") -> None:
        super().__init__(
            title="Database Error Injected",
            status=500,
            detail=detail,
            code="CHAOS_DB_ERROR_INJECTED",
        )


@dataclass
class ChaosSimulationState:
    disable_ai: bool = False
    ai_garbage: bool = False
    delay_worker_ms: int = 0
    stop_worker: bool = False
    fail_notifications: bool = False
    db_error_operations: list[str] = field(default_factory=list)

    @property
    def is_active(self) -> bool:
        return (
            self.disable_ai
            or self.ai_garbage
            or self.delay_worker_ms > 0
            or self.stop_worker
            or self.fail_notifications
            or len(self.db_error_operations) > 0
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_active": self.is_active,
            "disable_ai": self.disable_ai,
            "ai_garbage": self.ai_garbage,
            "delay_worker_ms": self.delay_worker_ms,
            "stop_worker": self.stop_worker,
            "fail_notifications": self.fail_notifications,
            "db_error_operations": list(self.db_error_operations),
        }


class ChaosManager:
    """Singleton managing active chaos simulation configurations for resilience testing."""

    def __init__(self) -> None:
        self.state = ChaosSimulationState()

    def check_non_production(self) -> None:
        if settings.ENVIRONMENT.lower() in {"production", "prod"}:
            raise ForbiddenError(
                "Chaos engineering simulation endpoints are strictly forbidden in production.",
                code="CHAOS_FORBIDDEN_IN_PRODUCTION",
            )

    def configure(
        self,
        disable_ai: bool | None = None,
        ai_garbage: bool | None = None,
        delay_worker_ms: int | None = None,
        stop_worker: bool | None = None,
        fail_notifications: bool | None = None,
        db_error_operations: list[str] | None = None,
    ) -> ChaosSimulationState:
        self.check_non_production()
        if disable_ai is not None:
            self.state.disable_ai = disable_ai
        if ai_garbage is not None:
            self.state.ai_garbage = ai_garbage
        if delay_worker_ms is not None:
            self.state.delay_worker_ms = max(0, delay_worker_ms)
        if stop_worker is not None:
            self.state.stop_worker = stop_worker
        if fail_notifications is not None:
            self.state.fail_notifications = fail_notifications
        if db_error_operations is not None:
            self.state.db_error_operations = db_error_operations

        logger.warning("Chaos configuration modified: %s", self.state.to_dict())
        return self.state

    def reset(self) -> ChaosSimulationState:
        self.check_non_production()
        self.state = ChaosSimulationState()
        logger.info("Chaos simulation state reset to all default (inactive) values.")
        return self.state

    def check_db_error(self, operation_name: str) -> None:
        if operation_name in self.state.db_error_operations:
            logger.warning("Injecting simulated database fault for operation '%s'", operation_name)
            raise DBInjectedChaosError(
                f"Simulated database fault injected for operation: '{operation_name}'"
            )

    async def handle_worker_chaos(self) -> bool:
        """Returns False if worker is stopped, sleeps if delay is requested."""
        if self.state.stop_worker:
            logger.debug("Worker execution skipped: stop_worker chaos flag is active.")
            return False
        if self.state.delay_worker_ms > 0:
            logger.debug(
                "Delaying worker execution by %d ms due to active chaos simulation",
                self.state.delay_worker_ms,
            )
            await asyncio.sleep(self.state.delay_worker_ms / 1000.0)
        return True


# Global singleton chaos manager
chaos_manager = ChaosManager()
