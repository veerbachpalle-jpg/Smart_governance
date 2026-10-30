import asyncio
import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import BadRequestError, NotFoundError
from app.modules.ai_assist.models.ai_interpretation import AIInterpretation
from app.modules.ai_assist.repository.ai_repository import AIInterpretationRepository
from app.modules.ai_assist.schemas.ai_assist import (
    AcceptInterpretationRequest,
    AIInterpretationResponse,
    InterpretationResult,
    LanguageDetectResult,
    OverrideInterpretationRequest,
    RejectInterpretationRequest,
)
from app.modules.ai_assist.service.guardrails import (
    ai_circuit_breaker,
    sanitize_and_delimit_untrusted_input,
    validate_root_cause_guardrail,
)
from app.modules.ai_assist.service.providers import LLMProvider, get_llm_provider
from app.modules.audit.service.audit_service import AuditService
from app.modules.complaints.repository.complaint_repository import ComplaintRepository
from app.modules.identity.models.user import User

logger = logging.getLogger("app.ai.service")
PROMPT_BASE_DIR = Path("prompts")
T = TypeVar("T", bound=BaseModel)


class PromptManager:
    """Loads and caches versioned system prompt templates."""

    _cache: dict[str, str] = {}

    @classmethod
    def get_prompt(cls, prompt_name: str, version: str = "v1") -> str:
        cache_key = f"{version}:{prompt_name}"
        if cache_key in cls._cache:
            return cls._cache[cache_key]

        file_path = PROMPT_BASE_DIR / version / f"{prompt_name}.md"
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt template '{file_path}' does not exist.")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        cls._cache[cache_key] = content
        return content


