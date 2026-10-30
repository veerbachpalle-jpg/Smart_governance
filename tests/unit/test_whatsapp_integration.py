import hashlib
import hmac
import json
from base64 import b64encode
from unittest.mock import patch
from urllib.parse import urlencode

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.complaints.models.complaint import Complaint, Ward
from app.modules.identity.models.user import Department, User
from app.modules.integrations.whatsapp.audio_transcriber import WhatsAppAudioTranscriber
from app.modules.integrations.whatsapp.service import (
    AWAITING_LOCATION_MESSAGE,
    UNINTELLIGIBLE_AUDIO_MESSAGE,
    WhatsAppInboundMessage,
    WhatsAppService,
    WhatsAppSessionStore,
)
from app.modules.integrations.whatsapp.user_resolver import (
    normalize_phone_number,
    resolve_or_create_whatsapp_citizen,
)

# ── Test helpers for webhook signature computation ────────────────────────────

TEST_META_SECRET = "test_meta_app_secret_1234"
TEST_TWILIO_TOKEN = "test_twilio_auth_token_5678"


def _compute_meta_signature(body: bytes, secret: str = TEST_META_SECRET) -> str:
    """Compute X-Hub-Signature-256 value for a given raw body."""
    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _compute_twilio_signature(
    url: str, params: dict[str, str], token: str = TEST_TWILIO_TOKEN
) -> str:
    """Compute X-Twilio-Signature value for a given URL and form params."""
    data_str = url
    for key in sorted(params.keys()):
        data_str += key + params[key]
    sig = b64encode(
        hmac.new(token.encode("utf-8"), data_str.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")
    return sig


@pytest.fixture
async def sample_ward(db_session: AsyncSession) -> Ward:
    ward = Ward(
        ward_number=101,
        name="MG Road Ward",
        boundary_geojson={
            "type": "Polygon",
            "coordinates": [
                [[77.50, 12.90], [77.65, 12.90], [77.65, 13.05], [77.50, 13.05], [77.50, 12.90]]
            ],
        },
        min_lat=12.90,
        max_lat=13.05,
        min_lon=77.50,
        max_lon=77.65,
    )
    db_session.add(ward)
    await db_session.commit()
    await db_session.refresh(ward)
    return ward


@pytest.fixture
async def sample_department(db_session: AsyncSession) -> Department:
    dept = Department(
        code="ROADS",
        name="Roads and Infrastructure",
        description="Handles road repairs, potholes and footpaths",
        is_active=True,
    )
    db_session.add(dept)
    await db_session.commit()
    await db_session.refresh(dept)
    return dept


# ==============================================================================
# 1. Citizen Identity & Uniqueness Tests (user_resolver.py)
# ==============================================================================


def test_normalize_phone_number() -> None:
    assert normalize_phone_number("whatsapp:+919876543210") == "+919876543210"
    assert normalize_phone_number("+919876543210") == "+919876543210"
    assert normalize_phone_number("919876543210") == "+919876543210"
    assert normalize_phone_number("+91 98765-43210") == "+919876543210"
    assert normalize_phone_number("+1 (555) 123-4567") == "+15551234567"

    with pytest.raises(ValueError):
        normalize_phone_number("")


@pytest.mark.asyncio
async def test_resolve_or_create_new_whatsapp_citizen(db_session: AsyncSession) -> None:
    raw_phone = "whatsapp:+919876543210"
    user = await resolve_or_create_whatsapp_citizen(db_session, raw_phone)

    assert user.id is not None
    assert user.phone_number == "+919876543210"
    assert user.email == "919876543210@wa.grievance.local"
    assert user.role == "citizen"
    assert user.is_active is True
    assert user.password_hash.startswith("$argon2")

    # Check CitizenProfile
    profile = user.citizen_profile
    assert profile is not None
    assert profile.full_name == "WhatsApp Citizen"
    assert profile.notification_preference == "whatsapp"
    assert profile.preferred_language == "hi"


@pytest.mark.asyncio
async def test_resolve_existing_whatsapp_citizen(db_session: AsyncSession) -> None:
    raw_phone = "+919876543210"
    user_first = await resolve_or_create_whatsapp_citizen(db_session, raw_phone)
    await db_session.commit()

    # Second call with 'whatsapp:' prefix should return the exact same user
    user_second = await resolve_or_create_whatsapp_citizen(
        db_session, "whatsapp:+919876543210"
    )
    assert user_second.id == user_first.id
    assert user_second.email == user_first.email

    # Verify no duplicate user created in database
    stmt = select(User).where(User.phone_number == "+919876543210")
    results = list((await db_session.execute(stmt)).scalars().all())
    assert len(results) == 1


# ==============================================================================
# 2. Audio Transcription & Safe Error Handling Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_audio_transcriber_intelligible_mock() -> None:
    transcriber = WhatsAppAudioTranscriber(api_key=None)

    # Hindi mock audio bytes
    audio_hi = b"Grievance in Hindi: \xe0\xa4\xb8\xe0\xa4\xa1\xe0\xa4\xbc\xe0\xa4\x95 \xe0\xa4\xaa\xe0\xa4\xb0 \xe0\xa4\x97\xe0\xa4\xa1\xe0\xa4\x8d\xe0\xa4\xa2\xe0\xa4\xbe \xe0\xa4\xb9\xe0\xa4\x88"
    res_hi = await transcriber.transcribe(audio_hi, mime_type="audio/ogg")
    assert res_hi.is_intelligible is True
    assert res_hi.language == "hi"
    assert len(res_hi.text) > 0

    # Kannada mock audio bytes
    audio_kn = "Kannada: ರಸ್ತೆಯಲ್ಲಿ ದೊಡ್ಡ ಗುಂಡಿ ಬಿದ್ದಿದೆ".encode("utf-8")
    res_kn = await transcriber.transcribe(audio_kn, mime_type="audio/ogg")
    assert res_kn.is_intelligible is True
    assert res_kn.language == "kn"

    # English mock audio bytes
    audio_en = b"Streetlight is not working on 100ft road since two weeks"
    res_en = await transcriber.transcribe(audio_en, mime_type="audio/ogg")
    assert res_en.is_intelligible is True
    assert res_en.language == "en"


@pytest.mark.asyncio
async def test_audio_transcriber_unintelligible() -> None:
    transcriber = WhatsAppAudioTranscriber(api_key=None)

    # Short / truncated audio
    res_short = await transcriber.transcribe(b"too_short", mime_type="audio/ogg")
    assert res_short.is_intelligible is False

    # Audio marked as unintelligible
    res_unintelligible = await transcriber.transcribe(b"UNINTELLIGIBLE_NOISE_123456789")
    assert res_unintelligible.is_intelligible is False


# ==============================================================================
# 3. Conversational State Machine & Flows Tests (service.py)
# ==============================================================================


@pytest.mark.asyncio
async def test_status_query_flow_no_complaints(db_session: AsyncSession) -> None:
    user = await resolve_or_create_whatsapp_citizen(db_session, "+919876540001")
    service = WhatsAppService(db_session)

    # Citizen texts 'STATUS'
    msg = WhatsAppInboundMessage(sender_phone="+919876540001", body="STATUS")
    reply = await service.process_inbound_message(user, msg)
    assert "You have no registered grievances yet" in reply


@pytest.mark.asyncio
async def test_status_query_flow_with_complaints(
    db_session: AsyncSession, sample_ward: Ward
) -> None:
    user = await resolve_or_create_whatsapp_citizen(db_session, "+919876540002")

    # Manually create a complaint for this citizen
    complaint = Complaint(
        tracking_number="GRV-20261029-TEST01",
        citizen_id=user.id,
        original_title="Open manhole near park",
        original_description="Uncovered manhole causing safety hazard for pedestrians",
        original_language="en",
        latitude=12.9716,
        longitude=77.5946,
        address="Near MG Road",
        ward_id=sample_ward.id,
        ward_name=sample_ward.name,
        channel="WHATSAPP",
        status="SUBMITTED",
    )
    db_session.add(complaint)
    await db_session.commit()

    service = WhatsAppService(db_session)

    # 1. General status check
    msg = WhatsAppInboundMessage(sender_phone="+919876540002", body="status")
    reply = await service.process_inbound_message(user, msg)
    assert "GRV-20261029-TEST01" in reply
    assert "Open manhole near park" in reply
    assert "https://frontend-nine-sandy-25.vercel.app/track" in reply

    # 2. Specific tracking number check
    msg_specific = WhatsAppInboundMessage(
        sender_phone="+919876540002", body="GRV-20261029-TEST01"
    )
    reply_specific = await service.process_inbound_message(user, msg_specific)
    assert "📋 Grievance Status" in reply_specific
    assert "GRV-20261029-TEST01" in reply_specific
    assert "Status: SUBMITTED" in reply_specific

    # 3. Non-existent tracking number
    msg_missing = WhatsAppInboundMessage(
        sender_phone="+919876540002", body="GRV-99999999-NOTFOUND"
    )
    reply_missing = await service.process_inbound_message(user, msg_missing)
    assert "❌ No grievance found" in reply_missing


@pytest.mark.asyncio
async def test_new_complaint_flow_text_then_location(
    db_session: AsyncSession, sample_ward: Ward, sample_department: Department
) -> None:
    user = await resolve_or_create_whatsapp_citizen(db_session, "+919876540003")
    store = WhatsAppSessionStore()
    service = WhatsAppService(db_session, session_store=store)

    # Step 1: Citizen sends description
    msg_desc = WhatsAppInboundMessage(
        sender_phone="+919876540003",
        body="Streetlight fixture broken and dark near MG Road Metro",
    )
    reply_desc = await service.process_inbound_message(user, msg_desc)
    assert reply_desc == AWAITING_LOCATION_MESSAGE

    # Verify session in store
    session_data = await store.get_session("+919876540003")
    assert session_data.get("state") == "AWAITING_LOCATION_OR_MEDIA"
    assert "Streetlight fixture broken" in session_data.get("draft_description", "")

    # Step 2: Citizen sends Location Pin -> triggers summary confirmation
    msg_loc = WhatsAppInboundMessage(
        sender_phone="+919876540003",
        latitude=12.9716,
        longitude=77.5946,
    )
    reply_loc = await service.process_inbound_message(user, msg_loc)
    assert "Please Confirm Your Grievance Submission" in reply_loc
    assert "Reply with *YES* to register this grievance" in reply_loc

    # Step 3: Citizen replies YES to confirm
    msg_confirm = WhatsAppInboundMessage(
        sender_phone="+919876540003",
        body="YES",
    )
    reply_confirm = await service.process_inbound_message(user, msg_confirm)

    # Verify submission response format
    assert "✅ Grievance Registered!" in reply_confirm
    assert "Tracking ID: GRV-" in reply_confirm
    assert "Department:" in reply_confirm
    assert "Status: Submitted (Awaiting Officer Triage)" in reply_confirm
    assert "Track anytime: https://frontend-nine-sandy-25.vercel.app/track" in reply_confirm
    assert 'Or simply text "STATUS" to this chat.' in reply_confirm

    # Verify session cleared
    cleared_session = await store.get_session("+919876540003")
    assert cleared_session == {}

    # Verify Complaint was created in database with channel WHATSAPP
    stmt = select(Complaint).where(Complaint.citizen_id == user.id)
    complaint = (await db_session.execute(stmt)).scalar_one()
    assert complaint.channel == "WHATSAPP"
    assert complaint.status == "SUBMITTED"
    assert complaint.latitude == 12.9716
    assert complaint.longitude == 77.5946


@pytest.mark.asyncio
async def test_new_complaint_flow_voice_note_intake(
    db_session: AsyncSession, sample_ward: Ward
) -> None:
    user = await resolve_or_create_whatsapp_citizen(db_session, "+919876540004")
    store = WhatsAppSessionStore()
    service = WhatsAppService(db_session, session_store=store)

    # 1. Unintelligible voice note
    msg_unintelligible = WhatsAppInboundMessage(
        sender_phone="+919876540004",
        media_bytes=b"UNINTELLIGIBLE_AUDIO_SAMPLE",
        media_content_type="audio/ogg",
    )
    reply_fail = await service.process_inbound_message(user, msg_unintelligible)
    assert reply_fail == UNINTELLIGIBLE_AUDIO_MESSAGE

    # 2. Intelligible voice note
    msg_voice = WhatsAppInboundMessage(
        sender_phone="+919876540004",
        media_bytes=b"Pipe burst flooding road with drinking water",
        media_content_type="audio/ogg",
    )
    reply_voice = await service.process_inbound_message(user, msg_voice)
    assert reply_voice == AWAITING_LOCATION_MESSAGE

    # 3. Location Pin prompts for confirmation
    msg_loc = WhatsAppInboundMessage(
        sender_phone="+919876540004",
        latitude=12.9720,
        longitude=77.5950,
    )
    reply_summary = await service.process_inbound_message(user, msg_loc)
    assert "Please Confirm Your Grievance Submission" in reply_summary

    # 4. Reply YES to confirm
    msg_confirm = WhatsAppInboundMessage(
        sender_phone="+919876540004",
        body="YES",
    )
    reply_final = await service.process_inbound_message(user, msg_confirm)
    assert "✅ Grievance Registered!" in reply_final
    assert "Tracking ID:" in reply_final


@pytest.mark.asyncio
async def test_deduplication_guardrail(db_session: AsyncSession) -> None:
    user = await resolve_or_create_whatsapp_citizen(db_session, "+919876540005")
    store = WhatsAppSessionStore()
    service = WhatsAppService(db_session, session_store=store)

    audio_bytes = b"Exact duplicate voice recording bytes 12345"
    msg_1 = WhatsAppInboundMessage(
        sender_phone="+919876540005",
        media_bytes=audio_bytes,
        media_content_type="audio/ogg",
    )
    reply_1 = await service.process_inbound_message(user, msg_1)
    assert reply_1 == AWAITING_LOCATION_MESSAGE

    # Immediately resend the exact same audio bytes within 60s
    msg_2 = WhatsAppInboundMessage(
        sender_phone="+919876540005",
        media_bytes=audio_bytes,
        media_content_type="audio/ogg",
    )
    reply_2 = await service.process_inbound_message(user, msg_2)
    # Deduplication handles this gracefully without overwriting/resetting or creating complaints
    assert reply_2 == AWAITING_LOCATION_MESSAGE


# ==============================================================================
# 4. Webhook Router HTTP Endpoints Tests (router.py)
# ==============================================================================


@pytest.mark.asyncio
async def test_meta_webhook_verification(client: AsyncClient) -> None:
    # 1. Valid verification challenge
    resp = await client.get(
        "/api/v1/integrations/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "challenge_token_9876",
            "hub.verify_token": settings.WHATSAPP_VERIFY_TOKEN,
        },
    )
    assert resp.status_code == 200
    assert resp.text == "challenge_token_9876"

    # 2. Invalid verification token -> 403 Forbidden
    resp_invalid = await client.get(
        "/api/v1/integrations/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.challenge": "challenge_token_9876",
            "hub.verify_token": "wrong_token",
        },
    )
    assert resp_invalid.status_code == 403


