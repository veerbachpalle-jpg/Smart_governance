import asyncio
import logging

from app.core.security import hash_password
from app.db.session import async_session_factory
from app.modules.complaints.models.complaint import Ward
from app.modules.complaints.repository.complaint_repository import WardRepository
from app.modules.identity.models.user import CitizenProfile, Department, DepartmentMember, User
from app.modules.identity.repository.identity_repository import (
    CitizenProfileRepository,
    DepartmentMemberRepository,
    DepartmentRepository,
    UserRepository,
)
from app.modules.identity.schemas.identity import UserRole

logger = logging.getLogger("seed")
logging.basicConfig(level=logging.INFO)

DEPARTMENTS_DATA = [
    {
        "code": "ROADS",
        "name": "Roads & Bridges",
        "description": "Maintenance of municipal streets, potholes, pavements, and flyovers.",
    },
    {
        "code": "WATER",
        "name": "Water Supply",
        "description": "Municipal potable water supply pipelines, leakage, and meter grievances.",
    },
    {
        "code": "ELEC",
        "name": "Electricity & Streetlights",
        "description": "Streetlight outages, exposed electrical wiring, and junction boxes.",
    },
    {
        "code": "SAN",
        "name": "Sanitation & Solid Waste",
        "description": "Garbage pickup, illegal dumping, street sweeping, and bins.",
    },
    {
        "code": "DRAIN",
        "name": "Stormwater & Drainage",
        "description": "Clogged stormwater drains, sewage overflow, and monsoon flooding.",
    },
    {
        "code": "PARKS",
        "name": "Parks & Horticulture",
        "description": "Public park maintenance, hazardous tree branches, and gardens.",
    },
]

DEMO_USERS = [
    {
        "email": "citizen@example.com",
        "phone": "+10000000001",
        "password": "CitizenDemo123!",
        "role": UserRole.CITIZEN.value,
        "full_name": "Jane Doe (Citizen)",
        "address": "42 Pine Street, Ward 12",
    },
    {
        "email": "officer@example.com",
        "phone": "+10000000002",
        "password": "OfficerDemo123!",
        "role": UserRole.OFFICER.value,
        "dept_code": "ROADS",
        "member_role": "officer",
    },
    {
        "email": "lead@example.com",
        "phone": "+10000000003",
        "password": "LeadDemo123!",
        "role": UserRole.DEPARTMENT_LEAD.value,
        "dept_code": "ROADS",
        "member_role": "lead",
    },
    {
        "email": "supervisor@example.com",
        "phone": "+10000000004",
        "password": "SupervisorDemo123!",
        "role": UserRole.SUPERVISOR.value,
    },
    {
        "email": "admin@example.com",
        "phone": "+10000000005",
        "password": "AdminDemo123!",
        "role": UserRole.ADMIN.value,
    },
    {
        "email": "auditor@example.com",
        "phone": "+10000000006",
        "password": "AuditorDemo123!",
        "role": UserRole.AUDITOR.value,
    },
]


WARDS_DATA = [
    {
        "ward_number": 1,
        "name": "Ward 1 - Central",
        "min_lat": 12.96,
        "max_lat": 13.00,
        "min_lon": 77.58,
        "max_lon": 77.62,
        "boundary_geojson": {
            "type": "Polygon",
            "coordinates": [
                [[77.58, 12.96], [77.62, 12.96], [77.62, 13.00], [77.58, 13.00], [77.58, 12.96]]
            ],
        },
    },
    {
        "ward_number": 2,
        "name": "Ward 2 - North",
        "min_lat": 13.00,
        "max_lat": 13.04,
        "min_lon": 77.58,
        "max_lon": 77.62,
        "boundary_geojson": {
            "type": "Polygon",
            "coordinates": [
                [[77.58, 13.00], [77.62, 13.00], [77.62, 13.04], [77.58, 13.04], [77.58, 13.00]]
            ],
        },
    },
    {
        "ward_number": 3,
        "name": "Ward 3 - South",
        "min_lat": 12.92,
        "max_lat": 12.96,
        "min_lon": 77.58,
        "max_lon": 77.62,
        "boundary_geojson": {
            "type": "Polygon",
            "coordinates": [
                [[77.58, 12.92], [77.62, 12.92], [77.62, 12.96], [77.58, 12.96], [77.58, 12.92]]
            ],
        },
    },
    {
        "ward_number": 4,
        "name": "Ward 4 - East",
        "min_lat": 12.96,
        "max_lat": 13.00,
        "min_lon": 77.62,
        "max_lon": 77.66,
        "boundary_geojson": {
            "type": "Polygon",
            "coordinates": [
                [[77.62, 12.96], [77.66, 12.96], [77.66, 13.00], [77.62, 13.00], [77.62, 12.96]]
            ],
        },
    },
    {
        "ward_number": 5,
        "name": "Ward 5 - West",
        "min_lat": 12.96,
        "max_lat": 13.00,
        "min_lon": 77.54,
        "max_lon": 77.58,
        "boundary_geojson": {
            "type": "Polygon",
            "coordinates": [
                [[77.54, 12.96], [77.58, 12.96], [77.58, 13.00], [77.54, 13.00], [77.54, 12.96]]
            ],
        },
    },
]


