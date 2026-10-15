import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, NotFoundError
from app.modules.audit.service.audit_service import AuditService
from app.modules.complaints.repository.complaint_repository import ComplaintRepository
from app.modules.identity.models.user import User
from app.modules.priority.models.priority import PriorityAssessment, PriorityPolicy
from app.modules.priority.repository.priority_repository import PriorityRepository
from app.modules.priority.schemas.priority import (
    AcceptPriorityRequest,
    OverridePriorityRequest,
    PriorityAssessmentResponse,
    PriorityPolicyCreate,
    PriorityPolicyResponse,
    PriorityQueueItem,
    RejectPriorityRequest,
)

logger = logging.getLogger("app.priority.service")

PRIORITY_LEVELS = {
    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}
LEVELS_TO_PRIORITY = {v: k for k, v in PRIORITY_LEVELS.items()}
SLA_HOURS_MAP = {
    "CRITICAL": 4,
    "HIGH": 24,
    "MEDIUM": 48,
    "LOW": 168,
}

DEFAULT_POLICIES = [
    {
        "policy_name": "EN_Live_Electrical_Hazard",
        "language": "en",
        "keyword_pattern": r"\b(live wire|sparking|electrocution|electric shock|exposed wire|hanging wire)\b",
        "elevate_to_priority": "CRITICAL",
        "description": "Exposed electrical conductors or sparking overhead lines",
    },
    {
        "policy_name": "EN_Structural_Gas_Collapse",
        "language": "en",
        "keyword_pattern": r"\b(gas leak|bridge collapse|wall collapse|building collapse|sinkhole)\b",
        "elevate_to_priority": "CRITICAL",
        "description": "Immediate catastrophic structural collapse or explosive gas risk",
    },
    {
        "policy_name": "EN_Open_Manhole_Sewage",
        "language": "en",
        "keyword_pattern": r"\b(uncovered manhole|open manhole|sewage contaminating|toxic fumes|chemical contamination)\b",
        "elevate_to_priority": "HIGH",
        "description": "Acute pedestrian falling hazard or direct drinking water contamination",
    },
    {
        "policy_name": "HI_Electrical_Hazard",
        "language": "hi",
        "keyword_pattern": r"(खुला तार|करंट|बिजली का झटका|बिजली का तार|आग)",
        "elevate_to_priority": "CRITICAL",
        "description": "Hindi keywords for live wire, electrical shock, and fire",
    },
    {
        "policy_name": "HI_Contamination_Collapse",
        "language": "hi",
        "keyword_pattern": r"(जहरीला पानी|पुल गिर|दीवार गिर|गैस रिसाव|धंस गई|sinkhole)",
        "elevate_to_priority": "CRITICAL",
        "description": "Hindi keywords for poisonous water, sinkhole, and structural collapse",
    },
    {
        "policy_name": "HI_Open_Manhole",
        "language": "hi",
        "keyword_pattern": r"(खुला मैनहोल)",
        "elevate_to_priority": "HIGH",
        "description": "Hindi keyword for open manhole hazard",
    },
    {
        "policy_name": "KN_Electrical_Hazard",
        "language": "kn",
        "keyword_pattern": r"(ತೆರೆದ ತಂತಿ|ವಿದ್ಯುತ್ ಆಘಾತ|ಕರೆಂಟ್|ಬೆಂಕಿ|ಲೈವ್ ವೈರ್)",
        "elevate_to_priority": "CRITICAL",
        "description": "Kannada keywords for live wire, electric shock, and fire",
    },
    {
        "policy_name": "KN_Collapse_Contamination",
        "language": "kn",
        "keyword_pattern": r"(ಕುಸಿತ|ವಿಷಕಾರಿ ನೀರು|ಅನಿಲ ಸೋರಿಕೆ|ವಿಷಕಾರಿ ಅನಿಲ)",
        "elevate_to_priority": "CRITICAL",
        "description": "Kannada keywords for structural collapse and toxic contamination",
    },
    {
        "policy_name": "KN_Open_Manhole",
        "language": "kn",
        "keyword_pattern": r"(ತೆರೆದ ಮ್ಯಾನ್‌ಹೋಲ್)",
        "elevate_to_priority": "HIGH",
        "description": "Kannada keyword for open manhole",
    },
    {
        "policy_name": "CM_Safety_Hazard",
        "language": "code_mixed",
        "keyword_pattern": r"\b(live wire|sparking|electrocution|current|gas leak|sinkhole|collapse|open manhole|uncovered manhole)\b",
        "elevate_to_priority": "CRITICAL",
        "description": "Code-mixed safety hazards",
    },
]


