import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.complaints.models.complaint import Complaint
from app.modules.identity.models.user import Department, User
from app.modules.priority.service.priority_service import (
    enforce_safety_only_raises,
)
from app.modules.routing.service.routing_service import RoutingService


@pytest.fixture
async def setup_departments(db_session: AsyncSession) -> list[Department]:
    depts = [
        Department(id=uuid.uuid4(), name="Roads and Infrastructure", code="ROADS", is_active=True),
        Department(id=uuid.uuid4(), name="Water and Sewage", code="WATER", is_active=True),
        Department(
            id=uuid.uuid4(), name="Electricity and Street Lighting", code="ELEC", is_active=True
        ),
        Department(
            id=uuid.uuid4(), name="Sanitation and Waste Management", code="SWM", is_active=True
        ),
    ]
    for d in depts:
        db_session.add(d)
    await db_session.commit()
    for d in depts:
        await db_session.refresh(d)
    return depts


@pytest.fixture
async def sample_complaint(db_session: AsyncSession, citizen_user: User) -> Complaint:
    c = Complaint(
        id=uuid.uuid4(),
        tracking_number=f"GRV-TEST-{uuid.uuid4().hex[:6].upper()}",
        citizen_id=citizen_user.id,
        original_title="Deep crater pothole on MG Road",
        original_description="Large pothole causing vehicle damage near junction.",
        original_language="en",
        latitude=12.9716,
        longitude=77.5946,
        address="MG Road, Bangalore",
        status="TRIAGE_REVIEW",
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


# ==========================================
# 1. Routing Rule Versioning & Effective Dates
# ==========================================


@pytest.mark.asyncio
async def test_routing_rule_versioning_and_effective_dates(
    client: AsyncClient,
    admin_token: str,
    setup_departments: list[Department],
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": f"Bearer {admin_token}"}
    dept1 = setup_departments[0]
    dept2 = setup_departments[1]

    # Create rule v1
    resp1 = await client.post(
        "/api/v1/routing/rules",
        headers=headers,
        json={
            "category": "Roads & Footpaths",
            "department_id": str(dept1.id),
            "is_active": True,
        },
    )
    assert resp1.status_code == 201
    r1 = resp1.json()
    assert r1["rule_version"] == 1
    assert r1["category"] == "Roads & Footpaths"

    # Create rule v2 (monotonically increments)
    resp2 = await client.post(
        "/api/v1/routing/rules",
        headers=headers,
        json={
            "category": "Roads & Footpaths",
            "department_id": str(dept2.id),
            "is_active": True,
        },
    )
    assert resp2.status_code == 201
    r2 = resp2.json()
    assert r2["rule_version"] == 2

    # Test effective dates: Create rule that expired yesterday
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    last_week = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    resp_expired = await client.post(
        "/api/v1/routing/rules",
        headers=headers,
        json={
            "category": "Water Supply & Sewerage",
            "department_id": str(dept2.id),
            "effective_from": last_week,
            "effective_to": yesterday,
            "is_active": True,
        },
    )
    assert resp_expired.status_code == 201
    expired_id = resp_expired.json()["id"]

    # Verify query for active matching rules excludes expired rule
    service = RoutingService(db_session)
    active_rules = await service.repo.find_matching_active_rules(
        category="Water Supply & Sewerage",
        at_time=datetime.now(timezone.utc),
    )
    assert not any(r.id == uuid.UUID(expired_id) for r in active_rules)


# ==========================================
# 2. Officer Routing Decision Lifecycle
# ==========================================


@pytest.mark.asyncio
async def test_officer_routing_decisions(
    client: AsyncClient,
    officer_token: str,
    setup_departments: list[Department],
    sample_complaint: Complaint,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": f"Bearer {officer_token}"}
    complaint_id = sample_complaint.id

    # 1. Get routing recommendation
    get_resp = await client.get(
        f"/api/v1/complaints/{complaint_id}/routing",
        headers=headers,
    )
    assert get_resp.status_code == 200
    data = get_resp.json()
    assert len(data["recommended_departments"]) >= 1
    assert data["recommendation_status"] == "PENDING"

    # 2. Override routing with reason
    alt_dept = setup_departments[2]
    override_resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/routing/override",
        headers=headers,
        json={
            "department_id": str(alt_dept.id),
            "reason": "Traffic signal electrical issue takes priority over pothole.",
        },
    )
    assert override_resp.status_code == 200
    ov_data = override_resp.json()
    assert ov_data["recommendation_status"] == "OVERRIDDEN"
    assert ov_data["primary_department_id"] == str(alt_dept.id)

    # Verify complaint advanced to ROUTED
    await db_session.refresh(sample_complaint)
    assert sample_complaint.status == "ROUTED"

    # 3. Accept routing
    accept_resp = await client.post(
        f"/api/v1/complaints/{complaint_id}/routing/accept",
        headers=headers,
        json={"notes": "Confirmed and accepted by officer"},
    )
    assert accept_resp.status_code == 200
    assert accept_resp.json()["recommendation_status"] == "ACCEPTED"


# ==========================================
# 3. Safety-Only-Raises Invariant
# ==========================================


def test_safety_only_raises_invariant() -> None:
    # Model suggests LOW, rule hits CRITICAL -> CRITICAL
    assert enforce_safety_only_raises("LOW", [{"elevate_to_priority": "CRITICAL"}]) == "CRITICAL"

    # Model suggests HIGH, rule hits CRITICAL -> CRITICAL
    assert enforce_safety_only_raises("HIGH", [{"elevate_to_priority": "CRITICAL"}]) == "CRITICAL"

    # Model suggests CRITICAL, rule hits HIGH -> remains CRITICAL (NEVER LOWERED)
    assert enforce_safety_only_raises("CRITICAL", [{"elevate_to_priority": "HIGH"}]) == "CRITICAL"

    # Model suggests CRITICAL, rule hits MEDIUM -> remains CRITICAL (NEVER LOWERED)
    assert enforce_safety_only_raises("CRITICAL", [{"elevate_to_priority": "MEDIUM"}]) == "CRITICAL"

    # Model suggests HIGH, rule hits LOW -> remains HIGH (NEVER LOWERED)
    assert enforce_safety_only_raises("HIGH", [{"elevate_to_priority": "LOW"}]) == "HIGH"

    # Model suggests MEDIUM, no rule hits -> remains MEDIUM
    assert enforce_safety_only_raises("MEDIUM", []) == "MEDIUM"


# ==========================================
# 4. Multilingual Keyword Hits
# ==========================================


@pytest.mark.asyncio
async def test_multilingual_safety_keywords(
    client: AsyncClient,
    officer_token: str,
    citizen_user: User,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": f"Bearer {officer_token}"}

    # 1. English hazard: live wire
    c_en = Complaint(
        id=uuid.uuid4(),
        tracking_number=f"GRV-EN-{uuid.uuid4().hex[:6].upper()}",
        citizen_id=citizen_user.id,
        original_title="Sparking live wire hanging on street",
        original_description="There is a live wire touching the ground with sparking.",
        original_language="en",
        latitude=12.9716,
        longitude=77.5946,
        address="1st Main Rd",
        status="TRIAGE_REVIEW",
    )
    db_session.add(c_en)

    # 2. Hindi hazard: खुला तार और करंट
    c_hi = Complaint(
        id=uuid.uuid4(),
        tracking_number=f"GRV-HI-{uuid.uuid4().hex[:6].upper()}",
        citizen_id=citizen_user.id,
        original_title="सड़क पर खुला तार गिर गया है",
        original_description="बिजली का झटका लगने का खतरा है, तुरंत ठीक करें।",
        original_language="hi",
        latitude=12.9716,
        longitude=77.5946,
        address="2nd Main Rd",
        status="TRIAGE_REVIEW",
    )
    db_session.add(c_hi)

    # 3. Kannada hazard: ತೆರೆದ ತಂತಿ ಮತ್ತು ಕರೆಂಟ್
    c_kn = Complaint(
        id=uuid.uuid4(),
        tracking_number=f"GRV-KN-{uuid.uuid4().hex[:6].upper()}",
        citizen_id=citizen_user.id,
        original_title="ರಸ್ತೆಯಲ್ಲಿ ತೆರೆದ ತಂತಿ ಬಿದ್ದಿದೆ",
        original_description="ಕರೆಂಟ್ ಹೊಡೆಯುವ ಅಪಾಯವಿದೆ ಬೇಗ ಸರಿಪಡಿಸಿ।",
        original_language="kn",
        latitude=12.9716,
        longitude=77.5946,
        address="3rd Main Rd",
        status="TRIAGE_REVIEW",
    )
    db_session.add(c_kn)
    await db_session.commit()

    # Assess English
    res_en = await client.get(f"/api/v1/complaints/{c_en.id}/priority", headers=headers)
    assert res_en.status_code == 200
    data_en = res_en.json()
    assert data_en["final_suggested_priority"] == "CRITICAL"
    assert data_en["is_safety_critical"] is True
    assert any("live" in str(h) for h in data_en["rule_hits"])

    # Assess Hindi
    res_hi = await client.get(f"/api/v1/complaints/{c_hi.id}/priority", headers=headers)
    assert res_hi.status_code == 200
    data_hi = res_hi.json()
    assert data_hi["final_suggested_priority"] == "CRITICAL"
    assert data_hi["is_safety_critical"] is True
    assert any(h["language"] == "hi" for h in data_hi["rule_hits"])

    # Assess Kannada
    res_kn = await client.get(f"/api/v1/complaints/{c_kn.id}/priority", headers=headers)
    assert res_kn.status_code == 200
    data_kn = res_kn.json()
    assert data_kn["final_suggested_priority"] == "CRITICAL"
    assert data_kn["is_safety_critical"] is True
    assert any(h["language"] == "kn" for h in data_kn["rule_hits"])

    # Verify priority queue includes critical items
    queue_resp = await client.get("/api/v1/priority/queue", headers=headers)
    assert queue_resp.status_code == 200
    q_items = queue_resp.json()
    assert len(q_items) >= 3


# ==========================================
# 5. Duplicate Ranking & NO Auto-Merge
# ==========================================


@pytest.mark.asyncio
async def test_duplicate_ranking_and_no_auto_merge(
    client: AsyncClient,
    officer_token: str,
    citizen_user: User,
    db_session: AsyncSession,
) -> None:
    headers = {"Authorization": f"Bearer {officer_token}"}

    # Complaint A: Base incident
    comp_a = Complaint(
        id=uuid.uuid4(),
        tracking_number=f"GRV-A-{uuid.uuid4().hex[:6].upper()}",
        citizen_id=citizen_user.id,
        original_title="Huge water pipeline burst on Indiranagar 100ft road",
        original_description="Clean drinking water gushing out flooding the road.",
        original_language="en",
        latitude=12.9784,
        longitude=77.6408,
        address="100ft Rd, Indiranagar",
        status="TRIAGE_REVIEW",
    )
    db_session.add(comp_a)

    # Complaint B: Nearby duplicate (~100m away, same water pipeline burst)
    comp_b = Complaint(
        id=uuid.uuid4(),
        tracking_number=f"GRV-B-{uuid.uuid4().hex[:6].upper()}",
        citizen_id=citizen_user.id,
        original_title="Water pipe leak flooding 100 feet road",
        original_description="Large water leak on the main road Indiranagar.",
        original_language="en",
        latitude=12.9790,
        longitude=77.6412,
        address="100ft Rd, Indiranagar near signal",
        status="TRIAGE_REVIEW",
    )
    db_session.add(comp_b)

    # Complaint C: Distant incident (300 km away)
    comp_c = Complaint(
        id=uuid.uuid4(),
        tracking_number=f"GRV-C-{uuid.uuid4().hex[:6].upper()}",
        citizen_id=citizen_user.id,
        original_title="Water pipe leak",
        original_description="Water pipe leak in distant city.",
        original_language="en",
        latitude=13.0827,
        longitude=80.2707,
        address="Chennai Central",
        status="TRIAGE_REVIEW",
    )
    db_session.add(comp_c)
    await db_session.commit()

    # Search duplicate candidates for Complaint A
    dup_resp = await client.get(
        f"/api/v1/complaints/{comp_a.id}/duplicates?radius_meters=3000",
        headers=headers,
    )
    assert dup_resp.status_code == 200
    candidates = dup_resp.json()

    # Nearby Complaint B must be found and ranked
    assert len(candidates) >= 1
    top_cand = candidates[0]
    assert top_cand["candidate_complaint_id"] == str(comp_b.id)
    assert top_cand["overall_score"] > 0.6
    assert top_cand["geo_similarity"] > 0.8
    assert top_cand["distance_meters"] < 200.0

    # Distant Complaint C should NOT be included (filtered out by radius)
    cand_ids = [c["candidate_complaint_id"] for c in candidates]
    assert str(comp_c.id) not in cand_ids

    # Officer links candidate B to A
    cand_record_id = top_cand["id"]
    link_resp = await client.post(
        f"/api/v1/complaints/{comp_a.id}/duplicates/{cand_record_id}/link",
        headers=headers,
        json={"reason": "Confirmed duplicate incident on same 100ft road water line."},
    )
    assert link_resp.status_code == 200
    assert link_resp.json()["status"] == "LINKED"

    # CRITICAL INVARIANT: NEVER AUTO-MERGE
    # Verify BOTH complaints remain in the database intact with independent records
    await db_session.refresh(comp_a)
    await db_session.refresh(comp_b)
    assert comp_a.id != comp_b.id
    assert comp_a.tracking_number != comp_b.tracking_number
    assert comp_a.status == "TRIAGE_REVIEW"
    assert comp_b.status == "TRIAGE_REVIEW"


# ==========================================
# 6. Citizen Nearby Reports & Support Endorsement
# ==========================================


@pytest.mark.asyncio
async def test_citizen_nearby_similar_and_support(
    client: AsyncClient,
    citizen_token: str,
    sample_complaint: Complaint,
) -> None:
    headers = {"Authorization": f"Bearer {citizen_token}"}

    # Citizen checks nearby similar reports
    nearby_resp = await client.get(
        f"/api/v1/complaints/nearby-similar?latitude={sample_complaint.latitude}&longitude={sample_complaint.longitude}&radius_meters=2000",
    )
    assert nearby_resp.status_code == 200
    reports = nearby_resp.json()
    assert len(reports) >= 1

    # Ensure strictly limited, non-sensitive fields (NO citizen PII)
    rep = reports[0]
    assert "tracking_number" in rep
    assert "title" in rep
    assert "status" in rep
    assert "distance_meters" in rep
    assert "support_count" in rep
    assert "email" not in rep
    assert "phone_number" not in rep
    assert "citizen_id" not in rep

    # Citizen clicks "This is the same issue" (adds support)
    sup_resp = await client.post(
        f"/api/v1/complaints/{sample_complaint.id}/support",
        headers=headers,
    )
    assert sup_resp.status_code == 200
    assert sup_resp.json()["support_count"] == 1

    # Endorsing again is idempotent
    sup_repeat = await client.post(
        f"/api/v1/complaints/{sample_complaint.id}/support",
        headers=headers,
    )
    assert sup_repeat.status_code == 200
    assert sup_repeat.json()["support_count"] == 1