async def seed() -> None:
    logger.info("Starting database seeding...")
    async with async_session_factory() as session:
        user_repo = UserRepository(session)
        profile_repo = CitizenProfileRepository(session)
        dept_repo = DepartmentRepository(session)
        member_repo = DepartmentMemberRepository(session)
        ward_repo = WardRepository(session)

        # 0. Seed Wards
        existing_wards = await ward_repo.list_all()
        existing_ward_nums = {w.ward_number for w in existing_wards}
        for w in WARDS_DATA:
            if w["ward_number"] not in existing_ward_nums:
                ward = Ward(
                    ward_number=w["ward_number"],
                    name=w["name"],
                    boundary_geojson=w["boundary_geojson"],
                    min_lat=w["min_lat"],
                    max_lat=w["max_lat"],
                    min_lon=w["min_lon"],
                    max_lon=w["max_lon"],
                )
                await ward_repo.create(ward)
                logger.info("Created ward: %s", w["name"])
            else:
                logger.info("Ward already exists: %s", w["name"])

        # 1. Seed Departments
        dept_map: dict[str, Department] = {}
        for d in DEPARTMENTS_DATA:
            existing = await dept_repo.get_by_code(d["code"])
            if not existing:
                dept = Department(
                    code=d["code"],
                    name=d["name"],
                    description=d["description"],
                    is_active=True,
                )
                created = await dept_repo.create(dept)
                dept_map[d["code"]] = created
                logger.info("Created department: %s (%s)", d["name"], d["code"])
            else:
                dept_map[d["code"]] = existing
                logger.info("Department already exists: %s", d["code"])

        # 2. Seed Demo Users for each Role
        for u in DEMO_USERS:
            existing_user = (await user_repo.get_by_email(u["email"])) or (
                await user_repo.get_by_phone(u["phone"])
            )
            if not existing_user:
                hashed = hash_password(u["password"])
                user = User(
                    email=u["email"],
                    phone_number=u["phone"],
                    password_hash=hashed,
                    role=u["role"],
                    is_active=True,
                )
                created_user = await user_repo.create(user)
                logger.info("Created user: %s (role: %s)", u["email"], u["role"])

                # If citizen, seed profile
                if u["role"] == UserRole.CITIZEN.value:
                    profile = CitizenProfile(
                        user_id=created_user.id,
                        full_name=u["full_name"],
                        address=u["address"],
                        preferred_language="en",
                        notification_preference="email",
                    )
                    await profile_repo.create(profile)
                    logger.info("Created citizen profile for: %s", u["email"])

                # If officer or lead, associate with department
                if "dept_code" in u:
                    dept_code = str(u["dept_code"])
                    target_dept: Department | None = dept_map.get(dept_code)
                    if target_dept is not None:
                        membership = DepartmentMember(
                            department_id=target_dept.id,
                            user_id=created_user.id,
                            member_role=str(u["member_role"]),
                            is_active=True,
                        )
                        await member_repo.create(membership)
                        logger.info(
                            "Assigned %s to department %s as %s",
                            u["email"],
                            target_dept.code,
                            u["member_role"],
                        )
            else:
                logger.info("User already exists: %s", u["email"])

        await session.commit()
    logger.info("Database seeding successfully completed.")


if __name__ == "__main__":
    asyncio.run(seed())
