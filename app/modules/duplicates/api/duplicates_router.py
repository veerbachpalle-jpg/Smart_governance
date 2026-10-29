import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_roles
from app.db.session import get_db
from app.modules.duplicates.schemas.duplicate import (
    DismissDuplicateRequest,
    DuplicateCandidateResponse,
    LinkDuplicateRequest,
    NearbySimilarReport,
    SupportComplaintResponse,
    UpvoteComplaintRequest,
    UpvoteComplaintResponse,
)
from app.modules.duplicates.service.duplicate_service import DuplicateService
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

duplicates_router = APIRouter(tags=["Duplicates"])

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


@duplicates_router.get(
    "/complaints/{complaint_id}/duplicates",
    response_model=list[DuplicateCandidateResponse],
    status_code=status.HTTP_200_OK,
    summary="Get ranked duplicate candidate incidents with spatial, semantic, and temporal breakdown",
)
async def get_duplicate_candidates(
    complaint_id: uuid.UUID,
    radius_meters: float = Query(3000.0, ge=100.0, le=50000.0),
    time_window_days: int = Query(30, ge=1, le=365),
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> list[DuplicateCandidateResponse]:
    service = DuplicateService(session)
    res = await service.search_and_rank_candidates(
        complaint_id=complaint_id,
        radius_meters=radius_meters,
        time_window_days=time_window_days,
    )
    await session.commit()
    return res


@duplicates_router.post(
    "/complaints/{complaint_id}/duplicates/{candidate_id}/link",
    response_model=DuplicateCandidateResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer links candidate as a duplicate incident; recorded with audit trail without auto-merging",
)
async def link_duplicate_candidate(
    complaint_id: uuid.UUID,
    candidate_id: uuid.UUID,
    payload: LinkDuplicateRequest = LinkDuplicateRequest(),
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> DuplicateCandidateResponse:
    service = DuplicateService(session)
    res = await service.link_duplicate(candidate_id, current_user, payload)
    await session.commit()
    return res


@duplicates_router.post(
    "/complaints/{complaint_id}/duplicates/{candidate_id}/dismiss",
    response_model=DuplicateCandidateResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer dismisses duplicate candidate with mandatory justification",
)
async def dismiss_duplicate_candidate(
    complaint_id: uuid.UUID,
    candidate_id: uuid.UUID,
    payload: DismissDuplicateRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> DuplicateCandidateResponse:
    service = DuplicateService(session)
    res = await service.dismiss_duplicate(candidate_id, current_user, payload)
    await session.commit()
    return res


@duplicates_router.get(
    "/complaints/nearby-similar",
    response_model=list[NearbySimilarReport],
    status_code=status.HTTP_200_OK,
    summary="Citizen-facing search returning limited, non-sensitive nearby reports",
)
async def get_nearby_similar_reports(
    latitude: float = Query(..., ge=-90.0, le=90.0),
    longitude: float = Query(..., ge=-180.0, le=180.0),
    radius_meters: float = Query(2000.0, ge=50.0, le=20000.0),
    session: AsyncSession = Depends(get_db),
) -> list[NearbySimilarReport]:
    service = DuplicateService(session)
    return await service.get_nearby_similar_for_citizens(
        latitude=latitude,
        longitude=longitude,
        radius_meters=radius_meters,
    )


@duplicates_router.post(
    "/complaints/{complaint_id}/support",
    response_model=SupportComplaintResponse,
    status_code=status.HTTP_200_OK,
    summary="Citizen clicks 'This is the same issue' to add endorsement to existing complaint",
)
async def support_complaint(
    complaint_id: uuid.UUID,
    current_user: User = Depends(require_roles(UserRole.CITIZEN)),
    session: AsyncSession = Depends(get_db),
) -> SupportComplaintResponse:
    service = DuplicateService(session)
    res = await service.support_complaint(complaint_id, current_user)
    await session.commit()
    return res


@duplicates_router.post(
    "/complaints/{complaint_id}/upvote",
    response_model=UpvoteComplaintResponse,
    status_code=status.HTTP_200_OK,
    summary="Toggle a citizen endorsement for an open complaint in the same ward or within 2 km",
)
async def toggle_complaint_upvote(
    complaint_id: uuid.UUID,
    payload: UpvoteComplaintRequest,
    current_user: User = Depends(require_roles(UserRole.CITIZEN)),
    session: AsyncSession = Depends(get_db),
) -> UpvoteComplaintResponse:
    service = DuplicateService(session)
    result = await service.toggle_upvote(complaint_id, current_user, payload)
    await session.commit()
    return result
