import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.modules.cases.schemas.case import CaseResponse
from app.modules.challenges.schemas.challenge import (
    ChallengeReviewRequest,
    CitizenChallengeRequest,
    CitizenChallengeResponse,
    ConfirmResolutionRequest,
    ProposeResolutionRequest,
    ResolutionProposalResponse,
)
from app.modules.challenges.service.challenge_service import ChallengeService
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

challenges_router = APIRouter(tags=["Resolutions & Citizen Challenges"])

STAFF_ROLES = (
    UserRole.OFFICER,
    UserRole.DEPARTMENT_LEAD,
    UserRole.SUPERVISOR,
    UserRole.ADMIN,
)
SUPERVISOR_ROLES = (
    UserRole.SUPERVISOR,
    UserRole.ADMIN,
)


# ========================================================
# 1. Staff: Propose Resolution & Review Window
# ========================================================


@challenges_router.post(
    "/cases/{case_id}/resolve",
    response_model=ResolutionProposalResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Officer submits formal resolution proposal with mandatory evidence attachments",
)
async def propose_resolution(
    case_id: uuid.UUID,
    payload: ProposeResolutionRequest,
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> ResolutionProposalResponse:
    service = ChallengeService(session)
    res = await service.propose_resolution(current_user, case_id, payload)
    await session.commit()
    return res


@challenges_router.get(
    "/cases/{case_id}/proposal",
    response_model=ResolutionProposalResponse,
    status_code=status.HTTP_200_OK,
    summary="Get latest resolution proposal and verification evidence for a case",
)
async def get_latest_proposal(
    case_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ResolutionProposalResponse:
    service = ChallengeService(session)
    return await service.get_latest_proposal(current_user, case_id)


# ========================================================
# 2. Citizen: Confirm Resolution or File Dispute
# ========================================================


@challenges_router.post(
    "/cases/{case_id}/confirm",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Citizen confirms resolution satisfaction, permanently closing the case",
)
@challenges_router.post(
    "/complaints/{case_id}/confirm",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Citizen confirms resolution satisfaction by complaint ID, permanently closing the case",
)
async def confirm_resolution(
    case_id: uuid.UUID,
    payload: ConfirmResolutionRequest = ConfirmResolutionRequest(),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> CaseResponse:
    service = ChallengeService(session)
    res = await service.confirm_resolution(current_user, case_id, payload)
    await session.commit()
    return res


@challenges_router.post(
    "/cases/{case_id}/challenge",
    response_model=CitizenChallengeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Citizen files a formal challenge against resolution, rejection, action, or priority",
)
@challenges_router.post(
    "/complaints/{case_id}/challenge",
    response_model=CitizenChallengeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Citizen files a formal challenge by complaint ID, reopening the case",
)
async def file_challenge(
    case_id: uuid.UUID,
    payload: CitizenChallengeRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> CitizenChallengeResponse:
    service = ChallengeService(session)
    res = await service.file_challenge(current_user, case_id, payload)
    await session.commit()
    return res


@challenges_router.get(
    "/cases/{case_id}/challenge",
    response_model=CitizenChallengeResponse,
    status_code=status.HTTP_200_OK,
    summary="Citizen queries the status of the challenge filed for a case",
)
async def get_challenge_status(
    case_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> CitizenChallengeResponse:
    service = ChallengeService(session)
    return await service.get_challenge_status(current_user, case_id)


# ========================================================
# 3. Staff: Challenge Queue & Anti-Self-Review Decisions
# ========================================================


@challenges_router.get(
    "/challenges/queue",
    response_model=list[CitizenChallengeResponse],
    status_code=status.HTTP_200_OK,
    summary="Staff review queue for citizen disputes",
)
async def list_challenge_queue(
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> list[CitizenChallengeResponse]:
    service = ChallengeService(session)
    return await service.list_challenges(current_user, status=status_filter)


@challenges_router.get(
    "/challenges/{challenge_id}",
    response_model=CitizenChallengeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get challenge details by ID",
)
async def get_challenge_by_id(
    challenge_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> CitizenChallengeResponse:
    service = ChallengeService(session)
    return await service.get_challenge_by_id(current_user, challenge_id)


@challenges_router.post(
    "/challenges/{challenge_id}/review",
    response_model=CitizenChallengeResponse,
    status_code=status.HTTP_200_OK,
    summary="Independent supervisor review decision (strictly blocks self-review)",
)
async def review_challenge(
    challenge_id: uuid.UUID,
    payload: ChallengeReviewRequest,
    current_user: User = Depends(require_roles(*SUPERVISOR_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> CitizenChallengeResponse:
    service = ChallengeService(session)
    res = await service.review_challenge(current_user, challenge_id, payload)
    await session.commit()
    return res


# ========================================================
# 4. Worker Jobs: SLA Escalations & Window Expiry
# ========================================================


@challenges_router.post(
    "/challenges/worker/sla-escalations",
    response_model=list[uuid.UUID],
    status_code=status.HTTP_200_OK,
    summary="Worker job trigger: Escalate overdue challenges to supervisor queue",
)
async def trigger_sla_escalations(
    current_user: User = Depends(require_roles(*SUPERVISOR_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> list[uuid.UUID]:
    service = ChallengeService(session)
    escalated = await service.process_challenge_sla_breaches()
    await session.commit()
    return escalated


@challenges_router.post(
    "/cases/worker/expire-review-windows",
    response_model=list[uuid.UUID],
    status_code=status.HTTP_200_OK,
    summary="Worker job trigger: Auto-close cases where review window expired with no challenge",
)
async def trigger_review_window_expiry(
    current_user: User = Depends(require_roles(*SUPERVISOR_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> list[uuid.UUID]:
    service = ChallengeService(session)
    closed = await service.process_expired_review_windows()
    await session.commit()
    return closed
