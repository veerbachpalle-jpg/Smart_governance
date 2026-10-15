import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_roles
from app.core.pagination import PaginatedResponse
from app.db.session import get_db
from app.modules.audit.schemas.audit import (
    AuditEventResponse,
    AuditFilterParams,
    AuditVerifyResponse,
)
from app.modules.audit.service.audit_service import AuditService
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

audit_router = APIRouter(prefix="/audit", tags=["Audit & Governance"])


@audit_router.get(
    "/events",
    response_model=PaginatedResponse[AuditEventResponse],
    status_code=status.HTTP_200_OK,
    summary="List immutable audit trail events with cursor pagination and filters",
)
async def list_audit_events(
    entity_type: str | None = Query(None),
    entity_id: uuid.UUID | None = Query(None),
    actor_id: uuid.UUID | None = Query(None),
    action: str | None = Query(None),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    current_user: User = Depends(require_roles(UserRole.AUDITOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[AuditEventResponse]:
    params = AuditFilterParams(
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=actor_id,
        action=action,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        cursor=cursor,
    )
    service = AuditService(session)
    return await service.list_events(params)


@audit_router.get(
    "/verify",
    response_model=AuditVerifyResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify cryptographic integrity of the entire audit hash chain",
)
async def verify_audit_chain(
    current_user: User = Depends(require_roles(UserRole.AUDITOR, UserRole.ADMIN)),
    session: AsyncSession = Depends(get_db),
) -> AuditVerifyResponse:
    service = AuditService(session)
    return await service.verify_chain()
