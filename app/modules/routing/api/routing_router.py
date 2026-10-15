import uuid

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import require_roles
from app.db.session import get_db
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole
from app.modules.routing.schemas.routing import (
    AcceptRoutingRequest,
    OverrideRoutingRequest,
    RejectRoutingRequest,
    RoutingRecommendationResponse,
    RoutingRuleCreate,
    RoutingRuleResponse,
    RoutingRuleUpdate,
)
from app.modules.routing.service.routing_service import RoutingService

routing_router = APIRouter(tags=["Routing"])

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
# 1. Admin Rule CRUD Endpoints
# ==========================================


@routing_router.post(
    "/routing/rules",
    response_model=RoutingRuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Admin creates a new versioned routing rule",
)
async def create_routing_rule(
    payload: RoutingRuleCreate,
    current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> RoutingRuleResponse:
    service = RoutingService(session)
    res = await service.create_rule(current_user, payload)
    await session.commit()
    return res


@routing_router.get(
    "/routing/rules",
    response_model=list[RoutingRuleResponse],
    status_code=status.HTTP_200_OK,
    summary="List all versioned routing rules with optional category and status filtering",
)
async def list_routing_rules(
    category: str | None = Query(None),
    is_active: bool | None = Query(None),
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> list[RoutingRuleResponse]:
    service = RoutingService(session)
    return await service.list_rules(category=category, is_active=is_active)


@routing_router.put(
    "/routing/rules/{rule_id}",
    response_model=RoutingRuleResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin updates an existing routing rule",
)
async def update_routing_rule(
    rule_id: uuid.UUID,
    payload: RoutingRuleUpdate,
    current_user: User = Depends(require_roles(*ADMIN_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> RoutingRuleResponse:
    service = RoutingService(session)
    res = await service.update_rule(current_user, rule_id, payload)
    await session.commit()
    return res


# ==========================================
# 2. Complaint Routing Recommendation Endpoints
# ==========================================


@routing_router.get(
    "/complaints/{complaint_id}/routing",
    response_model=RoutingRecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get top-3 department routing recommendations for a complaint",
)
async def get_complaint_routing(
    complaint_id: uuid.UUID,
    current_user: User = Depends(require_roles(*STAFF_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> RoutingRecommendationResponse:
    service = RoutingService(session)
    res = await service.get_latest_recommendation(complaint_id)
    await session.commit()
    return res


@routing_router.post(
    "/complaints/{complaint_id}/routing/accept",
    response_model=RoutingRecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer accepts routing recommendation; complaint moves to ROUTED",
)
async def accept_complaint_routing(
    complaint_id: uuid.UUID,
    payload: AcceptRoutingRequest = AcceptRoutingRequest(),
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> RoutingRecommendationResponse:
    service = RoutingService(session)
    res = await service.accept_routing(complaint_id, current_user, payload)
    await session.commit()
    return res


@routing_router.post(
    "/complaints/{complaint_id}/routing/override",
    response_model=RoutingRecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer overrides routing recommendation with mandatory reason; complaint moves to ROUTED",
)
async def override_complaint_routing(
    complaint_id: uuid.UUID,
    payload: OverrideRoutingRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> RoutingRecommendationResponse:
    service = RoutingService(session)
    res = await service.override_routing(complaint_id, current_user, payload)
    await session.commit()
    return res


@routing_router.post(
    "/complaints/{complaint_id}/routing/reject",
    response_model=RoutingRecommendationResponse,
    status_code=status.HTTP_200_OK,
    summary="Officer rejects routing recommendation with mandatory reason",
)
async def reject_complaint_routing(
    complaint_id: uuid.UUID,
    payload: RejectRoutingRequest,
    current_user: User = Depends(require_roles(*DECISION_ROLES)),
    session: AsyncSession = Depends(get_db),
) -> RoutingRecommendationResponse:
    service = RoutingService(session)
    res = await service.reject_routing(complaint_id, current_user, payload)
    await session.commit()
    return res