def enforce_safety_only_raises(model_priority: str, rule_hits: list[dict[str, Any]]) -> str:
    """CRITICAL INVARIANT: Safety rule hits can only RAISE the suggested priority, NEVER lower it."""
    model_score = PRIORITY_LEVELS.get(model_priority.upper(), 2)  # default MEDIUM (2)
    highest_score = model_score

    for hit in rule_hits:
        target_pri = hit.get("elevate_to_priority", "CRITICAL").upper()
        target_score = PRIORITY_LEVELS.get(target_pri, 4)
        if target_score > highest_score:
            highest_score = target_score

    # Guaranteed invariant: highest_score >= model_score
    return LEVELS_TO_PRIORITY[highest_score]


class PriorityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PriorityRepository(session)
        self.complaint_repo = ComplaintRepository(session)
        self.audit_service = AuditService(session)

    async def initialize_default_policies_if_empty(self) -> None:
        existing = await self.repo.list_policies()
        if not existing:
            for p in DEFAULT_POLICIES:
                policy = PriorityPolicy(
                    policy_name=p["policy_name"],
                    language=p["language"],
                    keyword_pattern=p["keyword_pattern"],
                    elevate_to_priority=p["elevate_to_priority"],
                    description=p["description"],
                    is_active=True,
                )
                await self.repo.create_policy(policy)
            await self.session.flush()

    async def create_policy(self, payload: PriorityPolicyCreate) -> PriorityPolicyResponse:
        policy = PriorityPolicy(
            policy_name=payload.policy_name.strip(),
            language=payload.language.strip().lower(),
            keyword_pattern=payload.keyword_pattern.strip(),
            elevate_to_priority=payload.elevate_to_priority.strip().upper(),
            description=payload.description,
            is_active=payload.is_active,
        )
        created = await self.repo.create_policy(policy)
        return PriorityPolicyResponse.model_validate(created)

    async def list_policies(self) -> list[PriorityPolicyResponse]:
        policies = await self.repo.list_policies()
        return [PriorityPolicyResponse.model_validate(p) for p in policies]

    async def assess_priority(
        self,
        complaint_id: uuid.UUID,
        model_priority_hint: str = "MEDIUM",
        model_confidence: float = 0.85,
        model_reasoning: str = "Baseline model priority assessment.",
    ) -> PriorityAssessmentResponse:
        """Assesses complaint priority combining explicit multilingual safety policies and model suggestion."""
        await self.initialize_default_policies_if_empty()

        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if not complaint:
            raise NotFoundError(
                f"Complaint '{complaint_id}' not found.", code="COMPLAINT_NOT_FOUND"
            )

        # 1. Search text across original and translated fields
        search_corpus = f"{complaint.original_title} {complaint.original_description}"
        if complaint.translated_title:
            search_corpus += f" {complaint.translated_title} {complaint.translated_description}"

        # 2. Check explicit active safety policies
        policies = await self.repo.list_policies(is_active=True)
        rule_hits: list[dict[str, Any]] = []

        for policy in policies:
            # Check pattern match
            try:
                if re.search(policy.keyword_pattern, search_corpus, re.IGNORECASE):
                    rule_hits.append(
                        {
                            "policy_name": policy.policy_name,
                            "language": policy.language,
                            "keyword_pattern": policy.keyword_pattern,
                            "elevate_to_priority": policy.elevate_to_priority,
                        }
                    )
            except re.error:
                # If regex compilation fails, fallback to simple substring
                if policy.keyword_pattern.lower() in search_corpus.lower():
                    rule_hits.append(
                        {
                            "policy_name": policy.policy_name,
                            "language": policy.language,
                            "keyword_pattern": policy.keyword_pattern,
                            "elevate_to_priority": policy.elevate_to_priority,
                        }
                    )

        # 3. Apply safety-only-raises invariant
        final_priority = enforce_safety_only_raises(
            model_priority=model_priority_hint,
            rule_hits=rule_hits,
        )
        suggested_sla = SLA_HOURS_MAP.get(final_priority, 48)
        is_safety_critical = final_priority == "CRITICAL"

        assessment = PriorityAssessment(
            complaint_id=complaint.id,
            model_priority=model_priority_hint,
            model_confidence=model_confidence,
            model_reasoning=model_reasoning,
            rule_hits=rule_hits,
            final_suggested_priority=final_priority,
            suggested_sla_hours=suggested_sla,
            is_safety_critical=is_safety_critical,
            recommendation_status="PENDING",
        )
        created = await self.repo.create_assessment(assessment)

        await self.audit_service.record_event(
            entity_type="priority_assessment",
            entity_id=created.id,
            action="priority.assessed",
            new_state={
                "complaint_id": str(complaint_id),
                "model_priority": model_priority_hint,
                "final_suggested_priority": final_priority,
                "rule_hits_count": len(rule_hits),
                "is_safety_critical": is_safety_critical,
            },
        )
        return PriorityAssessmentResponse.model_validate(created)

    async def get_latest_assessment(self, complaint_id: uuid.UUID) -> PriorityAssessmentResponse:
        assessment = await self.repo.get_latest_assessment(complaint_id)
        if not assessment:
            return await self.assess_priority(complaint_id)
        return PriorityAssessmentResponse.model_validate(assessment)

    async def list_critical_queue(self) -> list[PriorityQueueItem]:
        """Returns prioritized safety-critical items flagged for urgent officer triage."""
        assessments = await self.repo.list_critical_queue()
        items: list[PriorityQueueItem] = []
        for ass in assessments:
            complaint = await self.complaint_repo.get_by_id(ass.complaint_id)
            if complaint:
                items.append(
                    PriorityQueueItem(
                        complaint_id=complaint.id,
                        tracking_number=complaint.tracking_number,
                        title=complaint.original_title,
                        ward_name=complaint.ward_name,
                        final_suggested_priority=ass.final_suggested_priority,
                        rule_hits_count=len(ass.rule_hits),
                        created_at=ass.created_at,
                    )
                )
        return items

    async def accept_priority(
        self, complaint_id: uuid.UUID, officer: User, payload: AcceptPriorityRequest
    ) -> PriorityAssessmentResponse:
        assessment = await self.repo.get_latest_assessment(complaint_id)
        if not assessment:
            await self.assess_priority(complaint_id)
            assessment = await self.repo.get_latest_assessment(complaint_id)
            assert assessment is not None

        now = datetime.now(timezone.utc)
        assessment.recommendation_status = "ACCEPTED"
        assessment.decided_by_id = officer.id
        assessment.decided_at = now
        assessment.decision_reason = payload.notes

        await self.audit_service.record_event(
            entity_type="priority_assessment",
            entity_id=assessment.id,
            action="priority.accepted",
            actor_id=officer.id,
            actor_role=officer.role,
            new_state={
                "complaint_id": str(complaint_id),
                "status": "ACCEPTED",
                "priority": assessment.final_suggested_priority,
            },
        )
        return PriorityAssessmentResponse.model_validate(assessment)

    async def override_priority(
        self, complaint_id: uuid.UUID, officer: User, payload: OverridePriorityRequest
    ) -> PriorityAssessmentResponse:
        if not payload.reason or len(payload.reason.strip()) < 5:
            raise BadRequestError(
                "A substantive reason of at least 5 characters is required to override priority.",
                code="OVERRIDE_REASON_REQUIRED",
            )

        assessment = await self.repo.get_latest_assessment(complaint_id)
        if not assessment:
            await self.assess_priority(complaint_id)
            assessment = await self.repo.get_latest_assessment(complaint_id)
            assert assessment is not None

        now = datetime.now(timezone.utc)
        assessment.recommendation_status = "OVERRIDDEN"
        assessment.final_suggested_priority = payload.priority.upper()
        assessment.suggested_sla_hours = SLA_HOURS_MAP.get(payload.priority.upper(), 48)
        assessment.is_safety_critical = payload.priority.upper() == "CRITICAL"
        assessment.decided_by_id = officer.id
        assessment.decided_at = now
        assessment.decision_reason = payload.reason.strip()

        await self.audit_service.record_event(
            entity_type="priority_assessment",
            entity_id=assessment.id,
            action="priority.overridden",
            actor_id=officer.id,
            actor_role=officer.role,
            new_state={
                "complaint_id": str(complaint_id),
                "status": "OVERRIDDEN",
                "new_priority": payload.priority.upper(),
                "reason": payload.reason.strip(),
            },
        )
        return PriorityAssessmentResponse.model_validate(assessment)

    async def reject_priority(
        self, complaint_id: uuid.UUID, officer: User, payload: RejectPriorityRequest
    ) -> PriorityAssessmentResponse:
        if not payload.reason or len(payload.reason.strip()) < 5:
            raise BadRequestError(
                "A substantive reason of at least 5 characters is required to reject priority.",
                code="REJECTION_REASON_REQUIRED",
            )

        assessment = await self.repo.get_latest_assessment(complaint_id)
        if not assessment:
            await self.assess_priority(complaint_id)
            assessment = await self.repo.get_latest_assessment(complaint_id)
            assert assessment is not None

        now = datetime.now(timezone.utc)
        assessment.recommendation_status = "REJECTED"
        assessment.decided_by_id = officer.id
        assessment.decided_at = now
        assessment.decision_reason = payload.reason.strip()

        await self.audit_service.record_event(
            entity_type="priority_assessment",
            entity_id=assessment.id,
            action="priority.rejected",
            actor_id=officer.id,
            actor_role=officer.role,
            new_state={
                "complaint_id": str(complaint_id),
                "status": "REJECTED",
                "reason": payload.reason.strip(),
            },
        )
        return PriorityAssessmentResponse.model_validate(assessment)
