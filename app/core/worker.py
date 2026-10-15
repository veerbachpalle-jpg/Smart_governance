import logging
from typing import Any

from arq.connections import RedisSettings

from app.config import settings
from app.core.outbox import outbox_processor
from app.db.session import async_session_factory

logger = logging.getLogger("app.worker")


async def poll_outbox_task(ctx: dict[str, Any]) -> int:
    """Scheduled task executed by ARQ worker to dispatch pending outbox events."""
    async with async_session_factory() as session:
        try:
            count = await outbox_processor.process_batch(session)
            await session.commit()
            if count > 0:
                logger.info("Outbox worker processed %d events", count)
            return count
        except Exception as exc:
            await session.rollback()
            logger.error("Outbox worker execution failed: %s", str(exc))
            raise


async def startup(ctx: dict[str, Any]) -> None:
    from app.modules.ai_assist.service.pipeline import setup_ai_assist_handlers

    logger.info("Initializing ARQ background worker...")
    setup_ai_assist_handlers()


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("Shutting down ARQ background worker...")


class WorkerSettings:
    """ARQ worker configuration."""

    cron_jobs: list[Any] = []  # Can schedule poll_outbox_task every N seconds
    functions = [poll_outbox_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
