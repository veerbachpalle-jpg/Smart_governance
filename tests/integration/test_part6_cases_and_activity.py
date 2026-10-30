import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError
from app.modules.activity.models.activity import CaseActivity
from app.modules.cases.models.case import Case, CaseDepartment
from app.modules.complaints.models.complaint import Complaint
from app.modules.identity.models.user import Department, User
from app.modules.identity.schemas.identity import UserRole


@pytest.fixture
async def municipal_departments(db_session: AsyncSession) -> list[Department]:
    depts = [
        Department(id=uuid.uuid4(), name="Roads and Bridges", code="ROADS", is_active=True),
        Department(id=uuid.uuid4(), name="Water Works", code="WATER", is_active=True),
        Department(id=uuid.uuid4(), name="Street Lighting", code="ELEC", is_active=True),
    ]
    for d in depts:
        db_session.add(d)
    await db_session.commit()
    for d in depts:
        await db_session.refresh(d)
    return depts


@pytest.fixture
async def triage_complaint(db_session: AsyncSession, citizen_user: User) -> Complaint:
    c = Complaint(
        id=uuid.uuid4(),
        tracking_number=f"GRV-TRIAGE-{uuid.uuid4().hex[:6].upper()}",
        citizen_id=citizen_user.id,
        original_title="Dangerous pothole cluster on ring road",
        original_description="Multiple severe potholes causing bike falls.",
        original_language="en",
        latitude=12.9250,
        longitude=77.5850,
        address="Outer Ring Road",
        status="TRIAGE_REVIEW",
    )
    db_session.add(c)
    await db_session.commit()
    await db_session.refresh(c)
    return c


# ========================================================
# 1. Exhaustive State Machine Table & Universal Side-Effects
# ========================================================


@pytest.mark.asyncio
async def test_state_machine_valid_transitions_and_side_effects(
    client: AsyncClient,
    officer_token: str,
    lead_token: str,
    supervisor_token: str,
    officer_user: User,
    triage_complaint: Complaint,
    municipal_departments: list[Department],
) -> None:
    dept_roads = municipal_departments[0]
    dept_water = municipal_departments[1]

    # 1. Create Case from Complaint
    create_resp = await client.post(
        "/api/v1/cases",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"complaint_id": str(triage_complaint.id)},
    )
    assert create_resp.status_code == 201
    case_data = create_resp.json()
    case_id = case_data["id"]
    assert case_data["status"] == "TRIAGE_REVIEW"

    # Step A: TRIAGE_REVIEW -> ROUTED (Allowed: officer)
    trans_routed = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "target_state": "ROUTED",
            "department_id": str(dept_roads.id),
        },
    )
    assert trans_routed.status_code == 200
    assert trans_routed.json()["status"] == "ROUTED"
    assert trans_routed.json()["lead_department_id"] == str(dept_roads.id)

    # Step B: ROUTED -> ACCEPTED_BY_LEAD (Allowed: department_lead)
    trans_accepted = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {lead_token}"},
        json={"target_state": "ACCEPTED_BY_LEAD"},
    )
    assert trans_accepted.status_code == 200
    assert trans_accepted.json()["status"] == "ACCEPTED_BY_LEAD"

    # Step C: ACCEPTED_BY_LEAD -> IN_PROGRESS (Allowed: department_lead, requires assigned officer)
    # Missing officer assignment should fail
    fail_in_progress = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {lead_token}"},
        json={"target_state": "IN_PROGRESS"},
    )
    assert fail_in_progress.status_code == 400
    assert fail_in_progress.json()["code"] == "OFFICER_ASSIGNMENT_REQUIRED"

    # With officer assigned, transitions successfully
    trans_in_progress = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {lead_token}"},
        json={
            "target_state": "IN_PROGRESS",
            "assigned_officer_id": str(officer_user.id),
        },
    )
    assert trans_in_progress.status_code == 200
    assert trans_in_progress.json()["status"] == "IN_PROGRESS"
    assert trans_in_progress.json()["assigned_officer_id"] == str(officer_user.id)

    # Step D: IN_PROGRESS -> REASSIGN_REQUESTED (Allowed: officer/lead, requires reason)
    fail_reassign = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"target_state": "REASSIGN_REQUESTED"},
    )
    assert fail_reassign.status_code == 400

    trans_reassign = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "target_state": "REASSIGN_REQUESTED",
            "reason": "Water pipeline burst underneath the road surface; Water Works must fix first.",
            "department_id": str(dept_water.id),
        },
    )
    assert trans_reassign.status_code == 200
    assert trans_reassign.json()["status"] == "REASSIGN_REQUESTED"

    # Step E: REASSIGN_REQUESTED -> ROUTED (Allowed: supervisor)
    trans_rerouted = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {supervisor_token}"},
        json={
            "target_state": "ROUTED",
            "department_id": str(dept_water.id),
        },
    )
    assert trans_rerouted.status_code == 200
    assert trans_rerouted.json()["status"] == "ROUTED"
    assert trans_rerouted.json()["lead_department_id"] == str(dept_water.id)

    # Step F: ROUTED -> REJECTED_WITH_REASON (Allowed: supervisor, requires reason)
    fail_reject = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {supervisor_token}"},
        json={"target_state": "REJECTED_WITH_REASON"},
    )
    assert fail_reject.status_code == 400

    trans_reject = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {supervisor_token}"},
        json={
            "target_state": "REJECTED_WITH_REASON",
            "reason": "Private road outside municipal jurisdiction.",
        },
    )
    assert trans_reject.status_code == 200
    assert trans_reject.json()["status"] == "REJECTED_WITH_REASON"

    # Verify activity history recorded every step
    act_resp = await client.get(
        f"/api/v1/cases/{case_id}/activities",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    assert act_resp.status_code == 200
    activities = act_resp.json()
    act_types = [a["activity_type"] for a in activities]
    assert "CASE_CREATED" in act_types
    assert "CASE_ROUTED" in act_types
    assert "CASE_ACCEPTED_BY_DEPARTMENT" in act_types
    assert "OFFICER_ASSIGNED" in act_types
    assert "REASSIGNMENT_REQUESTED" in act_types
    assert "CASE_REASSIGNED" in act_types
    assert "CASE_REJECTED" in act_types


@pytest.mark.asyncio
async def test_illegal_state_transitions_fail(
    client: AsyncClient,
    officer_token: str,
    triage_complaint: Complaint,
) -> None:
    # Create Case
    create_resp = await client.post(
        "/api/v1/cases",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"complaint_id": str(triage_complaint.id)},
    )
    case_id = create_resp.json()["id"]

    # Attempt illegal jump: TRIAGE_REVIEW -> IN_PROGRESS directly
    illegal_resp = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"target_state": "IN_PROGRESS"},
    )
    assert illegal_resp.status_code == 400
    assert illegal_resp.json()["code"] == "ILLEGAL_TRANSITION"


