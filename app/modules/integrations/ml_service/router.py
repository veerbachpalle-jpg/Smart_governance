import logging
from typing import Any

from fastapi import APIRouter, Depends, status

from app.core.dependencies import get_current_user
from app.core.errors import BadRequestError
from app.modules.identity.models.user import User
from app.modules.integrations.ml_service.client import ml_client
from app.modules.integrations.ml_service.schemas import (
    MLAnalysis,
    MLAnalyzeDryRunRequest,
    MLComplaintResponse,
    MLHealthResponse,
)

logger = logging.getLogger("app.integrations.ml_service.router")

router = APIRouter(prefix="/integrations/ml-service", tags=["External ML Service"])


@router.get(
    "/health",
    response_model=MLHealthResponse,
    summary="Check External AI Complaint API connectivity and status",
)
async def check_ml_service_health(
    current_user: User = Depends(get_current_user),
) -> MLHealthResponse:
    """Pings the standalone AI Complaint Management service (http://<HOST>:8000/health) and reports status."""
    return await ml_client.check_health()


@router.post(
    "/analyze",
    response_model=MLComplaintResponse,
    summary="Dry-run complaint analysis against external zero-shot BART classifier",
)
async def analyze_dry_run(
    payload: MLAnalyzeDryRunRequest,
    current_user: User = Depends(get_current_user),
) -> MLComplaintResponse:
    """Invokes the external AI service to test classification, priority, duplicates, and summary for any text."""
    res = await ml_client.analyze_complaint(
        citizen_name=payload.citizen_name or current_user.full_name,
        contact=payload.contact or current_user.phone_number or "9999999999",
        location=payload.location or "Municipal Ward Area",
        complaint_text=payload.complaint_text,
        category=payload.category or "General Grievance",
    )
    if not res:
        raise BadRequestError(
            f"External ML service at '{ml_client.base_url}' is unreachable or timed out.",
            code="ML_SERVICE_UNAVAILABLE",
        )
    return res
