import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.core.outbox import enqueue_outbox_event
from app.modules.activity.models.activity import CaseActivity
from app.modules.ai_assist.models.ai_interpretation import AIInterpretation
from app.modules.ai_assist.schemas.manual_triage import (
    ManualTriageQueueItemResponse,
    ManualTriageRequest,
    ManualTriageResultResponse,
)
from app.modules.audit.service.audit_service import AuditService
from app.modules.cases.models.case import Case, CaseComplaint, CaseDepartment
from app.modules.cases.repository.case_repository import CaseRepository
from app.modules.complaints.models.complaint import Complaint
from app.modules.complaints.repository.complaint_repository import ComplaintRepository
from app.modules.identity.models.user import Department, User
from app.modules.priority.models.priority import PriorityAssessment
from app.modules.routing.models.routing import RoutingRecommendation

logger = logging.getLogger("app.triage.manual")


class ManualTriageService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.complaint_repo = ComplaintRepository(session)
        self.case_repo = CaseRepository(session)
        self.audit_service = AuditService(session)

    async def get_manual_triage_queue(self) -> list[ManualTriageQueueItemResponse]:
        """Lists complaints currently in MANUAL_TRIAGE queue waiting for human assessment."""
        stmt = (
            select(Complaint)
            .where(Complaint.status.in_(["MANUAL_TRIAGE", "AI_TRIAGE_PENDING"]))
            .order_by(Complaint.created_at.asc())
        )
        res = await self.session.execute(stmt)
        complaints = list(res.scalars().all())
        return [ManualTriageQueueItemResponse.model_validate(c) for c in complaints]

    async def process_manual_triage(
        self,
        current_user: User,
        complaint_id: uuid.UUID,
        payload: ManualTriageRequest,
    ) -> ManualTriageResultResponse:
        """Processes manual officer triage, producing the same downstream records as the AI path marked source=MANUAL."""
        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if not complaint:
            raise NotFoundError(
                f"Complaint '{complaint_id}' not found.", code="COMPLAINT_NOT_FOUND"
            )

        # Verify department exists
        stmt_dept = select(Department).where(Department.id == payload.department_id)
        dept = (await self.session.execute(stmt_dept)).scalar_one_or_none()
        if not dept:
            raise NotFoundError(
                f"Department '{payload.department_id}' not found.",
                code="DEPARTMENT_NOT_FOUND",
            )

        now = datetime.now(timezone.utc)

        # 1. Downstream AIInterpretation record marked source=MANUAL
        interpretation = AIInterpretation(
            id=uuid.uuid4(),
            complaint_id=complaint.id,
            model="manual-officer-triage",
            prompt_version="manual",
            input_hash="manual",
            raw_output=json.dumps(
                {
                    "category": payload.category,
                    "sub_category": payload.sub_category,
                    "source": "MANUAL",
                }
            ),
            parsed_output={
                "category": payload.category,
                "sub_category": payload.sub_category,
                "reported_facts": [payload.category],
                "inferences": [],
                "officer_summary": payload.notes or "Manually triaged by officer",
                "source": "MANUAL",
            },
            confidence=1.0,
            latency_ms=0,
            recommendation_status="ACCEPTED",
            decided_by_id=current_user.id,
            decided_at=now,
            decision_reason=payload.notes or "Manual triage completed by officer",
        )
        self.session.add(interpretation)

        # 2. Downstream RoutingRecommendation record marked source=MANUAL
        routing_rec = RoutingRecommendation(
            id=uuid.uuid4(),
            complaint_id=complaint.id,
            rule_version_used=None,
            primary_department_id=payload.department_id,
            recommended_departments=[
                {
                    "department_id": str(payload.department_id),
                    "department_name": dept.name,
                    "confidence": 1.0,
                    "reason": "Manually routed by triage officer",
                    "source": "MANUAL",
                }
            ],
            confidence=1.0,
            recommendation_status="ACCEPTED",
            decided_by_id=current_user.id,
            decision_reason=payload.notes or "Manual routing decision",
            decided_at=now,
        )
        self.session.add(routing_rec)

        # 3. Downstream PriorityAssessment record marked source=MANUAL
        sla_hours = (
            6
            if payload.priority == "CRITICAL"
            else (
                24 if payload.priority == "HIGH" else (48 if payload.priority == "MEDIUM" else 72)
            )
        )
        priority_rec = PriorityAssessment(
            id=uuid.uuid4(),
            complaint_id=complaint.id,
            model_priority=payload.priority,
            model_confidence=1.0,
            model_reasoning="Manual priority assessment by officer",
            rule_hits=[{"rule": "MANUAL_ENTRY", "source": "MANUAL"}],
            final_suggested_priority=payload.priority,
            suggested_sla_hours=sla_hours,
            is_safety_critical=payload.priority in ("HIGH", "CRITICAL"),
            recommendation_status="ACCEPTED",
            decided_by_id=current_user.id,
            decision_reason=payload.notes or "Manual priority determination",
            decided_at=now,
        )
        self.session.add(priority_rec)

        # 4. Run duplicate embeddings if available
        try:
            from app.modules.duplicates.service.duplicate_service import DuplicateService

            dup_service = DuplicateService(self.session)
            await dup_service.get_or_create_embedding(complaint)
            await dup_service.search_and_rank_candidates(complaint.id)
        except Exception as d_err:
            logger.debug("Duplicate search skipped in manual triage: %s", d_err)

        # 5. Mutate complaint status to ROUTED
        complaint.status = "ROUTED"

        # 6. Create or Link to Case
        case = await self.case_repo.get_case_for_complaint(complaint.id)
        if not case:
            case_number = f"CASE-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
            case = Case(
                id=uuid.uuid4(),
                case_number=case_number,
                title=f"Case: {complaint.original_title}",
                description=complaint.original_description,
                status="ROUTED",
                priority=payload.priority,
                lead_department_id=payload.department_id,
                created_by_id=current_user.id,
            )
            self.session.add(case)
            await self.session.flush()

            cd = CaseDepartment(
                case_id=case.id,
                department_id=payload.department_id,
                is_lead=True,
                added_by_id=current_user.id,
            )
            self.session.add(cd)

            cc = CaseComplaint(
                case_id=case.id,
                complaint_id=complaint.id,
                is_primary=True,
            )
            self.session.add(cc)
        else:
            case.status = "ROUTED"
            case.lead_department_id = payload.department_id
            case.priority = payload.priority

        # 7. Immutable Audit Event
        await self.audit_service.record_event(
            entity_type="complaint",
            entity_id=complaint.id,
            action="complaint.manual_triage_completed",
            actor_id=current_user.id,
            actor_role=current_user.role,
            new_state={
                "status": "ROUTED",
                "category": payload.category,
                "sub_category": payload.sub_category,
                "priority": payload.priority,
                "department_id": str(payload.department_id),
                "case_id": str(case.id),
                "source": "MANUAL",
            },
        )

        # 8. Immutable Case Activity
        activity = CaseActivity(
            case_id=case.id,
            actor_id=current_user.id,
            activity_type="CASE_ROUTED",
            visibility="CITIZEN_VISIBLE",
            message=f"Case manually triaged and routed to {dept.name} (Priority: {payload.priority}).",
            activity_metadata={
                "category": payload.category,
                "sub_category": payload.sub_category,
                "priority": payload.priority,
                "department_id": str(payload.department_id),
                "source": "MANUAL",
            },
        )
        self.session.add(activity)

        # 9. Outbox event
        await enqueue_outbox_event(
            session=self.session,
            event_type="case.routed",
            aggregate_type="case",
            aggregate_id=case.id,
            payload={
                "case_id": str(case.id),
                "complaint_id": str(complaint.id),
                "department_id": str(payload.department_id),
                "priority": payload.priority,
                "source": "MANUAL",
            },
        )

        await self.session.flush()

        return ManualTriageResultResponse(
            complaint_id=complaint.id,
            case_id=case.id,
            status=complaint.status,
            category=payload.category,
            sub_category=payload.sub_category,
            department_id=payload.department_id,
            priority=payload.priority,
            source="MANUAL",
            ai_interpretation_id=interpretation.id,
            routing_recommendation_id=routing_rec.id,
            priority_assessment_id=priority_rec.id,
            decided_by_id=current_user.id,
            decided_at=now,
        )
