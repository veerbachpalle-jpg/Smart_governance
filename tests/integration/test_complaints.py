import io
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox import OutboxEvent
from app.core.security import create_access_token, hash_password
from app.modules.complaints.models.complaint import Ward
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole


@pytest.fixture
async def seeded_wards(db_session: AsyncSession) -> list[Ward]:
    wards_data = [
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
    ]
    created = []
    for w in wards_data:
        ward = Ward(
            ward_number=w["ward_number"],
            name=w["name"],
            boundary_geojson=w["boundary_geojson"],
            min_lat=w["min_lat"],
            max_lat=w["max_lat"],
            min_lon=w["min_lon"],
            max_lon=w["max_lon"],
        )
        db_session.add(ward)
        created.append(ward)
    await db_session.commit()
    return created


@pytest.fixture
async def second_citizen_user(db_session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        email="citizen2@example.com",
        phone_number="+15550009",
        password_hash=hash_password("Password123!"),
        role=UserRole.CITIZEN.value,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    return user


@pytest.fixture
def second_citizen_token(second_citizen_user: User) -> str:
    return create_access_token(subject=str(second_citizen_user.id), role=second_citizen_user.role)


# ==========================================
# 1. Create Complaint & Outbox & Audit Tests
# ==========================================


@pytest.mark.asyncio
async def test_create_complaint_success(
    client: AsyncClient,
    citizen_token: str,
    seeded_wards: list[Ward],
    db_session: AsyncSession,
) -> None:
    idem_key = f"create-grv-{uuid.uuid4()}"
    payload = {
        "title": "Severe Pothole on 5th Cross Road",
        "description": "Deep pothole causing vehicle damage near the intersection. Immediate repair needed.",
        "latitude": 12.9800,
        "longitude": 77.6000,
        "address": "5th Cross Road, Ward 1",
        "channel": "MOBILE",
    }
    response = await client.post(
        "/api/v1/complaints",
        json=payload,
        headers={"Authorization": f"Bearer {citizen_token}", "Idempotency-Key": idem_key},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "SUBMITTED"
    assert data["original_title"] == "Severe Pothole on 5th Cross Road"
    assert data["original_description"] == payload["description"]
    assert data["ward_name"] == "Ward 1 - Central"
    assert "tracking_number" in data

    # Verify Outbox event was created in the SAME transaction
    stmt = select(OutboxEvent).where(
        OutboxEvent.aggregate_id == uuid.UUID(data["id"]),
        OutboxEvent.event_type == "ComplaintSubmitted",
    )
    res = await db_session.execute(stmt)
    outbox_event = res.scalar_one_or_none()
    assert outbox_event is not None
    assert outbox_event.status == "PENDING"
    assert outbox_event.payload["tracking_number"] == data["tracking_number"]


@pytest.mark.asyncio
async def test_create_complaint_geo_ward_assignment(
    client: AsyncClient,
    citizen_token: str,
    seeded_wards: list[Ward],
) -> None:
    # Coordinate located squarely in Ward 2 - North (13.02, 77.60)
    response = await client.post(
        "/api/v1/complaints",
        json={
            "title": "Broken Streetlight North Ward",
            "description": "Streetlight pole flickering throughout the night.",
            "latitude": 13.0200,
            "longitude": 77.6000,
            "address": "North Blvd, Ward 2",
        },
        headers={
            "Authorization": f"Bearer {citizen_token}",
            "Idempotency-Key": f"ward-assign-{uuid.uuid4()}",
        },
    )
    assert response.status_code == 201
    assert response.json()["ward_name"] == "Ward 2 - North"


# ==========================================
# 2. Public Tracking Endpoint Tests
# ==========================================


@pytest.mark.asyncio
async def test_public_safe_tracking(
    client: AsyncClient,
    citizen_token: str,
    seeded_wards: list[Ward],
) -> None:
    # Create complaint
    create_res = await client.post(
        "/api/v1/complaints",
        json={
            "title": "Garbage accumulation",
            "description": "Garbage has not been collected for 4 days.",
            "latitude": 12.9800,
            "longitude": 77.6000,
            "address": "Central Market",
        },
        headers={
            "Authorization": f"Bearer {citizen_token}",
            "Idempotency-Key": f"track-test-{uuid.uuid4()}",
        },
    )
    complaint_id = create_res.json()["id"]
    tracking_number = create_res.json()["tracking_number"]

    # Public tracking by UUID
    track_res1 = await client.get(f"/api/v1/complaints/{complaint_id}/tracking")
    assert track_res1.status_code == 200
    t_data1 = track_res1.json()
    assert t_data1["status"] == "SUBMITTED"
    assert t_data1["tracking_number"] == tracking_number
    # Invariant: Must NOT contain private data
    assert "citizen_id" not in t_data1
    assert "email" not in t_data1
    assert "address" not in t_data1

    # Public tracking by Tracking Number
    track_res2 = await client.get(f"/api/v1/complaints/{tracking_number}/tracking")
    assert track_res2.status_code == 200
    assert track_res2.json()["tracking_number"] == tracking_number


# ==========================================
# 3. Authorization & Object-Level Isolation
# ==========================================


@pytest.mark.asyncio
async def test_citizen_cannot_see_other_citizen_complaint(
    client: AsyncClient,
    citizen_token: str,
    second_citizen_token: str,
    officer_token: str,
    seeded_wards: list[Ward],
) -> None:
    # Citizen 1 creates a complaint
    res = await client.post(
        "/api/v1/complaints",
        json={
            "title": "Private Citizen 1 Issue",
            "description": "Confidential matter concerning property line.",
            "latitude": 12.9800,
            "longitude": 77.6000,
            "address": "Private Lane 1",
        },
        headers={
            "Authorization": f"Bearer {citizen_token}",
            "Idempotency-Key": f"c1-grv-{uuid.uuid4()}",
        },
    )
    complaint_id = res.json()["id"]

    # Citizen 2 lists complaints: sees 0
    c2_list = await client.get(
        "/api/v1/complaints",
        headers={"Authorization": f"Bearer {second_citizen_token}"},
    )
    assert c2_list.status_code == 200
    assert len(c2_list.json()["items"]) == 0

    # Citizen 2 directly fetches Citizen 1's complaint: gets 403 Forbidden
    c2_detail = await client.get(
        f"/api/v1/complaints/{complaint_id}",
        headers={"Authorization": f"Bearer {second_citizen_token}"},
    )
    assert c2_detail.status_code == 403
    assert c2_detail.json()["code"] == "FORBIDDEN_COMPLAINT_ACCESS"

    # Municipal Officer can access Citizen 1's complaint
    officer_detail = await client.get(
        f"/api/v1/complaints/{complaint_id}",
        headers={"Authorization": f"Bearer {officer_token}"},
    )
    assert officer_detail.status_code == 200
    assert officer_detail.json()["id"] == complaint_id


# ==========================================
# 4. Idempotency Replay & Conflict on Complaints
# ==========================================


@pytest.mark.asyncio
async def test_idempotent_complaint_create(
    client: AsyncClient,
    citizen_token: str,
    seeded_wards: list[Ward],
) -> None:
    idem_key = f"idem-grv-{uuid.uuid4()}"
    payload1 = {
        "title": "Water Leakage",
        "description": "Continuous water leakage on main road.",
        "latitude": 12.9800,
        "longitude": 77.6000,
        "address": "Water Works Rd",
    }
    # 1. Initial creation
    res1 = await client.post(
        "/api/v1/complaints",
        json=payload1,
        headers={"Authorization": f"Bearer {citizen_token}", "Idempotency-Key": idem_key},
    )
    assert res1.status_code == 201
    id1 = res1.json()["id"]

    # 2. Replay with identical payload returns exact same response
    res2 = await client.post(
        "/api/v1/complaints",
        json=payload1,
        headers={"Authorization": f"Bearer {citizen_token}", "Idempotency-Key": idem_key},
    )
    assert res2.status_code == 201
    assert res2.json()["id"] == id1
    assert res2.headers.get("X-Idempotent-Replay") == "true"

    # 3. Same key with different payload returns 409 Conflict
    payload_conflict = {
        "title": "Different Title",
        "description": "Completely different issue submitted with same key.",
        "latitude": 12.9800,
        "longitude": 77.6000,
        "address": "Other Place",
    }
    res3 = await client.post(
        "/api/v1/complaints",
        json=payload_conflict,
        headers={"Authorization": f"Bearer {citizen_token}", "Idempotency-Key": idem_key},
    )
    assert res3.status_code == 409
    assert res3.json()["code"] == "IDEMPOTENCY_CONFLICT"


# ==========================================
# 5. Attachment Upload Validation Tests
# ==========================================


@pytest.mark.asyncio
async def test_attachment_upload_valid_image(
    client: AsyncClient,
    citizen_token: str,
) -> None:
    # 1x1 valid PNG image bytes
    png_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00"
        b"\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
        b"\x00\x00IEND\xaeB`\x82"
    )
    files = {"file": ("test_pothole.png", io.BytesIO(png_bytes), "image/png")}
    response = await client.post(
        "/api/v1/complaints/attachments/upload",
        files=files,
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["mime_type"] == "image/png"
    assert data["file_name"] == "test_pothole.png"
    assert "sha256_hash" in data


@pytest.mark.asyncio
async def test_attachment_upload_reject_executable(
    client: AsyncClient,
    citizen_token: str,
) -> None:
    # Disguised executable with PNG mime type
    exe_bytes = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00"
    files = {"file": ("malicious.png", io.BytesIO(exe_bytes), "image/png")}
    response = await client.post(
        "/api/v1/complaints/attachments/upload",
        files=files,
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "EXECUTABLE_FILE_PROHIBITED"


@pytest.mark.asyncio
async def test_attachment_upload_reject_invalid_mime(
    client: AsyncClient,
    citizen_token: str,
) -> None:
    files = {"file": ("notes.txt", io.BytesIO(b"Hello world"), "text/plain")}
    response = await client.post(
        "/api/v1/complaints/attachments/upload",
        files=files,
        headers={"Authorization": f"Bearer {citizen_token}"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_FILE_TYPE"
