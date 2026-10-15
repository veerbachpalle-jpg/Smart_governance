import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox import OutboxEvent, outbox_processor
from app.modules.ai_assist.service.ai_service import AIAssistService

logger = logging.getLogger("app.ai.pipeline")


async def handle_complaint_submitted(event: OutboxEvent, session: AsyncSession) -> None:
    """Outbox event handler invoked when a citizen submits a new complaint."""
    try:
        complaint_id_raw = event.payload.get("complaint_id") or str(event.aggregate_id)
        complaint_id = uuid.UUID(str(complaint_id_raw))
        logger.info("Triggering AI assist triage for complaint %s", complaint_id)

        ai_service = AIAssistService(session)
        await ai_service.execute_triage_pipeline(complaint_id)
    except Exception as exc:
        logger.error(
            "Error executing AI assist triage for event %s: %s",
            event.id,
            str(exc),
            exc_info=True,
        )
        raise


def setup_ai_assist_handlers() -> None:
    """Registers domain event consumers for AI assist."""
    outbox_processor.register_handler("ComplaintSubmitted", handle_complaint_submitted)
    logger.info("Registered AI assist outbox handler for ComplaintSubmitted")
