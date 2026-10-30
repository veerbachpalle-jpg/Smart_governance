import logging
from typing import Any, Optional

import httpx

from app.config import settings
from app.modules.integrations.ml_service.schemas import (
    MLAnalysis,
    MLComplaintRequest,
    MLComplaintResponse,
    MLDeptScore,
    MLHealthResponse,
)

logger = logging.getLogger("app.integrations.ml_service")

# Mapping of external zero-shot department names to internal Department codes
EXTERNAL_DEPT_TO_CODE: dict[str, str] = {
    "roads": "ROADS",
    "water": "WATER",
    "electricity": "ELEC",
    "sanitation": "SAN",
    "drainage": "DRAIN",
    "parks": "PARKS",
}


def normalize_string_length(val: Optional[str], default: str, min_len: int, max_len: int) -> str:
    cleaned = (val or default).strip()
    if len(cleaned) < min_len:
        # Pad string to meet minimum length requirement
        cleaned = f"{cleaned} {'·' * (min_len - len(cleaned))}".strip()
        if len(cleaned) < min_len:
            cleaned = cleaned.ljust(min_len, ".")
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned


class MLComplaintClient:
    """HTTP Client for the standalone AI Complaint Management API (facebook/bart-large-mnli + all-MiniLM-L6-v2)."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> None:
        self.base_url = (base_url or settings.EXTERNAL_ML_API_URL).rstrip("/")
        self.timeout = timeout or settings.EXTERNAL_ML_API_TIMEOUT
        self.enabled = enabled if enabled is not None else settings.EXTERNAL_ML_API_ENABLED

    def map_dept_name_to_code(self, dept_name: str) -> Optional[str]:
        """Maps an external department name (e.g. 'Roads') to our internal department code (e.g. 'ROADS')."""
        return EXTERNAL_DEPT_TO_CODE.get(dept_name.strip().lower())

    async def check_health(self) -> MLHealthResponse:
        """Pings the external ML service health check endpoint."""
        url = f"{self.base_url}/health"
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                res = await client.get(url)
                if res.is_success:
                    data = res.json()
                    return MLHealthResponse(
                        connected=True,
                        url=self.base_url,
                        status=data.get("status", "healthy"),
                        model=data.get("model", "facebook/bart-large-mnli"),
                        embedding_model=data.get("embedding_model", "all-MiniLM-L6-v2"),
                        details=data,
                    )
                return MLHealthResponse(
                    connected=False,
                    url=self.base_url,
                    status=f"HTTP_{res.status_code}",
                    error=res.text[:200],
                )
        except Exception as exc:
            logger.debug("ML Service health check failed at %s: %s", url, exc)
            return MLHealthResponse(
                connected=False,
                url=self.base_url,
                error=str(exc),
            )

    async def analyze_complaint(
        self,
        citizen_name: Optional[str] = None,
        contact: Optional[str] = None,
        location: Optional[str] = None,
        complaint_text: Optional[str] = None,
        category: Optional[str] = None,
    ) -> Optional[MLComplaintResponse]:
        """Submits complaint to the external AI service for zero-shot routing, priority, duplicate check, and summary."""
        if not self.enabled:
            logger.info("External ML API is disabled by configuration.")
            return None

        # Sanitize and enforce API schema constraints
        safe_name = normalize_string_length(citizen_name, "Citizen", 2, 100)
        safe_contact = normalize_string_length(contact, "9999999999", 5, 100)
        safe_location = normalize_string_length(location, "City Municipal Area", 3, 200)
        safe_text = normalize_string_length(
            complaint_text,
            "Municipal Grievance - Citizen reported issue requiring inspection.",
            20,
            2000,
        )
        safe_category = normalize_string_length(category, "General Grievance", 2, 100)

        payload = MLComplaintRequest(
            citizen_name=safe_name,
            contact=safe_contact,
            location=safe_location,
            complaint_text=safe_text,
            category=safe_category,
        )

        url = f"{self.base_url}/complaints"
        try:
            logger.info(
                "Submitting complaint to external ML service at %s (timeout: %.1fs)",
                url,
                self.timeout,
            )
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                res = await client.post(url, json=payload.model_dump())
                res.raise_for_status()
                data = res.json()

                response_obj = MLComplaintResponse.model_validate(data)
                logger.info(
                    "ML service returned departments=%s, priority=%s, confidence=%.2f, duplicate=%s",
                    response_obj.ai_analysis.departments,
                    response_obj.ai_analysis.priority,
                    response_obj.ai_analysis.ai_confidence,
                    response_obj.ai_analysis.is_duplicate,
                )
                return response_obj

        except httpx.TimeoutException:
            logger.warning(
                "External ML service timed out after %.1fs at %s; falling back to internal heuristics",
                self.timeout,
                url,
            )
            return None
        except httpx.ConnectError:
            logger.warning(
                "Could not connect to external ML service at %s; falling back to internal heuristics",
                url,
            )
            return None
        except Exception as exc:
            logger.warning(
                "External ML service error at %s: %s; falling back to internal heuristics",
                url,
                exc,
            )
            return None


ml_client = MLComplaintClient()
