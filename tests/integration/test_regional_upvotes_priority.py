import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models.audit import AuditEvent
from app.modules.cases.models.case import Case, CaseComplaint
from app.modules.complaints.models.complaint import Complaint, Ward
from app.modules.complaints.ranking import calculate_composite_score
from app.modules.duplicates.models.duplicate import ComplaintSupport
from app.modules.identity.models.user import Department, User
from app.modules.priority.models.priority import PriorityAssessment


def build_complaint(
    citizen: User,
    title: str,
    latitude: float,
    longitude: float,
    *,
    ward: Ward | None = None,
    status: str = "IN_PROGRESS",
    upvote_count: int = 0,
) -> Complaint:
    return Complaint(
        tracking_number=f"GRV-RANK-{uuid.uuid4().hex[:8].upper()}",
        citizen_id=citizen.id,
        original_title=title,
        original_description=f"Detailed report for {title}",
        original_language="en",
        latitude=latitude,
        longitude=longitude,
        address="Regional test location",
        ward_id=ward.id if ward else None,
        ward_name=ward.name if ward else None,
        status=status,
        upvote_count=upvote_count,
    )


def build_assessment(complaint: Complaint, band: str) -> PriorityAssessment:
    sla_hours = {"CRITICAL": 4, "HIGH": 24, "MEDIUM": 72, "LOW": 168}[band]
    return PriorityAssessment(
        complaint_id=complaint.id,
        model_priority=band,
        model_confidence=1.0,
        model_reasoning="Ranking regression fixture",
        rule_hits=[],
        final_suggested_priority=band,
        suggested_sla_hours=sla_hours,
        is_safety_critical=band == "CRITICAL",
        recommendation_status="ACCEPTED",
    )


def test_critical_without_upvotes_outranks_medium_with_500_upvotes() -> None:
    created_at = datetime.now(timezone.utc)
    critical_score = calculate_composite_score("CRITICAL", 0, created_at, created_at)
    medium_score = calculate_composite_score("MEDIUM", 500, created_at, created_at)
    assert critical_score == 40_000
    assert medium_score == 22_500
    assert critical_score > medium_score