class AIAssistService:
    def __init__(self, session: AsyncSession, provider: Optional[LLMProvider] = None) -> None:
        self.session = session
        self.ai_repo = AIInterpretationRepository(session)
        self.complaint_repo = ComplaintRepository(session)
        self.audit_service = AuditService(session)
        self.provider = provider or get_llm_provider()

    async def execute_triage_pipeline(
        self, complaint_id: uuid.UUID, prompt_version: str = "v1"
    ) -> Optional[AIInterpretation]:
        """Runs the automated AI grievance triage pipeline or gracefully degrades to MANUAL_TRIAGE."""
        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if not complaint:
            logger.error("Complaint %s not found for AI triage pipeline", complaint_id)
            return None

        # 1. Kill switch / chaos check: if AI is disabled, degrade immediately to MANUAL_TRIAGE
        from app.core.chaos import chaos_manager

        if not settings.AI_ENABLED or chaos_manager.state.disable_ai:
            logger.info(
                "AI is disabled (kill switch or chaos simulation active); setting complaint %s to MANUAL_TRIAGE",
                complaint_id,
            )
            complaint.status = "MANUAL_TRIAGE"
            await self.audit_service.record_event(
                entity_type="complaint",
                entity_id=complaint.id,
                action="complaint.manual_triage_fallback",
                new_state={
                    "status": "MANUAL_TRIAGE",
                    "reason": "AI disabled by kill switch or chaos simulation",
                },
            )
            return None

        # 2. Circuit breaker check
        if not ai_circuit_breaker.can_execute():
            logger.warning(
                "AI circuit breaker is OPEN; setting complaint %s to MANUAL_TRIAGE", complaint_id
            )
            complaint.status = "MANUAL_TRIAGE"
            await self.audit_service.record_event(
                entity_type="complaint",
                entity_id=complaint.id,
                action="complaint.manual_triage_fallback",
                new_state={"status": "MANUAL_TRIAGE", "reason": "AI circuit breaker OPEN"},
            )
            return None

        # Transition status to AI_TRIAGE_PENDING while processing
        complaint.status = "AI_TRIAGE_PENDING"
        await self.session.flush()

        start_time = time.monotonic()
        try:
            # 3. Guardrail: Redact PII and sanitize input
            delimited_input = sanitize_and_delimit_untrusted_input(
                title=complaint.original_title,
                description=complaint.original_description,
            )

            # Compute input hash for deduplication and audit tracking
            input_hash = hashlib.sha256(delimited_input.encode("utf-8")).hexdigest()

            # 4. Language Detection & Translation
            lang_prompt = PromptManager.get_prompt("language_detect", version=prompt_version)
            lang_result = await self._generate_structured_with_retry(
                prompt=delimited_input,
                schema=LanguageDetectResult,
                system_instruction=lang_prompt,
            )

            # Update translated fields on complaint while preserving original verbatim
            complaint.original_language = lang_result.language_code
            if lang_result.requires_translation:
                complaint.translated_title = lang_result.translated_title
                complaint.translated_description = lang_result.translated_description

            # Prepare working text for interpretation (use translation if available)
            working_title = complaint.translated_title or complaint.original_title
            working_desc = complaint.translated_description or complaint.original_description
            working_delimited = sanitize_and_delimit_untrusted_input(
                title=working_title,
                description=working_desc,
            )

            # 5. Interpretation with retry on invalid format
            interpret_prompt = PromptManager.get_prompt("interpret", version=prompt_version)
            interpretation = await self._generate_structured_with_retry(
                prompt=working_delimited,
                schema=InterpretationResult,
                system_instruction=interpret_prompt,
            )

            # 6. Guardrail: Validate root cause separation post-check
            parsed_dict = interpretation.model_dump()
            validated_dict = validate_root_cause_guardrail(parsed_dict)
            confidence = float(validated_dict.get("confidence", 0.0))

            # 6b. External AI Complaint Management API (facebook/bart-large-mnli & all-MiniLM-L6-v2)
            ml_analysis_dict: dict[str, Any] | None = None
            if settings.EXTERNAL_ML_API_ENABLED:
                try:
                    from app.modules.identity.models.user import User
                    from app.modules.integrations.ml_service.client import ml_client

                    citizen_user = await self.session.get(User, complaint.citizen_id)
                    ml_res = await ml_client.analyze_complaint(
                        citizen_name=citizen_user.full_name if citizen_user else "Citizen",
                        contact=citizen_user.phone_number if citizen_user else "9999999999",
                        location=complaint.address or complaint.ward_name or "City Municipal Area",
                        complaint_text=f"{working_title}. {working_desc}",
                        category=validated_dict.get("category") or "General Grievance",
                    )
                    if ml_res and ml_res.ai_analysis:
                        ml_analysis_dict = ml_res.ai_analysis.model_dump()
                        validated_dict["dept_scores"] = [
                            s.model_dump() if hasattr(s, "model_dump") else s
                            for s in ml_res.ai_analysis.dept_scores
                        ]
                        validated_dict["departments"] = ml_res.ai_analysis.departments
                        validated_dict["ai_summary"] = ml_res.ai_analysis.ai_summary
                        validated_dict["similarity_score"] = ml_res.ai_analysis.similarity_score
                        validated_dict["is_duplicate"] = ml_res.ai_analysis.is_duplicate
                        validated_dict["duplicate_of"] = ml_res.ai_analysis.duplicate_of
                        validated_dict["ml_priority"] = ml_res.ai_analysis.priority
                        validated_dict["external_ml_model"] = "facebook/bart-large-mnli"
                        ml_conf = float(ml_res.ai_analysis.ai_confidence or 0.0)
                        if ml_conf > confidence:
                            confidence = ml_conf
                except Exception as ml_err:
                    logger.warning("External ML service call failed gracefully: %s", ml_err)

            latency_ms = int((time.monotonic() - start_time) * 1000)
            ai_circuit_breaker.record_success()

            model_name = (
                "facebook/bart-large-mnli"
                if ml_analysis_dict
                else (settings.GEMINI_MODEL if settings.GEMINI_API_KEY else "mock-keyword-provider")
            )

            # 7. Confidence check: low confidence degrades to MANUAL_TRIAGE
            if confidence < settings.AI_CONFIDENCE_THRESHOLD:
                logger.info(
                    "Complaint %s AI confidence %.2f < threshold %.2f; degrading to MANUAL_TRIAGE",
                    complaint_id,
                    confidence,
                    settings.AI_CONFIDENCE_THRESHOLD,
                )
                complaint.status = "MANUAL_TRIAGE"
                interpretation_rec = AIInterpretation(
                    complaint_id=complaint.id,
                    model=model_name,
                    prompt_version=prompt_version,
                    input_hash=input_hash,
                    raw_output=json.dumps(validated_dict),
                    parsed_output=validated_dict,
                    confidence=confidence,
                    latency_ms=latency_ms,
                    recommendation_status="PENDING",
                )
                created = await self.ai_repo.create(interpretation_rec)
                await self.audit_service.record_event(
                    entity_type="complaint",
                    entity_id=complaint.id,
                    action="complaint.manual_triage_fallback",
                    new_state={
                        "status": "MANUAL_TRIAGE",
                        "reason": f"Low AI confidence ({confidence:.2f} < {settings.AI_CONFIDENCE_THRESHOLD:.2f})",
                        "ai_interpretation_id": str(created.id),
                    },
                )
                return created

            # 8. Success: Transition complaint status to TRIAGE_REVIEW
            complaint.status = "TRIAGE_REVIEW"
            interpretation_rec = AIInterpretation(
                complaint_id=complaint.id,
                model=model_name,
                prompt_version=prompt_version,
                input_hash=input_hash,
                raw_output=json.dumps(validated_dict),
                parsed_output=validated_dict,
                confidence=confidence,
                latency_ms=latency_ms,
                recommendation_status="PENDING",
            )
            created = await self.ai_repo.create(interpretation_rec)

            await self.audit_service.record_event(
                entity_type="complaint",
                entity_id=complaint.id,
                action="complaint.ai_triage_completed",
                new_state={
                    "status": "TRIAGE_REVIEW",
                    "category": validated_dict.get("category"),
                    "sub_category": validated_dict.get("sub_category"),
                    "confidence": confidence,
                    "ai_interpretation_id": str(created.id),
                },
            )

            # Downstream pipeline: generate recommendations for routing, priority, duplicates
            try:
                from app.modules.routing.service.routing_service import RoutingService

                ml_scores = (
                    validated_dict.get("dept_scores")
                    if ml_analysis_dict
                    else None
                )
                await RoutingService(self.session).generate_routing_recommendation(
                    complaint.id,
                    ml_dept_scores=ml_scores,
                )
            except Exception as r_err:
                logger.warning("Downstream routing generation failed: %s", r_err)

            try:
                from app.modules.priority.service.priority_service import PriorityService

                model_pri = "MEDIUM"
                if ml_analysis_dict and ml_analysis_dict.get("priority"):
                    pri_raw = str(ml_analysis_dict["priority"]).upper()
                    if pri_raw in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                        model_pri = pri_raw

                await PriorityService(self.session).assess_priority(
                    complaint.id,
                    model_priority_hint=model_pri,
                    model_confidence=confidence,
                )
            except Exception as p_err:
                logger.warning("Downstream priority assessment failed: %s", p_err)

            try:
                from app.modules.duplicates.service.duplicate_service import DuplicateService

                dup_service = DuplicateService(self.session)
                await dup_service.get_or_create_embedding(complaint)
                await dup_service.search_and_rank_candidates(complaint.id)
            except Exception as d_err:
                logger.warning("Downstream duplicate processing failed: %s", d_err)

            return created

        except Exception as exc:
            ai_circuit_breaker.record_failure()
            logger.warning(
                "AI triage pipeline failed for complaint %s: %s; falling back to MANUAL_TRIAGE",
                complaint_id,
                str(exc),
            )
            complaint.status = "MANUAL_TRIAGE"
            await self.audit_service.record_event(
                entity_type="complaint",
                entity_id=complaint.id,
                action="complaint.manual_triage_fallback",
                new_state={"status": "MANUAL_TRIAGE", "error": str(exc)},
            )
            return None

    async def _generate_structured_with_retry(
        self, prompt: str, schema: type[T], system_instruction: str
    ) -> T:
        """Invokes provider with 1 retry on validation / formatting errors."""
        from app.core.chaos import chaos_manager

        if chaos_manager.state.ai_garbage:
            raise ValueError("Simulated AI corruption: returned unparseable garbage output")

        try:
            return await asyncio.wait_for(
                self.provider.generate_structured(
                    prompt=prompt,
                    schema=schema,
                    system_instruction=system_instruction,
                ),
                timeout=settings.AI_TIMEOUT_SECONDS,
            )
        except Exception as first_err:
            logger.warning(
                "First attempt for %s failed (%s); retrying once...",
                schema.__name__,
                str(first_err),
            )
            correction_instruction = (
                f"{system_instruction}\n\nIMPORTANT: Your previous output failed schema validation with error: "
                f"{str(first_err)}. Please ensure all fields adhere strictly to the schema without root causes."
            )
            return await asyncio.wait_for(
                self.provider.generate_structured(
                    prompt=prompt,
                    schema=schema,
                    system_instruction=correction_instruction,
                ),
                timeout=settings.AI_TIMEOUT_SECONDS,
            )

    async def get_latest_interpretation(self, complaint_id: uuid.UUID) -> AIInterpretationResponse:
        """Retrieves the latest AI interpretation recommendation for a complaint."""
        record = await self.ai_repo.get_latest_by_complaint_id(complaint_id)
        if not record:
            raise NotFoundError(
                detail=f"No AI interpretation found for complaint '{complaint_id}'.",
                code="AI_INTERPRETATION_NOT_FOUND",
            )
        return AIInterpretationResponse.model_validate(record)

    async def accept_interpretation(
        self,
        complaint_id: uuid.UUID,
        officer: User,
        payload: AcceptInterpretationRequest,
    ) -> AIInterpretationResponse:
        """Human officer accepts the AI recommendation."""
        record = await self.ai_repo.get_latest_by_complaint_id(complaint_id)
        if not record:
            raise NotFoundError(
                detail=f"No AI interpretation found for complaint '{complaint_id}'.",
                code="AI_INTERPRETATION_NOT_FOUND",
            )

        now = datetime.now(timezone.utc)
        record.recommendation_status = "ACCEPTED"
        record.decided_by_id = officer.id
        record.decided_at = now
        record.decision_reason = payload.notes

        # Advance complaint status
        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if complaint and complaint.status in (
            "TRIAGE_REVIEW",
            "MANUAL_TRIAGE",
            "AI_TRIAGE_PENDING",
        ):
            complaint.status = "ROUTED"

        await self.audit_service.record_event(
            entity_type="ai_interpretation",
            entity_id=record.id,
            action="ai_interpretation.accepted",
            actor_id=officer.id,
            actor_role=officer.role,
            new_state={
                "complaint_id": str(complaint_id),
                "status": "ACCEPTED",
                "notes": payload.notes,
            },
        )
        return AIInterpretationResponse.model_validate(record)

    async def override_interpretation(
        self,
        complaint_id: uuid.UUID,
        officer: User,
        payload: OverrideInterpretationRequest,
    ) -> AIInterpretationResponse:
        """Human officer overrides the AI recommendation with required justification."""
        if not payload.reason or len(payload.reason.strip()) < 5:
            raise BadRequestError(
                detail="A substantive reason of at least 5 characters is strictly required to override AI recommendation.",
                code="OVERRIDE_REASON_REQUIRED",
            )

        record = await self.ai_repo.get_latest_by_complaint_id(complaint_id)
        if not record:
            raise NotFoundError(
                detail=f"No AI interpretation found for complaint '{complaint_id}'.",
                code="AI_INTERPRETATION_NOT_FOUND",
            )

        now = datetime.now(timezone.utc)
        record.recommendation_status = "OVERRIDDEN"
        record.decided_by_id = officer.id
        record.decided_at = now
        record.decision_reason = payload.reason.strip()

        # Apply officer's manual categorization into parsed_output
        updated_output = dict(record.parsed_output)
        if payload.category:
            updated_output["category"] = payload.category.strip()
        if payload.sub_category:
            updated_output["sub_category"] = payload.sub_category.strip()
        record.parsed_output = updated_output

        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if complaint and complaint.status in (
            "TRIAGE_REVIEW",
            "MANUAL_TRIAGE",
            "AI_TRIAGE_PENDING",
        ):
            complaint.status = "ROUTED"

        await self.audit_service.record_event(
            entity_type="ai_interpretation",
            entity_id=record.id,
            action="ai_interpretation.overridden",
            actor_id=officer.id,
            actor_role=officer.role,
            new_state={
                "complaint_id": str(complaint_id),
                "status": "OVERRIDDEN",
                "reason": payload.reason.strip(),
                "overridden_category": payload.category,
                "overridden_sub_category": payload.sub_category,
            },
        )
        return AIInterpretationResponse.model_validate(record)

    async def reject_interpretation(
        self,
        complaint_id: uuid.UUID,
        officer: User,
        payload: RejectInterpretationRequest,
    ) -> AIInterpretationResponse:
        """Human officer rejects the AI recommendation entirely with mandatory reason."""
        if not payload.reason or len(payload.reason.strip()) < 5:
            raise BadRequestError(
                detail="A substantive reason of at least 5 characters is strictly required to reject AI recommendation.",
                code="REJECTION_REASON_REQUIRED",
            )

        record = await self.ai_repo.get_latest_by_complaint_id(complaint_id)
        if not record:
            raise NotFoundError(
                detail=f"No AI interpretation found for complaint '{complaint_id}'.",
                code="AI_INTERPRETATION_NOT_FOUND",
            )

        now = datetime.now(timezone.utc)
        record.recommendation_status = "REJECTED"
        record.decided_by_id = officer.id
        record.decided_at = now
        record.decision_reason = payload.reason.strip()

        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if complaint:
            complaint.status = "MANUAL_TRIAGE"

        await self.audit_service.record_event(
            entity_type="ai_interpretation",
            entity_id=record.id,
            action="ai_interpretation.rejected",
            actor_id=officer.id,
            actor_role=officer.role,
            new_state={
                "complaint_id": str(complaint_id),
                "status": "REJECTED",
                "reason": payload.reason.strip(),
            },
        )
        return AIInterpretationResponse.model_validate(record)
