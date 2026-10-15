import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_roles
from app.db.session import get_db
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole
from app.modules.priority.schemas.priority import (
    AcceptPriorityRequest,
    OverridePriorityRequest,
    PriorityAssessmentResponse,
    PriorityPolicyCreate,
    PriorityPolicyResponse,
    PriorityQueueItem,
    RejectPriorityRequest,
)
from app.modules.priority.service.priority_service import PriorityService

priority_router = APIRouter(tags=["Priority"])

ADMIN_ROLES = (UserRole.ADMIN,)
STAFF_ROLES = (
    UserRole.OFFICER,
    UserRole.DEPARTMENT_LEAD,
    UserRole.SUPERVISOR,
    UserRole.ADMIN,
    UserRole.AUDITOR,
)
DECISION_ROLES = (
    UserRole.OFFICER,
    UserRole.DEPARTMENT_LEAD,
    UserRole.SUPERVISOR,
    UserRole.ADMIN,
)


# ==========================================
# 1. Admin Policy CRUD Endpoints
# ==========================================


@priority_router.post(
    "/priority/policies",
    response_model=PriorityPolicyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin creates a multilingual safety priority policy",
)
async def create_priority_policy(
    payload: PriorityPolicyCreate,
    current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PriorityPolicyResponse:
    service = PriorityService(session)
    res = await service.create_policy(payload)
    await session.commit()
    return res


@priority_router.get(
    "/priority/policies",
    response_model=list[PriorityPolicyResponse],
    status_code=status.HTTP_200_OK,
    summary="List all priority policies",
)
async def list_priority_policies(
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> list[PriorityPolicyResponse]:
    service = PriorityService(session)
    return await service.list_policies()


# ==========================================
# 2. Priority Assessment & Decision Endpoints
# ==========================================


@priority_router.get(
    "/complaints/{complaint_id}/priority",
    response_model=PriorityAssessmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Get or generate priority assessment for a complaint",
)
async def get_complaint_priority(
    complaint_id: uuid.UUID,
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PriorityAssessmentResponse:
    service = PriorityService(session)
    res = await service.get_latest_assessment(complaint_id)
    await session.commit()
    return res


@priority_router.post(
    "/complaints/{complaint_id}/priority/accept",
    response_model=PriorityAssessmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer accepts suggested priority recommendation",
)
async def accept_complaint_priority(
    complaint_id: uuid.UUID,
    payload: AcceptPriorityRequest = AcceptPriorityRequest(),
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PriorityAssessmentResponse:
    service = PriorityService(session)
    res = await service.accept_priority(complaint_id, current_user, payload)
    await session.commit()
    return res


@priority_router.post(
    "/complaints/{complaint_id}/priority/override",
    response_model=PriorityAssessmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer overrides priority with mandatory justification",
)
async def override_complaint_priority(
    complaint_id: uuid.UUID,
    payload: OverridePriorityRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PriorityAssessmentResponse:
    service = PriorityService(session)
    res = await service.override_priority(complaint_id, current_user, payload)
    await session.commit()
    return res


@priority_router.post(
    "/complaints/{complaint_id}/priority/reject",
    response_model=PriorityAssessmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer rejects priority recommendation with mandatory justification",
)
async def reject_complaint_priority(
    complaint_id: uuid.UUID,
    payload: RejectPriorityRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PriorityAssessmentResponse:
    service = PriorityService(session)
    res = await service.reject_priority(complaint_id, current_user, payload)
    await session.commit()
    return res


# ==========================================
# 3. Safety-Critical Priority Queue
# ==========================================


@priority_router.get(
    "/priority/queue",
    response_model=list[PriorityQueueItem],
    status_code=status.HTTP_200_OK,
    summary="Safety-critical grievance queue flagged for expedited triage",
)
async def get_critical_priority_queue(
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> list[PriorityQueueItem]:
    service = PriorityService(session)
    return await service.list_critical_queue()