# ========================================================
# 2. Exactly ONE Accountable Lead Constraint
# ========================================================


@pytest.mark.asyncio
async def test_one_accountable_lead_department_constraint(
    client: AsyncClient,
    officer_token: str,
    triage_complaint: Complaint,
    municipal_departments: list[Department],
    db_session: AsyncSession,
) -> None:
    dept1 = municipal_departments[0]
    dept2 = municipal_departments[1]

    # Create Case
    create_resp = await client.post(
        "/api/v1/cases",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"complaint_id": str(triage_complaint.id)},
    )
    case_id = uuid.UUID(create_resp.json()["id"])

    # Add Department 1 as lead
    add_dept1 = await client.post(
        f"/api/v1/cases/{case_id}/departments",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"department_id": str(dept1.id), "is_lead": True},
    )
    assert add_dept1.status_code == 200
    assert any(
        d["department_id"] == str(dept1.id) and d["is_lead"] is True
        for d in add_dept1.json()["departments"]
    )

    # Add Department 2 as non-lead (co-jurisdiction)
    add_dept2 = await client.post(
        f"/api/v1/cases/{case_id}/departments",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"department_id": str(dept2.id), "is_lead": False},
    )
    assert add_dept2.status_code == 200
    depts = add_dept2.json()["departments"]
    lead_count = sum(1 for d in depts if d["is_lead"])
    assert lead_count == 1

    # Switch lead to Department 2
    set_lead_resp = await client.put(
        f"/api/v1/cases/{case_id}/lead",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"department_id": str(dept2.id)},
    )
    assert set_lead_resp.status_code == 200
    depts_after = set_lead_resp.json()["departments"]
    assert sum(1 for d in depts_after if d["is_lead"]) == 1
    lead_dept = next(d for d in depts_after if d["is_lead"])
    assert lead_dept["department_id"] == str(dept2.id)

    # Invariant at DB level: attempting raw duplicate is_lead=True fails with IntegrityError
    raw_cd = CaseDepartment(case_id=case_id, department_id=dept1.id, is_lead=True)
    db_session.add(raw_cd)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


# ========================================================
# 3. Role Restrictions
# ========================================================


