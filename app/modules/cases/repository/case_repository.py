import uuid
from typing import Optional

from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.cases.models.case import (
    Case,
    CaseComplaint,
    CaseDepartment,
    CaseReassignRequest,
)


class CaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_case(self, case: Case) -> Case:
        self.session.add(case)
        await self.session.flush()
        return case

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
