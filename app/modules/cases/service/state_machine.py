import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ForbiddenError
from app.core.outbox import enqueue_outbox_event
from app.modules.activity.models.activity import CaseActivity
from app.modules.audit.service.audit_service import AuditService
from app.modules.cases.models.case import Case, CaseReassignRequest
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

logger = logging.getLogger("app.cases.state_machine")


@dataclass
class TransitionRule:
    from_state: str
    to_state: str
    allowed_roles: set[str]
    activity_type: str
    visibility: str  # INTERNAL or CITIZEN_VISIBLE
    default_message: str


ALLOWED_TRANSITIONS: list[TransitionRule] = [
    # 1. TRIAGE_REVIEW -> ROUTED
    TransitionRule(
        from_state="TRIAGE_REVIEW",
        to_state="ROUTED",
        allowed_roles={UserRole.OFFICER.value, UserRole.SUPERVISOR.value, UserRole.ADMIN.value},
        activity_type="CASE_ROUTED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case has been routed to accountable department.",
    ),
    # 2. TRIAGE_REVIEW -> REJECTED_WITH_REASON
    TransitionRule(
        from_state="TRIAGE_REVIEW",
        to_state="REJECTED_WITH_REASON",
        allowed_roles={UserRole.OFFICER.value, UserRole.SUPERVISOR.value, UserRole.ADMIN.value},
        activity_type="COMPLAINT_REJECTED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case rejected as out of municipal jurisdiction or invalid.",
    ),
    # 3. ROUTED -> ACCEPTED_BY_LEAD
    TransitionRule(
        from_state="ROUTED",
        to_state="ACCEPTED_BY_LEAD",
        allowed_roles={
            UserRole.DEPARTMENT_LEAD.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="CASE_ACCEPTED_BY_DEPARTMENT",
        visibility="CITIZEN_VISIBLE",
        default_message="Case formally accepted by lead department.",
    ),
    # 4. ROUTED -> REJECTED_WITH_REASON
    TransitionRule(
        from_state="ROUTED",
        to_state="REJECTED_WITH_REASON",
        allowed_roles={UserRole.SUPERVISOR.value, UserRole.ADMIN.value},
        activity_type="CASE_REJECTED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case rejected by municipal supervisor.",
    ),
    # 5. ACCEPTED_BY_LEAD -> IN_PROGRESS
    TransitionRule(
        from_state="ACCEPTED_BY_LEAD",
        to_state="IN_PROGRESS",
        allowed_roles={
            UserRole.DEPARTMENT_LEAD.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="OFFICER_ASSIGNED",
        visibility="CITIZEN_VISIBLE",
        default_message="Officer assigned and field remediation is now in progress.",
    ),
    # 6. ACCEPTED_BY_LEAD -> REASSIGN_REQUESTED
    TransitionRule(
        from_state="ACCEPTED_BY_LEAD",
        to_state="REASSIGN_REQUESTED",
        allowed_roles={
            UserRole.DEPARTMENT_LEAD.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="REASSIGNMENT_REQUESTED",
        visibility="INTERNAL",
        default_message="Department lead requested jurisdictional reassignment.",
    ),
    # 7. IN_PROGRESS -> REASSIGN_REQUESTED
    TransitionRule(
        from_state="IN_PROGRESS",
        to_state="REASSIGN_REQUESTED",
        allowed_roles={
            UserRole.DEPARTMENT_LEAD.value,
            UserRole.OFFICER.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="REASSIGNMENT_REQUESTED",
        visibility="INTERNAL",
        default_message="Field officer requested reassignment due to misrouting.",
    ),
    # 7b. ROUTED -> REASSIGN_REQUESTED
    TransitionRule(
        from_state="ROUTED",
        to_state="REASSIGN_REQUESTED",
        allowed_roles={
            UserRole.DEPARTMENT_LEAD.value,
            UserRole.OFFICER.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="REASSIGNMENT_REQUESTED",
        visibility="INTERNAL",
        default_message="Department officer requested reassignment for newly routed case.",
    ),
    # 7c. TRIAGE_REVIEW -> REASSIGN_REQUESTED
    TransitionRule(
        from_state="TRIAGE_REVIEW",
        to_state="REASSIGN_REQUESTED",
        allowed_roles={
            UserRole.DEPARTMENT_LEAD.value,
            UserRole.OFFICER.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="REASSIGNMENT_REQUESTED",
        visibility="INTERNAL",
        default_message="Officer requested reassignment from triage review.",
    ),
    # 8. REASSIGN_REQUESTED -> ROUTED (Approved reassignment)
    TransitionRule(
        from_state="REASSIGN_REQUESTED",
        to_state="ROUTED",
        allowed_roles={UserRole.SUPERVISOR.value, UserRole.ADMIN.value},
        activity_type="CASE_REASSIGNED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case reassigned to new lead department by supervisor.",
    ),
    # 8b. REASSIGN_REQUESTED -> IN_PROGRESS (Rejected reassignment)
    TransitionRule(
        from_state="REASSIGN_REQUESTED",
        to_state="IN_PROGRESS",
        allowed_roles={UserRole.SUPERVISOR.value, UserRole.ADMIN.value},
        activity_type="REASSIGNMENT_REJECTED",
        visibility="CITIZEN_VISIBLE",
        default_message="Reassignment request rejected by supervisor; case remains with current department.",
    ),
    # 9. IN_PROGRESS -> RESOLUTION_PROPOSED
    TransitionRule(
        from_state="IN_PROGRESS",
        to_state="RESOLUTION_PROPOSED",
        allowed_roles={
            UserRole.OFFICER.value,
            UserRole.DEPARTMENT_LEAD.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="RESOLUTION_PROPOSED",
        visibility="CITIZEN_VISIBLE",
        default_message="Remediation completed; resolution proposed by field officer.",
    ),
    # 10. RESOLUTION_PROPOSED -> CITIZEN_REVIEW
    TransitionRule(
        from_state="RESOLUTION_PROPOSED",
        to_state="CITIZEN_REVIEW",
        allowed_roles={
            UserRole.OFFICER.value,
            UserRole.DEPARTMENT_LEAD.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
            UserRole.CITIZEN.value,
        },
        activity_type="CITIZEN_REVIEW_OPENED",
        visibility="CITIZEN_VISIBLE",
        default_message="Remediation verified; citizen review window is now open.",
    ),
    # 11. CITIZEN_REVIEW -> CLOSED
    TransitionRule(
        from_state="CITIZEN_REVIEW",
        to_state="CLOSED",
        allowed_roles={
            UserRole.CITIZEN.value,
            UserRole.OFFICER.value,
            UserRole.DEPARTMENT_LEAD.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="CASE_CLOSED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case closed following citizen confirmation or review window expiry.",
    ),
    # 12. CITIZEN_REVIEW -> CHALLENGED
    TransitionRule(
        from_state="CITIZEN_REVIEW",
        to_state="CHALLENGED",
        allowed_roles={
            UserRole.CITIZEN.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="RESOLUTION_CHALLENGED",
        visibility="CITIZEN_VISIBLE",
        default_message="Citizen disputed the proposed resolution.",
    ),
    # 13. REJECTED_WITH_REASON -> CHALLENGED
    TransitionRule(
        from_state="REJECTED_WITH_REASON",
        to_state="CHALLENGED",
        allowed_roles={
            UserRole.CITIZEN.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="REJECTION_CHALLENGED",
        visibility="CITIZEN_VISIBLE",
        default_message="Citizen challenged the rejection decision.",
    ),
    # 14. IN_PROGRESS -> CHALLENGED
    TransitionRule(
        from_state="IN_PROGRESS",
        to_state="CHALLENGED",
        allowed_roles={
            UserRole.CITIZEN.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="ACTION_CHALLENGED",
        visibility="CITIZEN_VISIBLE",
        default_message="Citizen challenged official action or priority.",
    ),
    # 15. ROUTED -> CHALLENGED
    TransitionRule(
        from_state="ROUTED",
        to_state="CHALLENGED",
        allowed_roles={
            UserRole.CITIZEN.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="ACTION_CHALLENGED",
        visibility="CITIZEN_VISIBLE",
        default_message="Citizen challenged routing decision.",
    ),
    # 16. CHALLENGED -> UNDER_REVIEW
    TransitionRule(
        from_state="CHALLENGED",
        to_state="UNDER_REVIEW",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="CHALLENGE_UNDER_REVIEW",
        visibility="INTERNAL",
        default_message="Challenge assigned to supervisor for independent review.",
    ),
    # 17. UNDER_REVIEW -> UPHELD
    TransitionRule(
        from_state="UNDER_REVIEW",
        to_state="UPHELD",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="CHALLENGE_UPHELD",
        visibility="CITIZEN_VISIBLE",
        default_message="Challenge review completed: official resolution upheld.",
    ),
    # 18. UNDER_REVIEW -> OVERTURNED
    TransitionRule(
        from_state="UNDER_REVIEW",
        to_state="OVERTURNED",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="CHALLENGE_OVERTURNED",
        visibility="CITIZEN_VISIBLE",
        default_message="Challenge review completed: official decision overturned.",
    ),
    # 19. CHALLENGED -> OVERTURNED
    TransitionRule(
        from_state="CHALLENGED",
        to_state="OVERTURNED",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="CHALLENGE_OVERTURNED",
        visibility="CITIZEN_VISIBLE",
        default_message="Challenge review completed: official decision overturned.",
    ),
    # 20. CHALLENGED -> UPHELD
    TransitionRule(
        from_state="CHALLENGED",
        to_state="UPHELD",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="CHALLENGE_UPHELD",
        visibility="CITIZEN_VISIBLE",
        default_message="Challenge review completed: official resolution upheld.",
    ),
    # 21. OVERTURNED -> REOPENED
    TransitionRule(
        from_state="OVERTURNED",
        to_state="REOPENED",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
            UserRole.OFFICER.value,
        },
        activity_type="CASE_REOPENED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case reopened following overturned challenge.",
    ),
    # 22. UPHELD -> REOPENED
    TransitionRule(
        from_state="UPHELD",
        to_state="REOPENED",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
            UserRole.OFFICER.value,
        },
        activity_type="CASE_REOPENED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case reopened following challenge review.",
    ),
    # 23. UPHELD -> CLOSED
    TransitionRule(
        from_state="UPHELD",
        to_state="CLOSED",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
            UserRole.OFFICER.value,
        },
        activity_type="CASE_CLOSED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case finalized and closed: resolution upheld.",
    ),
    # 24. OVERTURNED -> CLOSED
    TransitionRule(
        from_state="OVERTURNED",
        to_state="CLOSED",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
            UserRole.OFFICER.value,
        },
        activity_type="CASE_CLOSED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case finalized and closed.",
    ),
    # 25. REOPENED -> IN_PROGRESS
    TransitionRule(
        from_state="REOPENED",
        to_state="IN_PROGRESS",
        allowed_roles={
            UserRole.DEPARTMENT_LEAD.value,
            UserRole.OFFICER.value,
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
        },
        activity_type="WORK_RESUMED",
        visibility="CITIZEN_VISIBLE",
        default_message="Field remediation resumed on reopened case.",
    ),
    # 26. CHALLENGED -> REOPENED
    TransitionRule(
        from_state="CHALLENGED",
        to_state="REOPENED",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
            UserRole.OFFICER.value,
        },
        activity_type="CASE_REOPENED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case reopened following challenge review.",
    ),
    # 27. CHALLENGED -> CLOSED
    TransitionRule(
        from_state="CHALLENGED",
        to_state="CLOSED",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
            UserRole.OFFICER.value,
        },
        activity_type="CASE_CLOSED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case closed following challenge review.",
    ),
    # 28. UNDER_REVIEW -> REOPENED
    TransitionRule(
        from_state="UNDER_REVIEW",
        to_state="REOPENED",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
            UserRole.OFFICER.value,
        },
        activity_type="CASE_REOPENED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case reopened following challenge review.",
    ),
    # 29. UNDER_REVIEW -> CLOSED
    TransitionRule(
        from_state="UNDER_REVIEW",
        to_state="CLOSED",
        allowed_roles={
            UserRole.SUPERVISOR.value,
            UserRole.ADMIN.value,
            UserRole.OFFICER.value,
        },
        activity_type="CASE_CLOSED",
        visibility="CITIZEN_VISIBLE",
        default_message="Case closed following challenge review.",
    ),
]


class CaseStateMachine:
    """Central authority governing valid case status transitions and enforcing invariants."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.audit_service = AuditService(session)

    @classmethod
    def find_rule(cls, from_state: str, to_state: str) -> Optional[TransitionRule]:
        for r in ALLOWED_TRANSITIONS:
            if r.from_state == from_state and r.to_state == to_state:
                return r
        return None

    async def transition(
        self,
        case: Case,
        target_state: str,
        actor: User,
        reason: Optional[str] = None,
        department_id: Optional[uuid.UUID] = None,
        assigned_officer_id: Optional[uuid.UUID] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Case:
        """Executes validated transition with atomic side-effects: DB mutation, audit chain, case activity, outbox."""
        current_state = case.status
        target_state = target_state.upper()

        # 1. Validate transition existence
        rule = self.find_rule(current_state, target_state)
        if not rule:
            raise BadRequestError(
                f"Illegal state transition from '{current_state}' to '{target_state}'.",
                code="ILLEGAL_TRANSITION",
            )

        # 2. Validate role authorization
        if actor.role not in rule.allowed_roles:
            raise ForbiddenError(
                f"Role '{actor.role}' is not authorized to transition case from '{current_state}' to '{target_state}'.",
                code="ROLE_NOT_PERMITTED",
            )

        # 3. Validate mandatory inputs per transition
        if target_state == "REJECTED_WITH_REASON":
            if not reason or len(reason.strip()) < 5:
                raise BadRequestError(
                    "Rejection requires a substantive justification note of at least 5 characters.",
                    code="REJECTION_REASON_REQUIRED",
                )

        if target_state == "ROUTED":
            # Department ID must either be provided or case must already have a lead department
            target_dept_id = department_id or case.lead_department_id
            if not target_dept_id:
                raise BadRequestError(
                    "Transition to ROUTED requires a target lead department.",
                    code="LEAD_DEPARTMENT_REQUIRED",
                )
            case.lead_department_id = target_dept_id

        if target_state == "IN_PROGRESS":
            target_officer_id = assigned_officer_id or case.assigned_officer_id
            if not target_officer_id:
                raise BadRequestError(
                    "Transition to IN_PROGRESS requires an assigned officer.",
                    code="OFFICER_ASSIGNMENT_REQUIRED",
                )
            case.assigned_officer_id = target_officer_id

        if target_state == "REASSIGN_REQUESTED":
            if not reason or len(reason.strip()) < 5:
                raise BadRequestError(
                    "Reassignment request requires a substantive justification of at least 5 characters.",
                    code="REASSIGN_REASON_REQUIRED",
                )
            evidence_urls = None
            if metadata and isinstance(metadata.get("evidence_urls"), list):
                evidence_urls = metadata["evidence_urls"]
            # Record reassign request record
            reassign_req = CaseReassignRequest(
                case_id=case.id,
                requested_by_id=actor.id,
                current_department_id=case.lead_department_id or uuid.uuid4(),
                suggested_department_id=department_id,
                reason=reason.strip(),
                evidence_urls=evidence_urls,
                status="PENDING",
            )
            self.session.add(reassign_req)

            # Also add citizen-visible notice without leaking internal reasoning
            citizen_activity = CaseActivity(
                case_id=case.id,
                actor_id=actor.id,
                activity_type="ROUTING_UNDER_REVIEW",
                visibility="CITIZEN_VISIBLE",
                message="Routing is currently under review by municipal supervisors.",
                activity_metadata={"status": "REASSIGN_REQUESTED"},
            )
            self.session.add(citizen_activity)

        if target_state == "RESOLUTION_PROPOSED":
            from sqlalchemy import desc, select

            from app.modules.challenges.models.challenge import ResolutionProposal
            from app.modules.complaints.models.complaint import Attachment

            stmt_p = (
                select(ResolutionProposal)
                .where(ResolutionProposal.case_id == case.id)
                .order_by(desc(ResolutionProposal.created_at))
                .limit(1)
            )
            res_p = await self.session.execute(stmt_p)
            proposal = res_p.scalar_one_or_none()
            if not proposal or not proposal.officer_verified:
                raise BadRequestError(
                    "Transition to RESOLUTION_PROPOSED requires a verified resolution proposal.",
                    code="EVIDENCE_REQUIRED",
                )
            stmt_att = select(Attachment).where(Attachment.resolution_proposal_id == proposal.id)
            res_att = await self.session.execute(stmt_att)
            if not list(res_att.scalars().all()):
                raise BadRequestError(
                    "Resolution proposal requires at least one evidence attachment.",
                    code="EVIDENCE_REQUIRED",
                )

        if target_state == "CLOSED":
            from sqlalchemy import desc, select

            from app.modules.challenges.models.challenge import ResolutionProposal
            from app.modules.complaints.models.complaint import Attachment

            stmt_p = (
                select(ResolutionProposal)
                .where(ResolutionProposal.case_id == case.id)
                .order_by(desc(ResolutionProposal.created_at))
                .limit(1)
            )
            res_p = await self.session.execute(stmt_p)
            proposal = res_p.scalar_one_or_none()
            if not proposal or not proposal.officer_verified:
                raise BadRequestError(
                    "Case cannot be closed without verified remediation evidence.",
                    code="EVIDENCE_REQUIRED",
                )
            stmt_att = select(Attachment).where(Attachment.resolution_proposal_id == proposal.id)
            res_att = await self.session.execute(stmt_att)
            if not list(res_att.scalars().all()):
                raise BadRequestError(
                    "Case cannot be closed without at least one verified evidence attachment.",
                    code="EVIDENCE_REQUIRED",
                )

        if target_state == "CHALLENGED":
            if not reason or len(reason.strip()) < 5:
                raise BadRequestError(
                    "Filing a challenge requires a substantive justification note of at least 5 characters.",
                    code="CHALLENGE_REASON_REQUIRED",
                )

        # 4. Mutate Case State
        from app.core.chaos import chaos_manager

        chaos_manager.check_db_error("case.transition")

        case.status = target_state
        await self.session.flush()

        # Update linked complaints status if applicable
        for cc in case.case_complaints:
            if cc.complaint:
                cc.complaint.status = target_state

        # 5. Append immutable Audit Event
        activity_msg = reason.strip() if (reason and reason.strip()) else rule.default_message
        await self.audit_service.record_event(
            entity_type="case",
            entity_id=case.id,
            action=f"case.{target_state.lower()}",
            actor_id=actor.id,
            actor_role=actor.role,
            old_state={"status": current_state},
            new_state={
                "status": target_state,
                "reason": reason,
                "lead_department_id": str(case.lead_department_id)
                if case.lead_department_id
                else None,
                "assigned_officer_id": str(case.assigned_officer_id)
                if case.assigned_officer_id
                else None,
            },
        )

        # 6. Append immutable Case Activity
        activity_meta = metadata or {}
        if reason:
            activity_meta["reason"] = reason.strip()
        if department_id:
            activity_meta["department_id"] = str(department_id)
        if assigned_officer_id:
            activity_meta["assigned_officer_id"] = str(assigned_officer_id)

        activity_entry = CaseActivity(
            case_id=case.id,
            actor_id=actor.id,
            activity_type=rule.activity_type,
            visibility=rule.visibility,
            message=activity_msg,
            activity_metadata=activity_meta,
        )
        self.session.add(activity_entry)
        await self.session.flush()

        # 7. Enqueue Transactional Outbox Event in SAME transaction
        await enqueue_outbox_event(
            session=self.session,
            event_type=f"case.{target_state.lower()}",
            aggregate_type="case",
            aggregate_id=case.id,
            payload={
                "case_id": str(case.id),
                "case_number": case.case_number,
                "previous_status": current_state,
                "new_status": target_state,
                "actor_id": str(actor.id),
                "lead_department_id": str(case.lead_department_id)
                if case.lead_department_id
                else None,
            },
        )

        return case
