import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, cast

from sqlalchemy import case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.elements import ColumnElement

from app.core.pagination import decode_offset_cursor, encode_offset_cursor
from app.modules.cases.models.case import Case as GrievanceCase
from app.modules.cases.models.case import CaseComplaint
from app.modules.complaints.models.complaint import Attachment, Complaint, Ward
from app.modules.complaints.ranking import DEFAULT_SLA_HOURS, SEVERITY_WEIGHTS
from app.modules.complaints.schemas.complaint import ComplaintFilterParams
from app.modules.identity.models.user import Department
from app.modules.priority.models.priority import PriorityAssessment

OPEN_COMPLAINT_EXCLUDED_STATUSES = ("CLOSED", "RESOLVED", "REJECTED_WITH_REASON")


@dataclass(frozen=True)
class RankedComplaintRecord:
    complaint: Complaint
    priority_band: str
    suggested_sla_hours: int
    sla_urgency_points: int
    composite_score: int
    department_id: uuid.UUID | None
    department_name: str | None
    ward_number: int | None


class WardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> Sequence[Ward]:
        stmt = select(Ward).order_by(Ward.ward_number.asc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def get_by_id(self, ward_id: uuid.UUID) -> Optional[Ward]:
        stmt = select(Ward).where(Ward.id == ward_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_number(self, ward_number: int) -> Optional[Ward]:
        stmt = select(Ward).where(Ward.ward_number == ward_number)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, ward: Ward) -> Ward:
        self.session.add(ward)
        await self.session.flush()
        return ward


class AttachmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, attachment: Attachment) -> Attachment:
        self.session.add(attachment)
        await self.session.flush()
        return attachment

    async def get_by_id(self, attachment_id: uuid.UUID) -> Optional[Attachment]:
        stmt = select(Attachment).where(Attachment.id == attachment_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_ids(self, attachment_ids: list[uuid.UUID]) -> Sequence[Attachment]:
        if not attachment_ids:
            return []
        stmt = select(Attachment).where(Attachment.id.in_(attachment_ids))
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def list_by_complaint(self, complaint_id: uuid.UUID) -> Sequence[Attachment]:
        stmt = (
            select(Attachment)
            .where(Attachment.complaint_id == complaint_id)
            .order_by(Attachment.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()


class ComplaintRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, complaint: Complaint) -> Complaint:
        self.session.add(complaint)
        await self.session.flush()
        return complaint

    async def get_by_id(self, complaint_id: uuid.UUID) -> Optional[Complaint]:
        stmt = (
            select(Complaint)
            .options(selectinload(Complaint.attachments))
            .where(Complaint.id == complaint_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id_for_update(self, complaint_id: uuid.UUID) -> Optional[Complaint]:
        stmt = select(Complaint).where(Complaint.id == complaint_id).with_for_update()
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_tracking_number(self, tracking_number: str) -> Optional[Complaint]:
        stmt = (
            select(Complaint)
            .options(selectinload(Complaint.attachments))
            .where(Complaint.tracking_number == tracking_number.strip().upper())
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest_by_citizen(self, citizen_id: uuid.UUID) -> Optional[Complaint]:
        stmt = (
            select(Complaint)
            .where(Complaint.citizen_id == citizen_id)
            .order_by(Complaint.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _ranking_expressions(
        now: datetime,
    ) -> tuple[
        ColumnElement[Any],
        ColumnElement[Any],
        ColumnElement[Any],
        ColumnElement[Any],
        ColumnElement[Any],
        ColumnElement[Any],
        ColumnElement[Any],
    ]:
        latest_priority = (
            select(PriorityAssessment.final_suggested_priority)
            .where(PriorityAssessment.complaint_id == Complaint.id)
            .order_by(PriorityAssessment.created_at.desc())
            .limit(1)
            .correlate(Complaint)
            .scalar_subquery()
        )
        latest_sla_hours = (
            select(PriorityAssessment.suggested_sla_hours)
            .where(PriorityAssessment.complaint_id == Complaint.id)
            .order_by(PriorityAssessment.created_at.desc())
            .limit(1)
            .correlate(Complaint)
            .scalar_subquery()
        )
        linked_case_priority = (
            select(GrievanceCase.priority)
            .join(CaseComplaint, CaseComplaint.case_id == GrievanceCase.id)
            .where(CaseComplaint.complaint_id == Complaint.id)
            .limit(1)
            .correlate(Complaint)
            .scalar_subquery()
        )
        priority_band = func.coalesce(
            latest_priority, linked_case_priority, "MEDIUM"
        ).label("priority_band")
        suggested_sla_hours = func.coalesce(
            latest_sla_hours,
            case(
                (priority_band == "CRITICAL", DEFAULT_SLA_HOURS["CRITICAL"]),
                (priority_band == "HIGH", DEFAULT_SLA_HOURS["HIGH"]),
                (priority_band == "LOW", DEFAULT_SLA_HOURS["LOW"]),
                else_=DEFAULT_SLA_HOURS["MEDIUM"],
            ),
        ).label("suggested_sla_hours")
        severity_weight = case(
            (priority_band == "CRITICAL", SEVERITY_WEIGHTS["CRITICAL"]),
            (priority_band == "HIGH", SEVERITY_WEIGHTS["HIGH"]),
            (priority_band == "LOW", SEVERITY_WEIGHTS["LOW"]),
            else_=SEVERITY_WEIGHTS["MEDIUM"],
        )

        def urgency_for_band(band: str) -> ColumnElement[Any]:
            sla = DEFAULT_SLA_HOURS[band]
            return case(
                (Complaint.created_at <= now - timedelta(hours=sla), 9_999),
                (Complaint.created_at <= now - timedelta(hours=sla * 0.75), 7_500),
                (Complaint.created_at <= now - timedelta(hours=sla * 0.50), 5_000),
                (Complaint.created_at <= now - timedelta(hours=sla * 0.25), 2_500),
                else_=0,
            )

        sla_urgency = case(
            (priority_band == "CRITICAL", urgency_for_band("CRITICAL")),
            (priority_band == "HIGH", urgency_for_band("HIGH")),
            (priority_band == "LOW", urgency_for_band("LOW")),
            else_=urgency_for_band("MEDIUM"),
        ).label("sla_urgency_points")
        composite_score = (
            severity_weight + Complaint.upvote_count * 25 + sla_urgency
        ).label("composite_score")
        department_id = (
            select(GrievanceCase.lead_department_id)
            .join(CaseComplaint, CaseComplaint.case_id == GrievanceCase.id)
            .where(CaseComplaint.complaint_id == Complaint.id)
            .limit(1)
            .correlate(Complaint)
            .scalar_subquery()
            .label("department_id")
        )
        department_name = (
            select(Department.name)
            .join(GrievanceCase, GrievanceCase.lead_department_id == Department.id)
            .join(CaseComplaint, CaseComplaint.case_id == GrievanceCase.id)
            .where(CaseComplaint.complaint_id == Complaint.id)
            .limit(1)
            .correlate(Complaint)
            .scalar_subquery()
            .label("department_name")
        )
        ward_number = (
            select(Ward.ward_number)
            .where(Ward.id == Complaint.ward_id)
            .correlate(Complaint)
            .scalar_subquery()
            .label("ward_number")
        )
        return (
            priority_band,
            suggested_sla_hours,
            sla_urgency,
            composite_score,
            department_id,
            department_name,
            ward_number,
        )

    async def list_complaints(
        self,
        citizen_id: Optional[uuid.UUID],
        params: ComplaintFilterParams,
    ) -> tuple[list[RankedComplaintRecord], Optional[str], bool, int]:
        now = datetime.now(timezone.utc)
        expressions = self._ranking_expressions(now)
        priority_band, _, _, composite_score, _, _, _ = expressions
        stmt = select(Complaint, *expressions).options(selectinload(Complaint.attachments))

        if citizen_id is not None:
            stmt = stmt.where(Complaint.citizen_id == citizen_id)
        if params.status:
            if params.status.strip().lower() == "open":
                stmt = stmt.where(Complaint.status.notin_(OPEN_COMPLAINT_EXCLUDED_STATUSES))
            else:
                stmt = stmt.where(Complaint.status == params.status.strip().upper())
        if params.ward_id:
            stmt = stmt.where(Complaint.ward_id == params.ward_id)
        if params.ward_number is not None:
            stmt = stmt.where(
                exists(
                    select(Ward.id).where(
                        Ward.id == Complaint.ward_id,
                        Ward.ward_number == params.ward_number,
                    )
                )
            )
        if params.ward_name:
            stmt = stmt.where(Complaint.ward_name == params.ward_name.strip())
        if params.department_id or params.department_name:
            department_filter = (
                select(CaseComplaint.id)
                .join(GrievanceCase, GrievanceCase.id == CaseComplaint.case_id)
                .join(Department, Department.id == GrievanceCase.lead_department_id)
                .where(CaseComplaint.complaint_id == Complaint.id)
            )
            if params.department_id:
                department_filter = department_filter.where(
                    GrievanceCase.lead_department_id == params.department_id
                )
            if params.department_name:
                department_filter = department_filter.where(
                    func.lower(Department.name) == params.department_name.strip().lower()
                )
            stmt = stmt.where(exists(department_filter))
        if params.start_time:
            stmt = stmt.where(Complaint.created_at >= params.start_time)
        if params.end_time:
            stmt = stmt.where(Complaint.created_at <= params.end_time)

        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        count_res = await self.session.execute(count_stmt)
        total_count = count_res.scalar_one() or 0
        offset = decode_offset_cursor(params.cursor) if params.cursor else 0

        if params.sort == "upvotes":
            stmt = stmt.order_by(
                Complaint.upvote_count.desc(), composite_score.desc(), Complaint.created_at.asc()
            )
        elif params.sort == "recent":
            stmt = stmt.order_by(Complaint.created_at.desc(), Complaint.id.desc())
        else:
            stmt = stmt.order_by(
                composite_score.desc(), Complaint.created_at.asc(), Complaint.id.asc()
            )
        stmt = stmt.offset(offset).limit(params.limit + 1)

        result = await self.session.execute(stmt)
        rows = list(result.all())
        has_more = len(rows) > params.limit
        page_rows = [cast(tuple[Any, ...], tuple(row)) for row in rows[: params.limit]]
        items = [
            RankedComplaintRecord(
                complaint=row[0],
                priority_band=str(row[1]),
                suggested_sla_hours=int(row[2]),
                sla_urgency_points=int(row[3]),
                composite_score=int(row[4]),
                department_id=row[5],
                department_name=row[6],
                ward_number=row[7],
            )
            for row in page_rows
        ]
        next_cursor = encode_offset_cursor(offset + params.limit) if has_more else None
        return items, next_cursor, has_more, total_count

    async def list_open_nearby_candidates(
        self,
        latitude: float,
        longitude: float,
        radius_meters: float,
    ) -> list[RankedComplaintRecord]:
        latitude_delta = radius_meters / 111_320.0
        longitude_scale = max(0.1, abs(math.cos(math.radians(latitude))))
        longitude_delta = radius_meters / (111_320.0 * float(longitude_scale))
        expressions = self._ranking_expressions(datetime.now(timezone.utc))
        composite_score = expressions[3]
        stmt = (
            select(Complaint, *expressions)
            .options(selectinload(Complaint.attachments))
            .where(
                Complaint.status.notin_(OPEN_COMPLAINT_EXCLUDED_STATUSES),
                Complaint.latitude.between(
                    latitude - latitude_delta, latitude + latitude_delta
                ),
                Complaint.longitude.between(
                    longitude - longitude_delta, longitude + longitude_delta
                ),
            )
            .order_by(
                Complaint.upvote_count.desc(),
                composite_score.desc(),
                Complaint.created_at.asc(),
            )
            .limit(100)
        )
        result = await self.session.execute(stmt)
        rows = [cast(tuple[Any, ...], tuple(row)) for row in result.all()]
        return [
            RankedComplaintRecord(
                complaint=row[0],
                priority_band=str(row[1]),
                suggested_sla_hours=int(row[2]),
                sla_urgency_points=int(row[3]),
                composite_score=int(row[4]),
                department_id=row[5],
                department_name=row[6],
                ward_number=row[7],
            )
            for row in rows
        ]