@pytest.mark.asyncio
@patch.object(settings, "WHATSAPP_SIGNATURE_REQUIRED", False)
@patch.object(settings, "ENVIRONMENT", "development")
@patch.object(settings, "TWILIO_AUTH_TOKEN", None)
async def test_twilio_webhook_post_flow_unsigned_dev(
    client: AsyncClient, sample_ward: Ward, sample_department: Department
) -> None:
    """In dev mode with WHATSAPP_SIGNATURE_REQUIRED=False, unsigned requests are allowed."""
    # Step 1: Twilio form POST message
    resp_1 = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        data={
            "From": "whatsapp:+919876541111",
            "Body": "Huge pothole on middle of MG Road",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp_1.status_code == 200
    assert "application/xml" in resp_1.headers.get("content-type", "")
    assert "<Response><Message>" in resp_1.text
    assert "We heard your report" in resp_1.text

    # Step 2: Twilio form POST location -> prompts confirmation
    resp_2 = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        data={
            "From": "whatsapp:+919876541111",
            "Latitude": "12.9716",
            "Longitude": "77.5946",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp_2.status_code == 200
    assert "Please Confirm Your Grievance Submission" in resp_2.text

    # Step 3: Twilio form POST YES confirmation
    resp_3 = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        data={
            "From": "whatsapp:+919876541111",
            "Body": "YES",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp_3.status_code == 200
    assert "✅ Grievance Registered!" in resp_3.text
    assert "Tracking ID:" in resp_3.text


@pytest.mark.asyncio
@patch.object(settings, "WHATSAPP_APP_SECRET", TEST_META_SECRET)
async def test_twilio_webhook_post_flow_signed(
    client: AsyncClient, sample_ward: Ward, sample_department: Department
) -> None:
    """Twilio-style form POST with proper X-Twilio-Signature."""
    with patch.object(settings, "TWILIO_AUTH_TOKEN", TEST_TWILIO_TOKEN):
        # We need to compute the signature for the exact URL that the test client uses
        base_url = "http://test/api/v1/integrations/whatsapp/webhook"
        form_params = {
            "From": "whatsapp:+919876541112",
            "Body": "Huge pothole on middle of MG Road",
        }
        sig = _compute_twilio_signature(base_url, form_params)

        resp_1 = await client.post(
            "/api/v1/integrations/whatsapp/webhook",
            data=form_params,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Twilio-Signature": sig,
            },
        )
        assert resp_1.status_code == 200
        assert "We heard your report" in resp_1.text


@pytest.mark.asyncio
@patch.object(settings, "WHATSAPP_APP_SECRET", TEST_META_SECRET)
@patch.object(settings, "ENVIRONMENT", "development")
async def test_meta_cloud_api_json_post_flow(
    client: AsyncClient, sample_ward: Ward, sample_department: Department
) -> None:
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "wa_biz_account_1",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "messages": [
                                {
                                    "from": "919876542222",
                                    "id": "wamid.12345",
                                    "type": "text",
                                    "text": {"body": "status"},
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = _compute_meta_signature(raw_body)

    resp = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "You have no registered grievances yet" in data["reply"]


# ==============================================================================
# 5. Webhook Signature Verification Security Tests
# ==============================================================================


@pytest.mark.asyncio
@patch.object(settings, "WHATSAPP_APP_SECRET", TEST_META_SECRET)
async def test_meta_json_post_missing_signature_returns_403(client: AsyncClient) -> None:
    """POST JSON with no X-Hub-Signature-256 header -> 403."""
    payload = {"From": "919876540001", "Body": "hello"}
    resp = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=payload,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
@patch.object(settings, "WHATSAPP_APP_SECRET", TEST_META_SECRET)
async def test_meta_json_post_bad_signature_returns_403(client: AsyncClient) -> None:
    """POST JSON with incorrect X-Hub-Signature-256 header -> 403."""
    payload = {"From": "919876540001", "Body": "hello"}
    resp = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=payload,
        headers={"X-Hub-Signature-256": "sha256=deadbeef0000"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
@patch.object(settings, "WHATSAPP_APP_SECRET", TEST_META_SECRET)
async def test_meta_json_post_valid_signature_returns_200(client: AsyncClient) -> None:
    """POST JSON with correct X-Hub-Signature-256 header -> 200."""
    payload = {"From": "919876540001", "Body": "STATUS"}
    raw_body = json.dumps(payload).encode("utf-8")
    sig = _compute_meta_signature(raw_body)
    resp = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": sig,
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
@patch.object(settings, "TWILIO_AUTH_TOKEN", TEST_TWILIO_TOKEN)
async def test_twilio_form_post_missing_signature_returns_403(client: AsyncClient) -> None:
    """POST form data with no X-Twilio-Signature header -> 403."""
    resp = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        data={"From": "whatsapp:+919876540001", "Body": "hello"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
@patch.object(settings, "TWILIO_AUTH_TOKEN", TEST_TWILIO_TOKEN)
async def test_twilio_form_post_bad_signature_returns_403(client: AsyncClient) -> None:
    """POST form data with incorrect X-Twilio-Signature -> 403."""
    resp = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        data={"From": "whatsapp:+919876540001", "Body": "hello"},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": "badsignaturehere==",
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
@patch.object(settings, "TWILIO_AUTH_TOKEN", TEST_TWILIO_TOKEN)
async def test_twilio_form_post_valid_signature_returns_200(client: AsyncClient) -> None:
    """POST form data with correct X-Twilio-Signature -> 200."""
    base_url = "http://test/api/v1/integrations/whatsapp/webhook"
    form_params = {"From": "whatsapp:+919876540001", "Body": "STATUS"}
    sig = _compute_twilio_signature(base_url, form_params)

    resp = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        data=form_params,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Twilio-Signature": sig,
        },
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
@patch.object(settings, "ENVIRONMENT", "production")
@patch.object(settings, "WHATSAPP_APP_SECRET", None)
async def test_production_no_secret_fails_closed_json(client: AsyncClient) -> None:
    """In production, if WHATSAPP_APP_SECRET is not configured, reject with 403."""
    payload = {"From": "919876540001", "Body": "hello"}
    resp = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        json=payload,
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
@patch.object(settings, "ENVIRONMENT", "production")
@patch.object(settings, "TWILIO_AUTH_TOKEN", None)
async def test_production_no_token_fails_closed_form(client: AsyncClient) -> None:
    """In production, if TWILIO_AUTH_TOKEN is not configured, reject with 403."""
    resp = await client.post(
        "/api/v1/integrations/whatsapp/webhook",
        data={"From": "whatsapp:+919876540001", "Body": "hello"},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_webhook_no_longer_processes_messages(client: AsyncClient) -> None:
    """GET with From/Body params should no longer process messages (Twilio GET removed)."""
    resp = await client.get(
        "/api/v1/integrations/whatsapp/webhook",
        params={
            "From": "whatsapp:+919876543333",
            "Body": "STATUS",
        },
    )
    assert resp.status_code == 200
    # Should return the operational status, NOT process the message
    data = resp.json()
    assert data.get("status") == "ok"
    assert "operational" in data.get("message", "").lower()