@pytest.mark.asyncio
async def test_complaint_and_case_lists_use_composite_priority_order(
    client: AsyncClient,
    db_session: AsyncSession,
    citizen_user: User,
    officer_token: str,
) -> None:
    critical = build_complaint(citizen_user, "Critical issue", 12.972, 77.641)
    medium = build_complaint(
        citizen_user, "Popular medium issue", 12.973, 77.642, upvote_count=500
    )
    db_session.add_all([critical, medium])
    await db_session.flush()
    db_session.add_all([build_assessment(critical, "CRITICAL"), build_assessment(medium, "MEDIUM")])
    critical_case = Case(
        case_number=f"CASE-{uuid.uuid4().hex[:8]}",
        title=critical.original_title,
        description=critical.original_description,
        status="IN_PROGRESS",
        priority="CRITICAL",
    )
    medium_case = Case(
        case_number=f"CASE-{uuid.uuid4().hex[:8]}",
        title=medium.original_title,
        description=medium.original_description,
        status="IN_PROGRESS",
        priority="MEDIUM",
    )
    db_session.add_all([critical_case, medium_case])
    await db_session.flush()
    db_session.add_all(
        [
            CaseComplaint(case_id=critical_case.id, complaint_id=critical.id, is_primary=True),
            CaseComplaint(case_id=medium_case.id, complaint_id=medium.id, is_primary=True),
        ]
    )
    await db_session.commit()

    complaints = await client.get(
        "/api/v1/complaints?sort=priority_score&status=open",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert complaints.status_code == 200
    complaint_items = complaints.json()["items"]
    assert [item["id"] for item in complaint_items[:2]] == [str(critical.id), str(medium.id)]
    assert complaint_items[0]["composite_score"] > complaint_items[1]["composite_score"]

    cases = await client.get(
        "/api/v1/cases?sort=priority_score&status=open",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert cases.status_code == 200
    case_items = cases.json()["items"]
    assert [item["id"] for item in case_items[:2]] == [str(critical_case.id), str(medium_case.id)]
    assert case_items[0]["composite_score"] > case_items[1]["composite_score"]


@pytest.mark.asyncio
async def test_regional_upvote_toggles_counter_and_writes_audit_events(
    client: AsyncClient,
    db_session: AsyncSession,
    citizen_user: User,
    citizen_token: str,
) -> None:
    complaint = build_complaint(citizen_user, "Nearby open drain", 12.972, 77.641)
    db_session.add(complaint)
    await db_session.commit()
    payload = {"latitude": 12.973, "longitude": 77.642}

    added = await client.post(
        f"/api/v1/complaints/{complaint.id}/upvote",
        json=payload,
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert added.status_code == 200
    assert added.json()["upvoted"] is True
    assert added.json()["upvote_count"] == 1

    removed = await client.post(
        f"/api/v1/complaints/{complaint.id}/upvote",
        json=payload,
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert removed.status_code == 200
    assert removed.json()["upvoted"] is False
    assert removed.json()["upvote_count"] == 0

    support_count = await db_session.scalar(
        select(func.count(ComplaintSupport.id)).where(
            ComplaintSupport.complaint_id == complaint.id
        )
    )
    audit_actions = list(
        (
            await db_session.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.entity_id == complaint.id)
                .order_by(AuditEvent.sequence_number)
            )
        ).all()
    )
    await db_session.refresh(complaint)
    assert support_count == 0
    assert complaint.upvote_count == 0
    assert audit_actions == ["complaint.upvoted", "complaint.upvote_removed"]


@pytest.mark.asyncio
async def test_trending_and_regional_department_filters(
    client: AsyncClient,
    db_session: AsyncSession,
    citizen_user: User,
    citizen_token: str,
    officer_token: str,
) -> None:
    ward = Ward(
        ward_number=104,
        name="Ward 104 - Indiranagar",
        boundary_geojson={"type": "Polygon", "coordinates": []},
        min_lat=12.95,
        max_lat=12.99,
        min_lon=77.62,
        max_lon=77.66,
    )
    department = Department(code="ROADS", name="Roads", description="Roads department")
    db_session.add_all([ward, department])
    await db_session.flush()
    popular = build_complaint(
        citizen_user, "Popular nearby pothole", 12.972, 77.641, ward=ward, upvote_count=12
    )
    quieter = build_complaint(
        citizen_user, "Nearby broken kerb", 12.973, 77.642, ward=ward, upvote_count=3
    )
    closed = build_complaint(
        citizen_user,
        "Closed nearby issue",
        12.974,
        77.643,
        ward=ward,
        status="CLOSED",
        upvote_count=100,
    )
    db_session.add_all([popular, quieter, closed])
    await db_session.flush()
    case = Case(
        case_number=f"CASE-{uuid.uuid4().hex[:8]}",
        title=popular.original_title,
        description=popular.original_description,
        status="IN_PROGRESS",
        priority="HIGH",
        lead_department_id=department.id,
    )
    db_session.add(case)
    await db_session.flush()
    db_session.add(CaseComplaint(case_id=case.id, complaint_id=popular.id, is_primary=True))
    await db_session.commit()

    trending = await client.get(
        "/api/v1/complaints/trending-nearby?lat=12.972&lng=77.641&radius_meters=2000",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert trending.status_code == 200
    trending_items = trending.json()
    assert [item["id"] for item in trending_items[:2]] == [str(popular.id), str(quieter.id)]
    assert all(item["status"] != "CLOSED" for item in trending_items)

    filtered = await client.get(
        "/api/v1/complaints?ward_number=104&department_name=Roads&sort=priority_score",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert filtered.status_code == 200
    assert [item["id"] for item in filtered.json()["items"]] == [str(popular.id)]
