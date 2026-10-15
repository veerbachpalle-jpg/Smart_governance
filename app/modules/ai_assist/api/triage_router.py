import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_roles
from app.db.session import get_db
from app.modules.ai_assist.schemas.manual_triage import (
    ManualTriageQueueItemResponse,
    ManualTriageRequest,
    ManualTriageResultResponse,
)
from app.modules.ai_assist.service.manual_triage_service import ManualTriageService
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

triage_router = APIRouter(tags=["Manual Triage"])

OFFICER_ROLES = (
    UserRole.OFFICER,
    UserRole.DEPARTMENT_LEAD,
    UserRole.SUPERVISOR,
    UserRole.ADMIN,
)


@triage_router.get(
    "/triage/manual/queue",
    response_model=list[ManualTriageQueueItemResponse],
    status_code=status.HTTP_200_OK,
    summary="List complaints in the MANUAL_TRIAGE queue waiting for officer assessment",
)
@triage_router.get(
    "/complaints/manual-triage/queue",
    response_model=list[ManualTriageQueueItemResponse],
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def get_manual_triage_queue(
    current_user: User = Depends(require_roles(*OFFICER_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> list[ManualTriageQueueItemResponse]:
    service = ManualTriageService(session)
    return await service.get_manual_triage_queue()


@triage_router.post(
    "/triage/manual/{complaint_id}",
    response_model=ManualTriageResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer manually assigns category, routing, and priority (no AI required)",
)
@triage_router.post(
    "/complaints/{complaint_id}/manual-triage",
    response_model=ManualTriageResultResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
async def submit_manual_triage(
    complaint_id: uuid.UUID,
    payload: ManualTriageRequest,
    current_user: User = Depends(require_roles(*OFFICER_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> ManualTriageResultResponse:
    service = ManualTriageService(session)
    res = await service.process_manual_triage(current_user, complaint_id, payload)
    await session.commit()
    return res
