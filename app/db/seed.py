import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import async_session_factory
from app.modules.activity.models.activity import CaseActivity
from app.modules.cases.models.case import Case, CaseComplaint, CaseDepartment
from app.modules.challenges.models.challenge import CitizenChallenge, ResolutionProposal
from app.modules.complaints.models.complaint import Attachment, Complaint, Ward
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


SAMPLE_COMPLAINTS: list[dict[str, Any]] = [
    {
        "tracking_number": "GRV-DEMO-0001",
        "title": "Deep pothole beside the school crossing",
        "description": "A deep pothole has formed beside the zebra crossing on 12th Main Road and is forcing cyclists into traffic.",
        "address": "12th Main Road, Indiranagar",
        "latitude": 12.975,
        "longitude": 77.605,
        "ward_number": 1,
        "status": "SUBMITTED",
        "department": "ROADS",
        "priority": "HIGH",
    },
    {
        "tracking_number": "GRV-DEMO-0002",
        "title": "ಮಾರುಕಟ್ಟೆ ಬಳಿ drain overflow ಆಗುತ್ತಿದೆ",
        "description": "The drain near the market is overflowing after rain. ನೀರು footpath ಮೇಲೆ ಬರುತ್ತಿದೆ and pedestrians cannot pass safely.",
        "address": "Central Market Entrance, Bengaluru",
        "latitude": 12.969,
        "longitude": 77.601,
        "ward_number": 1,
        "status": "MANUAL_TRIAGE",
        "department": "DRAIN",
        "priority": "HIGH",
        "language": "kn",
    },
    {
        "tracking_number": "GRV-DEMO-0003",
        "title": "Streetlights dark on the park approach",
        "description": "Four consecutive streetlights are not working on the approach to the public park, leaving the road unsafe after sunset.",
        "address": "Park Road, Ward 4 East",
        "latitude": 12.982,
        "longitude": 77.642,
        "ward_number": 4,
        "status": "ROUTED",
        "department": "ELEC",
        "priority": "MEDIUM",
    },
    {
        "tracking_number": "GRV-DEMO-0004",
        "title": "Continuous drinking-water pipeline leak",
        "description": "A municipal supply pipe has been leaking continuously for two days and water is collecting along the carriageway.",
        "address": "CMH Road, Bengaluru",
        "latitude": 12.978,
        "longitude": 77.634,
        "ward_number": 4,
        "status": "IN_PROGRESS",
        "department": "WATER",
        "priority": "HIGH",
    },
    {
        "tracking_number": "GRV-DEMO-0005",
        "title": "Garbage accumulation behind community hall",
        "description": "The sanitation team reports that the accumulated waste was removed. This sample is awaiting citizen review of the proposed resolution.",
        "address": "Community Hall Lane, Ward 3 South",
        "latitude": 12.948,
        "longitude": 77.598,
        "ward_number": 3,
        "status": "CITIZEN_REVIEW",
        "department": "SAN",
        "priority": "MEDIUM",
        "proposal_status": "PROPOSED",
    },
    {
        "tracking_number": "GRV-DEMO-0006",
        "title": "Footpath repair left an open utility hole",
        "description": "The original repair was marked complete, but an open utility hole remains beside the repaired footpath. The citizen has challenged the resolution.",
        "address": "Old Airport Road, Bengaluru",
        "latitude": 12.955,
        "longitude": 77.634,
        "ward_number": 4,
        "status": "CHALLENGED",
        "department": "ROADS",
        "priority": "CRITICAL",
        "proposal_status": "CHALLENGED",
        "challenge": True,
    },
    {
        "tracking_number": "GRV-DEMO-0007",
        "title": "Hazardous branch removed from playground",
        "description": "A large broken branch over the playground was removed and the citizen accepted the verified resolution.",
        "address": "Neighbourhood Playground, Ward 2 North",
        "latitude": 13.018,
        "longitude": 77.601,
        "ward_number": 2,
        "status": "CLOSED",
        "department": "PARKS",
        "priority": "HIGH",
        "proposal_status": "ACCEPTED",
    },
    {
        "tracking_number": "GRV-DEMO-0008",
        "title": "Reopened sewage overflow complaint",
        "description": "The blockage returned after the first intervention, so the supervisor reopened the case for a permanent repair.",
        "address": "West Cross Street, Ward 5 West",
        "latitude": 12.981,
        "longitude": 77.565,
        "ward_number": 5,
        "status": "REOPENED",
        "department": "DRAIN",
        "priority": "CRITICAL",
    },
]


