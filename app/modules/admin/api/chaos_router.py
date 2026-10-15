from fastapi import APIRouter, Depends, status

from app.core.chaos import chaos_manager
from app.core.dependencies import require_roles
from app.modules.admin.schemas.chaos import ChaosConfigRequest, ChaosStateResponse
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

chaos_router = APIRouter(prefix="/admin/chaos", tags=["Admin Chaos Simulation"])


@chaos_router.get(
    "",
    response_model=ChaosStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Get active chaos engineering simulation state (used by UI for banner)",
)
async def get_chaos_state(
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> ChaosStateResponse:
    chaos_manager.check_non_production()
    return ChaosStateResponse(**chaos_manager.state.to_dict())


@chaos_router.post(
    "",
    response_model=ChaosStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Configure active chaos simulation parameters (admin-only, non-production only)",
)
async def configure_chaos(
    payload: ChaosConfigRequest,
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> ChaosStateResponse:
    chaos_manager.check_non_production()
    updated_state = chaos_manager.configure(
        disable_ai=payload.disable_ai,
        ai_garbage=payload.ai_garbage,
        delay_worker_ms=payload.delay_worker_ms,
        stop_worker=payload.stop_worker,
        fail_notifications=payload.fail_notifications,
        db_error_operations=payload.db_error_operations,
    )
    return ChaosStateResponse(**updated_state.to_dict())


@chaos_router.post(
    "/reset",
    response_model=ChaosStateResponse,
    status_code=status.HTTP_200_OK,
    summary="Reset all chaos simulations to normal/inactive state",
)
async def reset_chaos(
    current_user: User = Depends(require_roles(UserRole.ADMIN)),
) -> ChaosStateResponse:
    chaos_manager.check_non_production()
    reset_state = chaos_manager.reset()
    return ChaosStateResponse(**reset_state.to_dict())
