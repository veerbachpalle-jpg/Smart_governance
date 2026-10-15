import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.core.outbox import enqueue_outbox_event
from app.modules.activity.models.activity import CaseActivity
from app.modules.audit.service.audit_service import AuditService
from app.modules.cases.models.case import Case, CaseComplaint, CaseDepartment
from app.modules.cases.repository.case_repository import CaseRepository
from app.modules.cases.schemas.case import (
    AddDepartmentRequest,
    AssignOfficerRequest,
    CaseDepartmentResponse,
    CaseResponse,
    CreateCaseRequest,
    LinkComplaintRequest,
    ReassignCaseRequest,
    SetLeadDepartmentRequest,
    TransitionCaseRequest,
)
from app.modules.cases.service.state_machine import CaseStateMachine
from app.modules.complaints.repository.complaint_repository import ComplaintRepository
from app.modules.identity.models.user import Department, User

logger = logging.getLogger("app.cases.service")


class CaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = CaseRepository(session)
        self.complaint_repo = ComplaintRepository(session)
        self.audit_service = AuditService(session)
        self.state_machine = CaseStateMachine(session)

    def _build_response(self, case: Case) -> CaseResponse:
        depts_resp = [
            CaseDepartmentResponse(
                id=d.id,
                department_id=d.department_id,
                department_name=d.department.name if d.department else "Unknown Department",
                is_lead=d.is_lead,
                added_at=d.added_at,
            )
            for d in case.departments
        ]
        complaint_ids = [cc.complaint_id for cc in case.case_complaints]

        return CaseResponse(
            id=case.id,
            case_number=case.case_number,
            title=case.title,
            description=case.description,
            status=case.status,
            priority=case.priority,
            lead_department_id=case.lead_department_id,
            assigned_officer_id=case.assigned_officer_id,
            created_at=case.created_at,
            updated_at=case.updated_at,
            departments=depts_resp,
            complaint_ids=complaint_ids,
        )

    async def create_case_from_complaint(
        self, current_user: User, payload: CreateCaseRequest
    ) -> CaseResponse:
        complaint = await self.complaint_repo.get_by_id(payload.complaint_id)
        if not complaint:
            raise NotFoundError(
                f"Complaint '{payload.complaint_id}' not found.", code="COMPLAINT_NOT_FOUND"
            )

        # Check if complaint is already linked to an existing case
        existing_case = await self.repo.get_case_for_complaint(complaint.id)
        if existing_case:
            raise ConflictError(
                f"Complaint '{complaint.id}' is already linked to case '{existing_case.case_number}'.",
                code="COMPLAINT_ALREADY_LINKED",
            )

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y%m%d")
        case_number = f"CASE-{date_str}-{uuid.uuid4().hex[:6].upper()}"

        title = payload.title or f"Case: {complaint.original_title}"
        description = payload.description or complaint.original_description
        status = (
            complaint.status if complaint.status in {"TRIAGE_REVIEW", "ROUTED"} else "TRIAGE_REVIEW"
        )

        case = Case(
            case_number=case_number,
            title=title,
            description=description,
            status=status,
            priority="MEDIUM",
            created_by_id=current_user.id,
        )
        created_case = await self.repo.create_case(case)

        # Link primary complaint
        link = CaseComplaint(
            case_id=created_case.id,
            complaint_id=complaint.id,
            is_primary=True,
            linked_at=now,
        )
        await self.repo.add_complaint_to_case(link)

        # Append immutable Audit Event
        await self.audit_service.record_event(
            entity_type="case",
            entity_id=created_case.id,
            action="case.created",
            actor_id=current_user.id,
            actor_role=current_user.role,
            new_state={
                "case_number": case_number,
                "primary_complaint_id": str(complaint.id),
                "status": status,
            },
        )

        # Append immutable Case Activity
        activity = CaseActivity(
            case_id=created_case.id,
            complaint_id=complaint.id,
            actor_id=current_user.id,
            activity_type="CASE_CREATED",
            visibility="CITIZEN_VISIBLE",
            message=f"Case {case_number} initialized from complaint {complaint.tracking_number}.",
            activity_metadata={"tracking_number": complaint.tracking_number},
        )
        self.session.add(activity)

        # Enqueue Outbox Event
        await enqueue_outbox_event(
            session=self.session,
            event_type="case.created",
            aggregate_type="case",
            aggregate_id=created_case.id,
            payload={
                "case_id": str(created_case.id),
                "case_number": case_number,
                "complaint_id": str(complaint.id),
            },
        )

        # Refresh for relations
        full_case = await self.repo.get_case_by_id(created_case.id)
        assert full_case is not None
        return self._build_response(full_case)

    async def link_complaint(
        self, current_user: User, case_id: uuid.UUID, payload: LinkComplaintRequest
    ) -> CaseResponse:
        case = await self.repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        complaint = await self.complaint_repo.get_by_id(payload.complaint_id)
        if not complaint:
            raise NotFoundError(
                f"Complaint '{payload.complaint_id}' not found.", code="COMPLAINT_NOT_FOUND"
            )

        existing = await self.repo.get_case_for_complaint(complaint.id)
        if existing:
            raise ConflictError(
                f"Complaint '{complaint.id}' is already linked to case '{existing.case_number}'.",
                code="COMPLAINT_ALREADY_LINKED",
            )

        link = CaseComplaint(
            case_id=case.id,
            complaint_id=complaint.id,
            is_primary=payload.is_primary,
        )
        await self.repo.add_complaint_to_case(link)

        # Keep complaint status in sync
        complaint.status = case.status

        await self.audit_service.record_event(
            entity_type="case",
            entity_id=case.id,
            action="case.complaint_linked",
            actor_id=current_user.id,
            actor_role=current_user.role,
            new_state={"linked_complaint_id": str(complaint.id), "is_primary": payload.is_primary},
        )

        activity = CaseActivity(
            case_id=case.id,
            complaint_id=complaint.id,
            actor_id=current_user.id,
            activity_type="COMPLAINT_LINKED",
            visibility="CITIZEN_VISIBLE",
            message=f"Complaint {complaint.tracking_number} grouped under case {case.case_number}.",
            activity_metadata={"tracking_number": complaint.tracking_number},
        )
        self.session.add(activity)
        await self.session.flush()

        full_case = await self.repo.get_case_by_id(case_id)
        assert full_case is not None
        return self._build_response(full_case)

    async def add_department(
        self, current_user: User, case_id: uuid.UUID, payload: AddDepartmentRequest
    ) -> CaseResponse:
        case = await self.repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        dept = await self.session.get(Department, payload.department_id)
        if not dept:
            raise NotFoundError(
                f"Department '{payload.department_id}' not found.", code="DEPT_NOT_FOUND"
            )

        existing_membership = await self.repo.get_department_membership(
            case.id, payload.department_id
        )
        if existing_membership:
            if payload.is_lead and not existing_membership.is_lead:
                for d in case.departments:
                    d.is_lead = False
                await self.repo.unset_current_lead(case.id)
                existing_membership.is_lead = True
                case.lead_department_id = payload.department_id
                await self.session.flush()
        else:
            if payload.is_lead:
                for d in case.departments:
                    d.is_lead = False
                await self.repo.unset_current_lead(case.id)
                case.lead_department_id = payload.department_id
            cd = CaseDepartment(
                case_id=case.id,
                department_id=payload.department_id,
                is_lead=payload.is_lead,
                added_by_id=current_user.id,
            )
            cd.department = dept
            await self.repo.add_department(cd)
            case.departments.append(cd)

        await self.audit_service.record_event(
            entity_type="case",
            entity_id=case.id,
            action="case.department_added",
            actor_id=current_user.id,
            actor_role=current_user.role,
            new_state={
                "department_id": str(payload.department_id),
                "is_lead": payload.is_lead,
            },
        )

        activity = CaseActivity(
            case_id=case.id,
            actor_id=current_user.id,
            activity_type="DEPARTMENT_ASSIGNED",
            visibility="CITIZEN_VISIBLE",
            message=f"Department assigned to case (is_lead={payload.is_lead}).",
            activity_metadata={
                "department_id": str(payload.department_id),
                "is_lead": payload.is_lead,
            },
        )
        self.session.add(activity)
        await self.session.flush()

        return self._build_response(case)

    async def set_lead_department(
        self, current_user: User, case_id: uuid.UUID, payload: SetLeadDepartmentRequest
    ) -> CaseResponse:
        case = await self.repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        for d in case.departments:
            d.is_lead = d.department_id == payload.department_id

        await self.repo.set_lead_department(case.id, payload.department_id)
        case.lead_department_id = payload.department_id
        await self.session.flush()

        await self.audit_service.record_event(
            entity_type="case",
            entity_id=case.id,
            action="case.lead_department_set",
            actor_id=current_user.id,
            actor_role=current_user.role,
            new_state={"lead_department_id": str(payload.department_id)},
        )

        activity = CaseActivity(
            case_id=case.id,
            actor_id=current_user.id,
            activity_type="LEAD_DEPARTMENT_UPDATED",
            visibility="CITIZEN_VISIBLE",
            message=f"Accountable lead department updated for case {case.case_number}.",
            activity_metadata={"lead_department_id": str(payload.department_id)},
        )
        self.session.add(activity)
        await self.session.flush()

        full_case = await self.repo.get_case_by_id(case_id)
        assert full_case is not None
        return self._build_response(full_case)

    async def transition_case(
        self, current_user: User, case_id: uuid.UUID, payload: TransitionCaseRequest
    ) -> CaseResponse:
        case = await self.repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        updated_case = await self.state_machine.transition(
            case=case,
            target_state=payload.target_state,
            actor=current_user,
            reason=payload.reason,
            department_id=payload.department_id,
            assigned_officer_id=payload.assigned_officer_id,
        )

        full_case = await self.repo.get_case_by_id(updated_case.id)
        assert full_case is not None
        return self._build_response(full_case)

    async def assign_officer(
        self, current_user: User, case_id: uuid.UUID, payload: AssignOfficerRequest
    ) -> CaseResponse:
        case = await self.repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        case.assigned_officer_id = payload.officer_id

        # If currently ACCEPTED_BY_LEAD, advance to IN_PROGRESS
        if case.status == "ACCEPTED_BY_LEAD":
            await self.state_machine.transition(
                case=case,
                target_state="IN_PROGRESS",
                actor=current_user,
                assigned_officer_id=payload.officer_id,
                reason="Officer assigned and work commenced.",
            )
        else:
            await self.audit_service.record_event(
                entity_type="case",
                entity_id=case.id,
                action="case.officer_assigned",
                actor_id=current_user.id,
                actor_role=current_user.role,
                new_state={"assigned_officer_id": str(payload.officer_id)},
            )
            activity = CaseActivity(
                case_id=case.id,
                actor_id=current_user.id,
                activity_type="OFFICER_ASSIGNED",
                visibility="CITIZEN_VISIBLE",
                message="Field officer assigned to case.",
                activity_metadata={"assigned_officer_id": str(payload.officer_id)},
            )
            self.session.add(activity)

        full_case = await self.repo.get_case_by_id(case.id)
        assert full_case is not None
        return self._build_response(full_case)

    async def request_reassign(
        self, current_user: User, case_id: uuid.UUID, payload: ReassignCaseRequest
    ) -> CaseResponse:
        case = await self.repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        await self.state_machine.transition(
            case=case,
            target_state="REASSIGN_REQUESTED",
            actor=current_user,
            reason=payload.reason,
            department_id=payload.suggested_department_id,
        )

        full_case = await self.repo.get_case_by_id(case.id)
        assert full_case is not None
        return self._build_response(full_case)

    async def get_case(self, current_user: User, case_id: uuid.UUID) -> CaseResponse:
        case = await self.repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")
        return self._build_response(case)
