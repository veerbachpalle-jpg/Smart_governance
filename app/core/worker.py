import logging
from typing import Any

from arq.connections import RedisSettings
from arq.cron import cron

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


async def expire_review_windows_task(ctx: dict[str, Any]) -> int:
    """Close eligible cases after an uncontested citizen review window expires."""
    from app.modules.challenges.service.challenge_service import ChallengeService

    async with async_session_factory() as session:
        try:
            closed = await ChallengeService(session).process_expired_review_windows()
            await session.commit()
            return len(closed)
        except Exception:
            await session.rollback()
            logger.exception("Review-window expiry job failed")
            raise


async def escalate_challenge_slas_task(ctx: dict[str, Any]) -> int:
    """Escalate citizen challenges whose independent-review SLA has expired."""
    from app.modules.challenges.service.challenge_service import ChallengeService

    async with async_session_factory() as session:
        try:
            escalated = await ChallengeService(session).process_challenge_sla_breaches()
            await session.commit()
            return len(escalated)
        except Exception:
            await session.rollback()
            logger.exception("Challenge SLA escalation job failed")
            raise


async def startup(ctx: dict[str, Any]) -> None:
    from app.modules.ai_assist.service.pipeline import setup_ai_assist_handlers

    logger.info("Initializing ARQ background worker...")
    setup_ai_assist_handlers()


async def shutdown(ctx: dict[str, Any]) -> None:
    logger.info("Shutting down ARQ background worker...")


class WorkerSettings:
    """ARQ worker configuration."""

    cron_jobs = [
        cron(
            poll_outbox_task,
            second={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55},
            run_at_startup=True,
            unique=True,
        ),
        cron(expire_review_windows_task, minute=5, run_at_startup=True, unique=True),
        cron(escalate_challenge_slas_task, minute=10, run_at_startup=True, unique=True),
    ]
    functions = [poll_outbox_task, expire_review_windows_task, escalate_challenge_slas_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
