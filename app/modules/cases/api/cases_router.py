import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_roles
from app.core.pagination import PaginatedResponse
from app.db.session import get_db
from app.modules.cases.schemas.case import (
    AddDepartmentRequest,
    AssignOfficerRequest,
    CaseFilterParams,
    CaseResponse,
    CreateCaseRequest,
    LinkComplaintRequest,
    ReassignCaseRequest,
    SetLeadDepartmentRequest,
    TransitionCaseRequest,
)
from app.modules.cases.service.case_service import CaseService
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

cases_router = APIRouter(prefix="/cases", tags=["Cases"])

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
SUPERVISOR_ROLES = (
    UserRole.SUPERVISOR,
    UserRole.ADMIN,
)


@cases_router.get(
    "",
    response_model=PaginatedResponse[CaseResponse],
    status_code=status.HTTP_200_OK,
    summary="List cases ordered by dynamic severity, endorsement, and SLA priority",
)
async def list_cases(
    case_status: str | None = Query(None, alias="status"),
    ward_id: uuid.UUID | None = Query(None),
    ward_number: int | None = Query(None, ge=1),
    department_id: uuid.UUID | None = Query(None),
    department_name: str | None = Query(None),
    sort: Literal["priority_score", "upvotes", "recent"] = Query("priority_score"),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CaseResponse]:
    del current_user
    service = CaseService(session)
    return await service.list_cases(
        CaseFilterParams(
            status=case_status,
            ward_id=ward_id,
            ward_number=ward_number,
            department_id=department_id,
            department_name=department_name,
            sort=sort,
            limit=limit,
            cursor=cursor,
        )
    )


@cases_router.post(
    "",
    response_model=CaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new case grouping one or more complaints",
)
async def create_case(
    payload: CreateCaseRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> CaseResponse:
    service = CaseService(session)
    res = await service.create_case_from_complaint(current_user, payload)
    await session.commit()
    return res


@cases_router.get(
    "/{case_id}",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Get case dossier with departments and linked complaints",
)
async def get_case(
    case_id: uuid.UUID,
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> CaseResponse:
    service = CaseService(session)
    return await service.get_case(current_user, case_id)


@cases_router.post(
    "/{case_id}/complaints",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Link an additional complaint to this case",
)
async def link_complaint(
    case_id: uuid.UUID,
    payload: LinkComplaintRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> CaseResponse:
    service = CaseService(session)
    res = await service.link_complaint(current_user, case_id, payload)
    await session.commit()
    return res


@cases_router.post(
    "/{case_id}/departments",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Add a department to this case",
)
async def add_department(
    case_id: uuid.UUID,
    payload: AddDepartmentRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> CaseResponse:
    service = CaseService(session)
    res = await service.add_department(current_user, case_id, payload)
    await session.commit()
    return res


@cases_router.put(
    "/{case_id}/lead",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Set the single accountable lead department for the case",
)
async def set_lead_department(
    case_id: uuid.UUID,
    payload: SetLeadDepartmentRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> CaseResponse:
    service = CaseService(session)
    res = await service.set_lead_department(current_user, case_id, payload)
    await session.commit()
    return res


@cases_router.post(
    "/{case_id}/transition",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Transition case status through central state machine",
)
async def transition_case(
    case_id: uuid.UUID,
    payload: TransitionCaseRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> CaseResponse:
    service = CaseService(session)
    res = await service.transition_case(current_user, case_id, payload)
    await session.commit()
    return res


@cases_router.post(
    "/{case_id}/assign",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Assign an officer to the case; advances ACCEPTED_BY_LEAD to IN_PROGRESS",
)
async def assign_officer(
    case_id: uuid.UUID,
    payload: AssignOfficerRequest,
    current_user: User = Depends(
        require_roles(UserRole.DEPARTMENT_LEAD, UserRole.SUPERVISOR, UserRole.ADMIN)
    ),
    session: AsyncSession = Depends(get_db),
) -> CaseResponse:
    service = CaseService(session)
    res = await service.assign_officer(current_user, case_id, payload)
    await session.commit()
    return res


@cases_router.post(
    "/{case_id}/reassign",
    response_model=CaseResponse,
    status_code=status.HTTP_200_OK,
    summary="Request case reassignment with mandatory justification",
)
async def request_reassignment(
    case_id: uuid.UUID,
    payload: ReassignCaseRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> CaseResponse:
    service = CaseService(session)
    res = await service.request_reassign(current_user, case_id, payload)
    await session.commit()
    return res
