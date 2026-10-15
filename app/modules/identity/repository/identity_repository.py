import uuid
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.identity.models.user import CitizenProfile, Department, DepartmentMember, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        stmt = select(User).options(selectinload(User.citizen_profile)).where(User.id == user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> Optional[User]:
        stmt = (
            select(User)
            .options(selectinload(User.citizen_profile))
            .where(User.email == email.strip().lower())
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> Optional[User]:
        stmt = (
            select(User)
            .options(selectinload(User.citizen_profile))
            .where(User.phone_number == phone.strip())
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user


class CitizenProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, profile: CitizenProfile) -> CitizenProfile:
        self.session.add(profile)
        await self.session.flush()
        return profile


class DepartmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, dept_id: uuid.UUID) -> Optional[Department]:
        stmt = select(Department).where(Department.id == dept_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_code(self, code: str) -> Optional[Department]:
        stmt = select(Department).where(Department.code == code.strip().upper())
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[Department]:
        stmt = select(Department).order_by(Department.name.asc())
        result = await self.session.execute(stmt)
        return result.scalars().all()

    async def create(self, department: Department) -> Department:
        self.session.add(department)
        await self.session.flush()
        return department


class DepartmentMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, member: DepartmentMember) -> DepartmentMember:
        self.session.add(member)
        await self.session.flush()
        return member

    async def get_by_department(self, department_id: uuid.UUID) -> Sequence[DepartmentMember]:
        stmt = (
            select(DepartmentMember)
            .options(selectinload(DepartmentMember.user))
            .where(DepartmentMember.department_id == department_id)
        )
        result = await self.session.execute(stmt)
        return result.scalars().all()
