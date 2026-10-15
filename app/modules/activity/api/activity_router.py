import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.modules.activity.schemas.activity import (
    AddActivityRequest,
    CaseActivityResponse,
    CitizenTimelineItem,
    CitizenUpdateRequest,
)
from app.modules.activity.service.activity_service import ActivityService
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

activity_router = APIRouter(prefix="/cases", tags=["Case Activity"])

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


@activity_router.post(
    "/{case_id}/activity",
    response_model=CaseActivityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Append an official activity log entry to the case",
)
async def add_activity(
    case_id: uuid.UUID,
    payload: AddActivityRequest,
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> CaseActivityResponse:
    service = ActivityService(session)
    res = await service.add_activity(current_user, case_id, payload)
    await session.commit()
    return res


@activity_router.get(
    "/{case_id}/activities",
    response_model=list[CaseActivityResponse],
    status_code=status.HTTP_200_OK,
    summary="Get official activity history for staff (includes internal and citizen-visible entries)",
)
async def list_case_activities(
    case_id: uuid.UUID,
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> list[CaseActivityResponse]:
    service = ActivityService(session)
    return await service.list_activities_for_staff(current_user, case_id)


@activity_router.post(
    "/{case_id}/citizen-updates",
    response_model=CaseActivityResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Publish an official citizen-visible update message for public tracking",
)
async def publish_citizen_update(
    case_id: uuid.UUID,
    payload: CitizenUpdateRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> CaseActivityResponse:
    service = ActivityService(session)
    res = await service.publish_citizen_update(current_user, case_id, payload)
    await session.commit()
    return res


@activity_router.get(
    "/citizen-timeline/{complaint_id}",
    response_model=list[CitizenTimelineItem],
    status_code=status.HTTP_200_OK,
    summary="Citizen timeline showing ONLY CITIZEN_VISIBLE entries for their grievance",
)
async def get_citizen_timeline(
    complaint_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[CitizenTimelineItem]:
    service = ActivityService(session)
    return await service.get_citizen_timeline(current_user, complaint_id)