@pytest.mark.asyncio
async def test_role_restrictions_on_state_machine(
    client: AsyncClient,
    citizen_token: str,
    officer_token: str,
    triage_complaint: Complaint,
    municipal_departments: list[Department],
) -> None:
    dept = municipal_departments[0]

    # Officer creates case and routes it
    create_resp = await client.post(
        "/api/v1/cases",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"complaint_id": str(triage_complaint.id)},
    )
    case_id = create_resp.json()["id"]

    await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"target_state": "ROUTED", "department_id": str(dept.id)},
    )

    # 1. Citizen cannot transition case (403 Forbidden)
    citizen_fail = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {citizen_token}"},
        json={"target_state": "ACCEPTED_BY_LEAD"},
    )
    assert citizen_fail.status_code == 403

    # 2. Officer cannot accept case on behalf of department lead (403 Forbidden)
    officer_accept_fail = await client.post(
        f"/api/v1/cases/{case_id}/transition",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"target_state": "ACCEPTED_BY_LEAD"},
    )
    assert officer_accept_fail.status_code == 403
    assert officer_accept_fail.json()["code"] == "ROLE_NOT_PERMITTED"


# ========================================================
# 4. Citizens NEVER See INTERNAL Activities
# ========================================================


@pytest.mark.asyncio
async def test_citizens_never_see_internal_activities(
    client: AsyncClient,
    officer_token: str,
    citizen_token: str,
    citizen_user: User,
    triage_complaint: Complaint,
    db_session: AsyncSession,
) -> None:
    # 1. Create case
    create_resp = await client.post(
        "/api/v1/cases",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"complaint_id": str(triage_complaint.id)},
    )
    case_id = create_resp.json()["id"]

    # 2. Officer adds an INTERNAL activity
    internal_resp = await client.post(
        f"/api/v1/cases/{case_id}/activity",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "activity_type": "INTERNAL_NOTE",
            "visibility": "INTERNAL",
            "message": "CONFIDENTIAL: Suspected illegal digging by private contractor.",
        },
    )
    assert internal_resp.status_code == 201

    # 3. Officer broadcasts a CITIZEN_VISIBLE update
    pub_resp = await client.post(
        f"/api/v1/cases/{case_id}/citizen-updates",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "title": "Repair Crew Dispatched",
            "message": "Asphalt restoration equipment is scheduled to arrive on site at 10:00 AM.",
        },
    )
    assert pub_resp.status_code == 201

    # 4. Staff view: sees ALL activities (INTERNAL + CITIZEN_VISIBLE)
    staff_view = await client.get(
        f"/api/v1/cases/{case_id}/activities",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert staff_view.status_code == 200
    staff_acts = staff_view.json()
    staff_visibilities = {a["visibility"] for a in staff_acts}
    assert "INTERNAL" in staff_visibilities
    assert "CITIZEN_VISIBLE" in staff_visibilities

    # 5. Citizen timeline: strictly ONLY CITIZEN_VISIBLE
    cit_resp = await client.get(
        f"/api/v1/cases/citizen-timeline/{triage_complaint.id}",
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert cit_resp.status_code == 200
    cit_timeline = cit_resp.json()
    assert len(cit_timeline) >= 1

    # Assert NO internal activity leaked into citizen timeline
    for item in cit_timeline:
        assert "CONFIDENTIAL" not in item["message"]
        assert "illegal digging" not in item["message"]

    # Confirm citizen update message IS present
    assert any("Repair Crew Dispatched" in item["message"] for item in cit_timeline)

    # 6. Another citizen cannot view someone else's complaint timeline
    other_citizen = User(
        id=uuid.uuid4(),
        email="stranger@example.com",
        phone_number="+15559999",
        password_hash="hash",
        role=UserRole.CITIZEN.value,
        is_active=True,
    )
    db_session.add(other_citizen)
    await db_session.commit()
    from app.core.security import create_access_token

    other_token = create_access_token(subject=str(other_citizen.id), role=other_citizen.role)

    unauthorized_resp = await client.get(
        f"/api/v1/cases/citizen-timeline/{triage_complaint.id}",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert unauthorized_resp.status_code == 403


# ========================================================
# 5. CaseActivity Immutability Enforcement
# ========================================================


@pytest.mark.asyncio
async def test_case_activity_immutability(
    triage_complaint: Complaint,
    db_session: AsyncSession,
) -> None:
    # Directly test that updating or deleting CaseActivity raises ConflictError
    case = Case(
        id=uuid.uuid4(),
        case_number="CASE-TEST-IMMUTABLE",
        title="Test Immutability",
        description="Desc",
    )
    db_session.add(case)
    await db_session.flush()

    act = CaseActivity(
        case_id=case.id,
        activity_type="IMMUTABILITY_PROBE",
        visibility="INTERNAL",
        message="Initial message",
    )
    db_session.add(act)
    await db_session.commit()
    await db_session.refresh(act)

    # Attempt mutation
    act.message = "Mutated message"
    with pytest.raises(ConflictError):
        await db_session.flush()
    await db_session.rollback()

    # Attempt deletion
    await db_session.refresh(act)
    await db_session.delete(act)
    with pytest.raises(ConflictError):
        await db_session.flush()
    await db_session.rollback()


# ========================================================
# 6. Supervisor Reassignment Approval Queue, Priority Override & Department Operations
# ========================================================


@pytest.mark.asyncio
async def test_supervisor_reassignment_approve_and_reject(
    client: AsyncClient,
    officer_token: str,
    supervisor_token: str,
    municipal_departments: list[Department],
    triage_complaint: Complaint,
) -> None:
    dept_1 = municipal_departments[0]
    dept_2 = municipal_departments[1]

    # 1. Officer creates a case from complaint
    c_resp = await client.post(
        "/api/v1/cases",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"complaint_id": str(triage_complaint.id), "title": "Pothole remediation case"},
    )
    assert c_resp.status_code == 201
    case_id = c_resp.json()["id"]

    # 2. Add lead department
    await client.put(
        f"/api/v1/cases/{case_id}/lead",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"department_id": str(dept_1.id)},
    )

    # 3. Request reassignment with mandatory reason and optional evidence_urls
    reassign_res = await client.post(
        f"/api/v1/cases/{case_id}/reassign",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={
            "suggested_department_id": str(dept_2.id),
            "reason": "Road is under water authority jurisdiction due to burst main pipe underneath.",
            "evidence_urls": ["https://storage.example.com/burst_pipe.jpg"],
        },
    )
    assert reassign_res.status_code == 200
    assert reassign_res.json()["status"] == "REASSIGN_REQUESTED"

    # 4. Supervisor views pending reassignments queue
    pending_res = await client.get(
        "/api/v1/cases/reassign-requests/pending",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    assert pending_res.status_code == 200
    pending_list = pending_res.json()
    assert len(pending_list) >= 1
    req_item = next(r for r in pending_list if r["case_id"] == case_id)
    assert req_item["status"] == "PENDING"
    assert req_item["suggested_department_id"] == str(dept_2.id)
    assert req_item["evidence_urls"] == ["https://storage.example.com/burst_pipe.jpg"]

    # 5. Citizen timeline during review shows "Routing is currently under review by municipal supervisors."
    time_res = await client.get(
        f"/api/v1/cases/citizen-timeline/{triage_complaint.id}",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    assert time_res.status_code == 200
    assert any("Routing is currently under review by municipal supervisors" in it["message"] for it in time_res.json())

    # 6. Supervisor approves reassignment -> atomically swaps lead department and transitions to ROUTED
    approve_res = await client.post(
        f"/api/v1/cases/{case_id}/reassign-requests/{req_item['id']}/approve",
        headers={"Authorization": f"Bearer {supervisor_token}"},
        json={"decision_notes": "Confirmed: pipe defect belongs to water department."},
    )
    assert approve_res.status_code == 200
    appr_data = approve_res.json()
    assert appr_data["status"] == "ROUTED"
    assert appr_data["lead_department_id"] == str(dept_2.id)

    # 7. Priority override by supervisor
    prio_res = await client.post(
        f"/api/v1/cases/{case_id}/priority/override",
        headers={"Authorization": f"Bearer {supervisor_token}"},
        json={"priority": "CRITICAL", "justification": "Immediate flooding hazard for surrounding buildings."},
    )
    assert prio_res.status_code == 200
    assert prio_res.json()["priority"] == "CRITICAL"

    # 8. Add supporting department then remove supporting department
    dept_3 = municipal_departments[2]
    add_dept_res = await client.post(
        f"/api/v1/cases/{case_id}/departments",
        headers={"Authorization": f"Bearer {supervisor_token}"},
        json={"department_id": str(dept_3.id), "is_lead": False},
    )
    assert add_dept_res.status_code == 200
    assert len(add_dept_res.json()["departments"]) >= 2

    # Cannot remove lead department
    bad_del_res = await client.delete(
        f"/api/v1/cases/{case_id}/departments/{dept_2.id}",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    assert bad_del_res.status_code == 400

    # Can remove supporting department
    del_res = await client.delete(
        f"/api/v1/cases/{case_id}/departments/{dept_3.id}",
        headers={"Authorization": f"Bearer {supervisor_token}"},
    )
    assert del_res.status_code == 200

