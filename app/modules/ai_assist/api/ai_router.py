import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_roles
from app.db.session import get_db
from app.modules.ai_assist.schemas.ai_assist import (
    AcceptInterpretationRequest,
    AIInterpretationResponse,
    OverrideInterpretationRequest,
    RejectInterpretationRequest,
)
from app.modules.ai_assist.service.ai_service import AIAssistService
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

ai_router = APIRouter(prefix="/complaints", tags=["AI Assist"])

OFFICER_ROLES = (
    UserRole.OFFICER,
    UserRole.DEPARTMENT_LEAD,
    UserRole.SUPERVISOR,
    UserRole.ADMIN,
)
READ_ROLES = (
    UserRole.OFFICER,
    UserRole.DEPARTMENT_LEAD,
    UserRole.SUPERVISOR,
    UserRole.ADMIN,
    UserRole.AUDITOR,
)


@ai_router.get(
    "/{complaint_id}/ai-interpretation",
    response_model=AIInterpretationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get latest AI triage recommendation for a complaint",
)
async def get_complaint_ai_interpretation(
    complaint_id: uuid.UUID,
    current_user: User = Depends(require_roles(*READ_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> AIInterpretationResponse:
    service = AIAssistService(session)
    return await service.get_latest_interpretation(complaint_id)


@ai_router.post(
    "/{complaint_id}/ai-interpretation/accept",
    response_model=AIInterpretationResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer accepts AI triage recommendation",
)
async def accept_ai_interpretation(
    complaint_id: uuid.UUID,
    payload: AcceptInterpretationRequest = AcceptInterpretationRequest(),
    current_user: User = Depends(require_roles(*OFFICER_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> AIInterpretationResponse:
    service = AIAssistService(session)
    res = await service.accept_interpretation(complaint_id, current_user, payload)
    await session.commit()
    return res


@ai_router.post(
    "/{complaint_id}/ai-interpretation/override",
    response_model=AIInterpretationResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer overrides AI triage recommendation with mandatory reason",
)
async def override_ai_interpretation(
    complaint_id: uuid.UUID,
    payload: OverrideInterpretationRequest,
    current_user: User = Depends(require_roles(*OFFICER_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> AIInterpretationResponse:
    service = AIAssistService(session)
    res = await service.override_interpretation(complaint_id, current_user, payload)
    await session.commit()
    return res


@ai_router.post(
    "/{complaint_id}/ai-interpretation/reject",
    response_model=AIInterpretationResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer rejects AI triage recommendation with mandatory reason",
)
async def reject_ai_interpretation(
    complaint_id: uuid.UUID,
    payload: RejectInterpretationRequest,
    current_user: User = Depends(require_roles(*OFFICER_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> AIInterpretationResponse:
    service = AIAssistService(session)
    res = await service.reject_interpretation(complaint_id, current_user, payload)
    await session.commit()
    return res