async def seed_sample_workflows(
    session: Any,
    citizen: User,
    officer: User,
    supervisor: User,
    departments: dict[str, Department],
    wards: dict[int, Ward],
) -> None:
    """Create repeatable, non-sensitive records spanning the complete demo lifecycle."""
    now = datetime.now(timezone.utc)
    for index, data in enumerate(SAMPLE_COMPLAINTS, start=1):
        tracking_number = str(data["tracking_number"])
        result = await session.execute(
            select(Complaint).where(Complaint.tracking_number == tracking_number)
        )
        complaint = result.scalar_one_or_none()
        if complaint is None:
            ward = wards[int(data["ward_number"])]
            complaint = Complaint(
                tracking_number=tracking_number,
                citizen_id=citizen.id,
                original_title=str(data["title"]),
                original_description=str(data["description"]),
                original_language=str(data.get("language", "en")),
                latitude=float(data["latitude"]),
                longitude=float(data["longitude"]),
                address=str(data["address"]),
                ward_id=ward.id,
                ward_name=ward.name,
                channel="WEB",
                status=str(data["status"]),
                created_at=now - timedelta(days=10 - index),
                updated_at=now - timedelta(hours=index),
            )
            session.add(complaint)
            await session.flush()
            logger.info("Created sample complaint: %s", tracking_number)

        if data["status"] in {"SUBMITTED", "MANUAL_TRIAGE"}:
            continue

        case_number = f"CASE-DEMO-{index:04d}"
        case_result = await session.execute(select(Case).where(Case.case_number == case_number))
        case = case_result.scalar_one_or_none()
        if case is None:
            department = departments[str(data["department"])]
            case = Case(
                case_number=case_number,
                title=complaint.original_title,
                description=complaint.original_description,
                status=str(data["status"]),
                priority=str(data["priority"]),
                lead_department_id=department.id,
                assigned_officer_id=officer.id,
                created_by_id=supervisor.id,
            )
            session.add(case)
            await session.flush()
            session.add_all(
                [
                    CaseComplaint(case_id=case.id, complaint_id=complaint.id, is_primary=True),
                    CaseDepartment(
                        case_id=case.id,
                        department_id=department.id,
                        is_lead=True,
                        added_by_id=supervisor.id,
                    ),
                    CaseActivity(
                        case_id=case.id,
                        complaint_id=complaint.id,
                        actor_id=supervisor.id,
                        activity_type="CASE_CREATED",
                        visibility="CITIZEN_VISIBLE",
                        message=f"Case {case_number} created and assigned to {department.name}.",
                        activity_metadata={"tracking_number": tracking_number},
                        created_at=now - timedelta(days=5),
                    ),
                    CaseActivity(
                        case_id=case.id,
                        complaint_id=complaint.id,
                        actor_id=officer.id,
                        activity_type="STATUS_UPDATE",
                        visibility="CITIZEN_VISIBLE",
                        message=f"Current sample workflow status: {data['status']}.",
                        activity_metadata={"status": data["status"]},
                        created_at=now - timedelta(hours=index),
                    ),
                ]
            )
            await session.flush()
            logger.info("Created sample case: %s", case_number)

        proposal_status = data.get("proposal_status")
        if proposal_status:
            proposal_result = await session.execute(
                select(ResolutionProposal).where(ResolutionProposal.case_id == case.id)
            )
            proposal = proposal_result.scalar_one_or_none()
            if proposal is None:
                proposal = ResolutionProposal(
                    case_id=case.id,
                    proposing_officer_id=officer.id,
                    remediation_summary="Municipal crew completed the documented remediation shown in the sample evidence.",
                    root_cause_identified="Routine infrastructure wear and delayed preventive maintenance.",
                    officer_verified=True,
                    officer_verified_at=now - timedelta(days=1),
                    review_window_expires_at=now + timedelta(days=7),
                    status=str(proposal_status),
                )
                session.add(proposal)
                await session.flush()
                session.add(
                    Attachment(
                        case_id=case.id,
                        resolution_proposal_id=proposal.id,
                        uploader_id=officer.id,
                        file_url=f"seed://resolution/{tracking_number}.jpg",
                        file_name=f"{tracking_number.lower()}-resolution.jpg",
                        mime_type="image/jpeg",
                        file_size_bytes=1024,
                        sha256_hash="0" * 64,
                        attachment_type="RESOLUTION_EVIDENCE",
                    )
                )
                await session.flush()

            if data.get("challenge"):
                challenge_result = await session.execute(
                    select(CitizenChallenge).where(CitizenChallenge.case_id == case.id)
                )
                if challenge_result.scalar_one_or_none() is None:
                    session.add(
                        CitizenChallenge(
                            case_id=case.id,
                            resolution_proposal_id=proposal.id,
                            citizen_id=citizen.id,
                            challenge_type="RESOLUTION",
                            reason="The open utility hole remains unsafe despite the proposed resolution.",
                            status="PENDING",
                            sla_expires_at=now + timedelta(hours=48),
                            is_escalated=False,
                        )
                    )
                    await session.flush()
                    logger.info("Created sample citizen challenge for: %s", tracking_number)


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

        existing_wards = await ward_repo.list_all()
        ward_map = {ward.ward_number: ward for ward in existing_wards}

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
        user_map: dict[str, User] = {}
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
                user_map[str(u["email"])] = created_user
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
                user_map[str(u["email"])] = existing_user
                logger.info("User already exists: %s", u["email"])

        await seed_sample_workflows(
            session=session,
            citizen=user_map["citizen@example.com"],
            officer=user_map["officer@example.com"],
            supervisor=user_map["supervisor@example.com"],
            departments=dept_map,
            wards=ward_map,
        )

        await session.commit()
    logger.info("Database seeding successfully completed.")


if __name__ == "__main__":
    asyncio.run(seed())
