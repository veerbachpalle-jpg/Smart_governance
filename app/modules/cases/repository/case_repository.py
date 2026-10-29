import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import case, desc, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import decode_offset_cursor, encode_offset_cursor
from app.modules.cases.models.case import (
    Case,
    CaseComplaint,
    CaseDepartment,
    CaseReassignRequest,
)
from app.modules.cases.schemas.case import CaseFilterParams
from app.modules.complaints.models.complaint import Complaint, Ward
from app.modules.complaints.ranking import DEFAULT_SLA_HOURS, SEVERITY_WEIGHTS
from app.modules.identity.models.user import Department


@dataclass(frozen=True)
class RankedCaseRecord:
    case: Case
    upvote_count: int
    sla_urgency_points: int
    composite_score: int


class CaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_case(self, case: Case) -> Case:
        self.session.add(case)
        await self.session.flush()
        return case

    async def list_cases(
        self, params: CaseFilterParams
    ) -> tuple[list[RankedCaseRecord], Optional[str], bool, int]:
        now = datetime.now(timezone.utc)
        upvote_count = func.coalesce(
            select(func.sum(Complaint.upvote_count))
            .join(CaseComplaint, CaseComplaint.complaint_id == Complaint.id)
            .where(CaseComplaint.case_id == Case.id)
            .correlate(Case)
            .scalar_subquery(),
            0,
        ).label("upvote_count")
        severity_weight = case(
            (Case.priority == "CRITICAL", SEVERITY_WEIGHTS["CRITICAL"]),
            (Case.priority == "HIGH", SEVERITY_WEIGHTS["HIGH"]),
            (Case.priority == "LOW", SEVERITY_WEIGHTS["LOW"]),
            else_=SEVERITY_WEIGHTS["MEDIUM"],
        )

        def urgency(band: str) -> object:
            hours = DEFAULT_SLA_HOURS[band]
            return case(
                (Case.created_at <= now - timedelta(hours=hours), 9_999),
                (Case.created_at <= now - timedelta(hours=hours * 0.75), 7_500),
                (Case.created_at <= now - timedelta(hours=hours * 0.50), 5_000),
                (Case.created_at <= now - timedelta(hours=hours * 0.25), 2_500),
                else_=0,
            )

        sla_urgency = case(
            (Case.priority == "CRITICAL", urgency("CRITICAL")),
            (Case.priority == "HIGH", urgency("HIGH")),
            (Case.priority == "LOW", urgency("LOW")),
            else_=urgency("MEDIUM"),
        ).label("sla_urgency_points")
        composite_score = (
            severity_weight + upvote_count * 25 + sla_urgency
        ).label("composite_score")
        stmt = select(Case, upvote_count, sla_urgency, composite_score).options(
            selectinload(Case.departments).selectinload(CaseDepartment.department),
            selectinload(Case.case_complaints).selectinload(CaseComplaint.complaint),
            selectinload(Case.lead_department),
            selectinload(Case.assigned_officer),
        )
        if params.status:
            if params.status.lower() == "open":
                stmt = stmt.where(Case.status.notin_(("CLOSED", "RESOLVED")))
            else:
                stmt = stmt.where(Case.status == params.status.upper())
        if params.department_id:
            stmt = stmt.where(Case.lead_department_id == params.department_id)
        if params.department_name:
            stmt = stmt.where(
                exists(
                    select(Department.id).where(
                        Department.id == Case.lead_department_id,
                        func.lower(Department.name) == params.department_name.strip().lower(),
                    )
                )
            )
        if params.ward_id or params.ward_number is not None:
            ward_filter = (
                select(CaseComplaint.id)
                .join(Complaint, Complaint.id == CaseComplaint.complaint_id)
                .where(CaseComplaint.case_id == Case.id)
            )
            if params.ward_id:
                ward_filter = ward_filter.where(Complaint.ward_id == params.ward_id)
            if params.ward_number is not None:
                ward_filter = ward_filter.join(Ward, Ward.id == Complaint.ward_id).where(
                    Ward.ward_number == params.ward_number
                )
            stmt = stmt.where(exists(ward_filter))

        count_result = await self.session.execute(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )
        total_count = count_result.scalar_one() or 0
        offset = decode_offset_cursor(params.cursor) if params.cursor else 0
        if params.sort == "upvotes":
            stmt = stmt.order_by(
                upvote_count.desc(), composite_score.desc(), Case.created_at.asc()
            )
        elif params.sort == "recent":
            stmt = stmt.order_by(Case.created_at.desc(), Case.id.desc())
        else:
            stmt = stmt.order_by(composite_score.desc(), Case.created_at.asc(), Case.id.asc())
        result = await self.session.execute(stmt.offset(offset).limit(params.limit + 1))
        rows = list(result.all())
        has_more = len(rows) > params.limit
        records = [
            RankedCaseRecord(
                case=row[0],
                upvote_count=int(row[1]),
                sla_urgency_points=int(row[2]),
                composite_score=int(row[3]),
            )
            for row in rows[: params.limit]
        ]
        next_cursor = encode_offset_cursor(offset + params.limit) if has_more else None
        return records, next_cursor, has_more, total_count

    async def get_case_by_id(self, case_id: uuid.UUID) -> Optional[Case]:
        stmt = (
            select(Case)
            .options(
                selectinload(Case.departments).selectinload(CaseDepartment.department),
                selectinload(Case.case_complaints).selectinload(CaseComplaint.complaint),
                selectinload(Case.lead_department),
                selectinload(Case.assigned_officer),
            )
            .execution_options(populate_existing=True)
            .where(Case.id == case_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def get_case_for_complaint(self, complaint_id: uuid.UUID) -> Optional[Case]:
        stmt = (
            select(Case)
            .join(CaseComplaint, Case.id == CaseComplaint.case_id)
            .options(
                selectinload(Case.departments).selectinload(CaseDepartment.department),
                selectinload(Case.case_complaints).selectinload(CaseComplaint.complaint),
                selectinload(Case.lead_department),
                selectinload(Case.assigned_officer),
            )
            .where(CaseComplaint.complaint_id == complaint_id)
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def add_complaint_to_case(self, link: CaseComplaint) -> CaseComplaint:
        self.session.add(link)
        await self.session.flush()
        return link

    async def add_department(self, cd: CaseDepartment) -> CaseDepartment:
        self.session.add(cd)
        await self.session.flush()
        return cd

    async def get_department_membership(
        self, case_id: uuid.UUID, department_id: uuid.UUID
    ) -> Optional[CaseDepartment]:
        stmt = select(CaseDepartment).where(
            CaseDepartment.case_id == case_id,
            CaseDepartment.department_id == department_id,
        )
        res = await self.session.execute(stmt)
        return res.scalar_one_or_none()

    async def unset_current_lead(self, case_id: uuid.UUID) -> None:
        stmt = (
            update(CaseDepartment)
            .where(CaseDepartment.case_id == case_id, CaseDepartment.is_lead == True)  # noqa: E712
            .values(is_lead=False)
        )
        await self.session.execute(stmt)

    async def set_lead_department(self, case_id: uuid.UUID, department_id: uuid.UUID) -> None:
        # 1. Unset current lead
        await self.unset_current_lead(case_id)
        # 2. Set new lead
        cd = await self.get_department_membership(case_id, department_id)
        if cd:
            cd.is_lead = True
        else:
            cd = CaseDepartment(case_id=case_id, department_id=department_id, is_lead=True)
            self.session.add(cd)
        await self.session.flush()

    async def list_reassign_requests(self, case_id: uuid.UUID) -> list[CaseReassignRequest]:
        stmt = (
            select(CaseReassignRequest)
            .where(CaseReassignRequest.case_id == case_id)
            .order_by(desc(CaseReassignRequest.created_at))
        )
        res = await self.session.execute(stmt)
        return list(res.scalars().all())
