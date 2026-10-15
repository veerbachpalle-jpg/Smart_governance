import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.modules.activity.models.activity import CaseActivity, CitizenUpdate
from app.modules.activity.repository.activity_repository import ActivityRepository
from app.modules.activity.schemas.activity import (
    AddActivityRequest,
    CaseActivityResponse,
    CitizenTimelineItem,
    CitizenUpdateRequest,
)
from app.modules.audit.service.audit_service import AuditService
from app.modules.cases.repository.case_repository import CaseRepository
from app.modules.complaints.repository.complaint_repository import ComplaintRepository
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

logger = logging.getLogger("app.activity.service")


class ActivityService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ActivityRepository(session)
        self.case_repo = CaseRepository(session)
        self.complaint_repo = ComplaintRepository(session)
        self.audit_service = AuditService(session)

    async def add_activity(
        self, current_user: User, case_id: uuid.UUID, payload: AddActivityRequest
    ) -> CaseActivityResponse:
        case = await self.case_repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        activity = CaseActivity(
            case_id=case.id,
            actor_id=current_user.id,
            activity_type=payload.activity_type,
            visibility=payload.visibility,
            message=payload.message,
            activity_metadata=payload.metadata or {},
        )
        created = await self.repo.create_activity(activity)

        await self.audit_service.record_event(
            entity_type="case_activity",
            entity_id=created.id,
            action="case.activity_recorded",
            actor_id=current_user.id,
            actor_role=current_user.role,
            new_state={
                "case_id": str(case.id),
                "activity_type": payload.activity_type,
                "visibility": payload.visibility,
            },
        )
        return CaseActivityResponse.model_validate(created)

    async def publish_citizen_update(
        self, current_user: User, case_id: uuid.UUID, payload: CitizenUpdateRequest
    ) -> CaseActivityResponse:
        case = await self.case_repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        # 1. Record CitizenUpdate
        update_record = CitizenUpdate(
            case_id=case.id,
            author_id=current_user.id,
            title=payload.title,
            message=payload.message,
        )
        await self.repo.create_citizen_update(update_record)

        # 2. Append official CITIZEN_VISIBLE activity
        activity = CaseActivity(
            case_id=case.id,
            actor_id=current_user.id,
            activity_type="CITIZEN_UPDATE",
            visibility="CITIZEN_VISIBLE",
            message=f"{payload.title}: {payload.message}",
            activity_metadata={"title": payload.title},
        )
        created = await self.repo.create_activity(activity)

        await self.audit_service.record_event(
            entity_type="citizen_update",
            entity_id=update_record.id,
            action="citizen_update.published",
            actor_id=current_user.id,
            actor_role=current_user.role,
            new_state={"case_id": str(case.id), "title": payload.title},
        )
        return CaseActivityResponse.model_validate(created)

    async def list_activities_for_staff(
        self, current_user: User, case_id: uuid.UUID
    ) -> list[CaseActivityResponse]:
        case = await self.case_repo.get_case_by_id(case_id)
        if not case:
            raise NotFoundError(f"Case '{case_id}' not found.", code="CASE_NOT_FOUND")

        # Staff gets both internal and citizen-visible
        activities = await self.repo.list_activities(case_id)
        return [CaseActivityResponse.model_validate(a) for a in activities]

    async def get_citizen_timeline(
        self, current_user: User, complaint_id: uuid.UUID
    ) -> list[CitizenTimelineItem]:
        """Returns ONLY CITIZEN_VISIBLE activities for the citizen's own complaints."""
        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if not complaint:
            raise NotFoundError(
                f"Complaint '{complaint_id}' not found.", code="COMPLAINT_NOT_FOUND"
            )

        # Authorization check: citizens can only view their own complaint timeline
        if current_user.role == UserRole.CITIZEN.value and complaint.citizen_id != current_user.id:
            raise ForbiddenError(
                "Citizens are strictly prohibited from viewing activity history of other citizens' complaints.",
                code="CITIZEN_UNAUTHORIZED_COMPLAINT_ACCESS",
            )

        case = await self.case_repo.get_case_for_complaint(complaint.id)
        if not case:
            return []

        # STRICT INVARIANT: Query ONLY CITIZEN_VISIBLE entries
        activities = await self.repo.list_citizen_timeline(case.id)

        items: list[CitizenTimelineItem] = []
        lead_dept_name = case.lead_department.name if case.lead_department else complaint.ward_name

        for a in activities:
            # Absolute security check: discard any INTERNAL entry
            if a.visibility != "CITIZEN_VISIBLE":
                continue

            items.append(
                CitizenTimelineItem(
                    id=a.id,
                    time=a.created_at,
                    status=case.status,
                    department=lead_dept_name,
                    message=a.message,
                    activity_type=a.activity_type,
                )
            )

        return items
