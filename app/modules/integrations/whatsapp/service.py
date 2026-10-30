import hashlib
import json
import logging
import re
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import httpx
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.modules.complaints.models.complaint import Attachment, Complaint
from app.modules.complaints.repository.complaint_repository import (
    AttachmentRepository,
    ComplaintRepository,
)
from app.modules.complaints.schemas.complaint import ComplaintFilterParams, CreateComplaintRequest
from app.modules.complaints.service.complaint_service import ComplaintService
from app.modules.identity.models.user import User
from app.modules.integrations.whatsapp.audio_transcriber import (
    WhatsAppAudioTranscriber,
    get_audio_transcriber,
)
from app.modules.routing.service.routing_service import RoutingService

logger = logging.getLogger("app.integrations.whatsapp.service")

UNINTELLIGIBLE_AUDIO_MESSAGE = (
    "आपकी आवाज़ स्पष्ट नहीं थी। कृपया माइक्रोफ़ोन के पास आकर अपनी समस्या दोबारा रिकॉर्ड करें। / "
    "Your audio was unclear. Please record again closer to the microphone."
)

AWAITING_LOCATION_MESSAGE = (
    "We heard your report. Please share your Location using WhatsApp's 📎 Location Pin, and optionally a photo."
)


class WhatsAppInboundMessage(BaseModel):
    """Normalized inbound WhatsApp/Twilio message payload."""

    sender_phone: str
    body: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    media_url: Optional[str] = None
    media_content_type: Optional[str] = None
    media_bytes: Optional[bytes] = None


class WhatsAppSessionStore:
    """
    Session cache with 15-minute TTL backed by Redis under 'wa:session:{phone_number}'.
    Falls back to an in-memory TTL dictionary if Redis is offline or during tests.
    """

    def __init__(self, redis_url: str = settings.REDIS_URL) -> None:
        self.redis_url = redis_url
        self._redis: Optional[Any] = None
        self._redis_checked = False
        self._memory_sessions: dict[str, tuple[float, dict[str, Any]]] = {}
        self._memory_dedup: dict[str, tuple[float, str]] = {}

    async def _get_client(self) -> Optional[Any]:
        if self._redis_checked:
            return self._redis
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_connect_timeout=1,
            )
            await client.ping()
            self._redis = client
            logger.info("WhatsApp session store connected to Redis at %s", self.redis_url)
        except Exception:
            logger.warning("Redis unavailable for WhatsApp session; using in-memory session cache.")
            self._redis = None
        finally:
            self._redis_checked = True
        return self._redis

    async def get_session(self, phone: str) -> dict[str, Any]:
        client = await self._get_client()
        if client is not None:
            try:
                raw = await client.get(f"wa:session:{phone}")
                if raw:
                    return json.loads(raw)  # type: ignore[no-any-return]
                return {}
            except Exception as e:
                logger.warning("Error reading session from Redis: %s", e)

        # In-memory fallback
        if phone in self._memory_sessions:
            expire_at, data = self._memory_sessions[phone]
            if time.time() < expire_at:
                return data
            self._memory_sessions.pop(phone, None)
        return {}

    async def save_session(self, phone: str, data: dict[str, Any], ttl: int = 900) -> None:
        client = await self._get_client()
        if client is not None:
            try:
                await client.set(f"wa:session:{phone}", json.dumps(data), ex=ttl)
                return
            except Exception as e:
                logger.warning("Error saving session to Redis: %s", e)

        self._memory_sessions[phone] = (time.time() + ttl, data)

    async def clear_session(self, phone: str) -> None:
        client = await self._get_client()
        if client is not None:
            try:
                await client.delete(f"wa:session:{phone}")
            except Exception as e:
                logger.warning("Error clearing session from Redis: %s", e)

        self._memory_sessions.pop(phone, None)

    async def is_duplicate(self, phone: str, signature: str, window_seconds: int = 60) -> bool:
        """
        Deduplication guardrail: checks if the exact same voice note or location
        was received from this phone number within window_seconds (default 60s).
        """
        now = time.time()
        client = await self._get_client()
        if client is not None:
            try:
                key = f"wa:dedup:{phone}"
                last_sig = await client.get(key)
                if last_sig == signature:
                    return True
                await client.set(key, signature, ex=window_seconds)
                return False
            except Exception as e:
                logger.warning("Error with Redis dedup check: %s", e)

        if phone in self._memory_dedup:
            expire_at, prev_sig = self._memory_dedup[phone]
            if now < expire_at and prev_sig == signature:
                return True

        self._memory_dedup[phone] = (now + window_seconds, signature)
        return False


_global_session_store = WhatsAppSessionStore()


class WhatsAppService:
    """Conversational state machine and processing engine for WhatsApp grievances."""

    def __init__(
        self,
        session: AsyncSession,
        session_store: Optional[WhatsAppSessionStore] = None,
        audio_transcriber: Optional[WhatsAppAudioTranscriber] = None,
    ) -> None:
        self.session = session
        self.session_store = session_store or _global_session_store
        self.audio_transcriber = audio_transcriber or get_audio_transcriber()
        self.complaint_repo = ComplaintRepository(session)
        self.attachment_repo = AttachmentRepository(session)
        self.complaint_service = ComplaintService(session)

    async def process_inbound_message(
        self,
        user: User,
        msg: WhatsAppInboundMessage,
        message_id: Optional[str] = None,
    ) -> str:
        """Processes an inbound citizen message through the conversational state machine."""
        phone = user.phone_number
        body_text = (msg.body or "").strip()

        # ------------------------------------------------------------------
        # 0. Message ID deduplication (Meta/Twilio)
        # ------------------------------------------------------------------
        if message_id:
            msg_dup = await self.session_store.is_duplicate(phone, f"msgid:{message_id}", window_seconds=86400)
            if msg_dup:
                logger.info("Ignoring duplicate webhook message ID %s for %s", message_id, phone)
                return "Duplicate message received."

        # ------------------------------------------------------------------
        # 1. Status Query Flow
        # ------------------------------------------------------------------
        status_match = self._is_status_query(body_text)
        if status_match:
            return await self._handle_status_query(user, body_text)

        # Retrieve active session
        session_data = await self.session_store.get_session(phone)

        # ------------------------------------------------------------------
        # 1b. Check if user is in AWAITING_CONFIRMATION state
        # ------------------------------------------------------------------
        if session_data.get("state") == "AWAITING_CONFIRMATION":
            cmd = body_text.strip().upper()
            if cmd in {"YES", "Y", "SUBMIT", "HAAN", "हाँ", "ಹೌದು", "CONFIRM"}:
                return await self._finalize_submission(user, session_data)
            elif cmd in {"CANCEL", "NO", "N", "NAHI", "नहीं", "ಬೇಡ", "RESET"}:
                await self.session_store.clear_session(phone)
                return "❌ Grievance submission cancelled. You can report a new grievance anytime by sending a text or voice note."
            else:
                return (
                    "Please reply with *YES* to submit your complaint or *CANCEL* to discard.\n\n"
                    + self._render_confirmation_summary(session_data)
                )

        # ------------------------------------------------------------------
        # 2. Audio / Voice Note Intake
        # ------------------------------------------------------------------
        is_audio = (
            (msg.media_content_type and "audio" in msg.media_content_type.lower())
            or (msg.media_content_type and "ogg" in msg.media_content_type.lower())
            or (msg.media_url and any(msg.media_url.lower().endswith(ext) for ext in [".ogg", ".oga", ".mp3", ".wav", ".amr"]))
        )
        if is_audio:
            return await self._handle_audio_intake(user, msg, session_data)

        # ------------------------------------------------------------------
        # 3. Image / Photo Intake
        # ------------------------------------------------------------------
        is_image = (
            (msg.media_content_type and "image" in msg.media_content_type.lower())
            or (msg.media_url and any(msg.media_url.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]))
        )
        if is_image:
            return await self._handle_image_intake(user, msg, session_data)

        # ------------------------------------------------------------------
        # 4. Location Intake
        # ------------------------------------------------------------------
        if msg.latitude is not None and msg.longitude is not None:
            return await self._handle_location_intake(user, msg.latitude, msg.longitude, session_data)

        # ------------------------------------------------------------------
        # 5. Text Description Intake
        # ------------------------------------------------------------------
        if body_text:
            return await self._handle_text_intake(user, body_text, session_data)

        return (
            "Welcome to Grievance Redressal! 🏛️\n"
            "You can:\n"
            "• Send a text or voice note 🎙️ to report a grievance.\n"
            "• Send 'STATUS' to track your existing grievances."
        )

    # ----------------------------------------------------------------------
    # Helper Methods
    # ----------------------------------------------------------------------

    def _is_status_query(self, text: str) -> bool:
        t = text.strip().lower()
        if t in {"status", "track", "haal", "हाल", "sthiti", "स्थिति"}:
            return True
        # Check if text contains a tracking number pattern (e.g. GRV-20261029-XXXXXX or BLR-2026-XXXXX)
        if re.search(r"\b(?:GRV|BLR)-[A-Za-z0-9\-]+\b", text, re.IGNORECASE):
            return True
        return False

    async def _handle_status_query(self, user: User, text: str) -> str:
        # Check if a specific tracking number was sent
        match = re.search(r"\b((?:GRV|BLR)-[A-Za-z0-9\-]+)\b", text, re.IGNORECASE)
        if match:
            tracking_num = match.group(1).upper()
            complaint = await self.complaint_repo.get_by_tracking_number(tracking_num)
            if not complaint:
                return (
                    f"❌ No grievance found with Tracking ID: {tracking_num}.\n"
                    "Please check the ID and try again, or text 'STATUS' to view your recent complaints."
                )

            dept_name = await self._resolve_department_name(complaint)
            return (
                f"📋 Grievance Status:\n"
                f"Tracking ID: {complaint.tracking_number}\n"
                f"Title: {complaint.original_title}\n"
                f"Department: {dept_name}\n"
                f"Status: {complaint.status}\n"
                f"Ward: {complaint.ward_name or 'Unassigned'}\n\n"
                f"Track anytime: https://frontend-nine-sandy-25.vercel.app/track"
            )

        # General status inquiry: list recent complaints for this citizen
        items, _, _, _ = await self.complaint_repo.list_complaints(
            citizen_id=user.id,
            params=ComplaintFilterParams(limit=5),
        )
        if not items:
            return (
                "You have no registered grievances yet.\n\n"
                "To register a new grievance, simply send a text description or a voice note describing the issue! 🎙️"
            )

        lines = [f"📋 Your Recent Grievances ({len(items)} found):\n"]
        for idx, ranked in enumerate(items, start=1):
            complaint = ranked.complaint
            lines.append(
                f"{idx}. [{complaint.tracking_number}] {complaint.original_title[:40]}\n"
                f"   Status: {complaint.status} | Ward: {complaint.ward_name or 'Unassigned'}"
            )
        lines.append("\nTrack anytime: https://frontend-nine-sandy-25.vercel.app/track")
        return "\n".join(lines)

    async def _handle_audio_intake(
        self,
        user: User,
        msg: WhatsAppInboundMessage,
        session_data: dict[str, Any],
    ) -> str:
        # 1. Fetch audio bytes
        audio_bytes = msg.media_bytes
        if not audio_bytes and msg.media_url:
            audio_bytes = await self._download_media(msg.media_url)

        if not audio_bytes:
            return UNINTELLIGIBLE_AUDIO_MESSAGE

        # 2. Deduplication guardrail
        audio_sig = hashlib.sha256(audio_bytes).hexdigest()
        is_dup = await self.session_store.is_duplicate(user.phone_number, f"audio:{audio_sig}", window_seconds=60)
        if is_dup and session_data.get("draft_description"):
            logger.info("Duplicate voice note detected within 60s from %s; preserving active draft.", user.phone_number)
            return AWAITING_LOCATION_MESSAGE

        # 3. Transcribe audio with gemini-1.5-flash
        content_type = msg.media_content_type or "audio/ogg"
        res = await self.audio_transcriber.transcribe(audio_bytes, mime_type=content_type)
        if not res.is_intelligible or not res.text.strip():
            logger.info("Audio from %s marked as unintelligible.", user.phone_number)
            return UNINTELLIGIBLE_AUDIO_MESSAGE

        # 4. Save draft in session
        text = res.text.strip()
        session_data["draft_description"] = text
        session_data["draft_title"] = text[:80] + ("..." if len(text) > 80 else "")
        session_data["detected_language"] = res.language
        session_data["state"] = "AWAITING_LOCATION_OR_MEDIA"

        # If location was already provided in message or session, transition to confirmation
        lat = msg.latitude or session_data.get("latitude")
        lon = msg.longitude or session_data.get("longitude")
        if lat is not None and lon is not None:
            session_data["latitude"] = lat
            session_data["longitude"] = lon
            session_data["state"] = "AWAITING_CONFIRMATION"
            await self.session_store.save_session(user.phone_number, session_data)
            return self._render_confirmation_summary(session_data)

        await self.session_store.save_session(user.phone_number, session_data)
        return AWAITING_LOCATION_MESSAGE

    async def _handle_text_intake(
        self,
        user: User,
        text: str,
        session_data: dict[str, Any],
    ) -> str:
        # Deduplication check
        text_sig = hashlib.sha256(text.encode("utf-8")).hexdigest()
        is_dup = await self.session_store.is_duplicate(user.phone_number, f"text:{text_sig}", window_seconds=60)
        if is_dup and session_data.get("draft_description"):
            logger.info("Duplicate text detected within 60s from %s; preserving active draft.", user.phone_number)
            return AWAITING_LOCATION_MESSAGE

        # Language detection heuristic
        has_devanagari = any("\u0900" <= ch <= "\u097f" for ch in text)
        has_kannada = any("\u0c80" <= ch <= "\u0cff" for ch in text)
        lang = "hi" if has_devanagari else ("kn" if has_kannada else "en")

        session_data["draft_description"] = text
        session_data["draft_title"] = text[:80] + ("..." if len(text) > 80 else "")
        session_data["detected_language"] = lang
        session_data["state"] = "AWAITING_LOCATION_OR_MEDIA"

        lat = session_data.get("latitude")
        lon = session_data.get("longitude")
        if lat is not None and lon is not None:
            session_data["state"] = "AWAITING_CONFIRMATION"
            await self.session_store.save_session(user.phone_number, session_data)
            return self._render_confirmation_summary(session_data)

        await self.session_store.save_session(user.phone_number, session_data)
        return AWAITING_LOCATION_MESSAGE

    async def _handle_location_intake(
        self,
        user: User,
        lat: float,
        lon: float,
        session_data: dict[str, Any],
    ) -> str:
        # Deduplication check
        loc_sig = f"loc:{lat:.4f},{lon:.4f}"
        is_dup = await self.session_store.is_duplicate(user.phone_number, loc_sig, window_seconds=60)
        if is_dup and not session_data.get("draft_description"):
            return "We already received this location pin. 📍 Please describe the issue via text or voice note."

        session_data["latitude"] = lat
        session_data["longitude"] = lon

        # If draft description is already present, transition to confirmation
        if session_data.get("draft_description"):
            session_data["state"] = "AWAITING_CONFIRMATION"
            await self.session_store.save_session(user.phone_number, session_data)
            return self._render_confirmation_summary(session_data)

        # Awaiting description
        session_data["state"] = "AWAITING_DESCRIPTION"
        await self.session_store.save_session(user.phone_number, session_data)
        return "Location received! 📍 Now please send a text description or a voice note describing the issue."

    async def _handle_image_intake(
        self,
        user: User,
        msg: WhatsAppInboundMessage,
        session_data: dict[str, Any],
    ) -> str:
        image_bytes = msg.media_bytes
        if not image_bytes and msg.media_url:
            image_bytes = await self._download_media(msg.media_url)

        if image_bytes:
            content_type = msg.media_content_type or "image/jpeg"
            attachment = await self._store_attachment(user, image_bytes, content_type)
            att_ids = session_data.setdefault("attachment_ids", [])
            att_ids.append(str(attachment.id))

        if session_data.get("draft_description") and session_data.get("latitude") is not None:
            session_data["state"] = "AWAITING_CONFIRMATION"
            await self.session_store.save_session(user.phone_number, session_data)
            return self._render_confirmation_summary(session_data)

        await self.session_store.save_session(user.phone_number, session_data)
        if session_data.get("draft_description"):
            return "Photo received! 📸 Please share your Location using WhatsApp's 📎 Location Pin to finalize."
        return "Photo received! 📸 Please share a description of the grievance via text or a voice note."

    def _render_confirmation_summary(self, session_data: dict[str, Any]) -> str:
        """Presents explicit summary confirmation before final submission."""
        title = session_data.get("draft_title", "Grievance Report")
        desc = session_data.get("draft_description", "")
        lat = session_data.get("latitude", 0.0)
        lon = session_data.get("longitude", 0.0)
        photo_count = len(session_data.get("attachment_ids", []))
        photos_txt = f"{photo_count} photo(s) attached" if photo_count > 0 else "None"

        return (
            "📝 *Please Confirm Your Grievance Submission:*\n\n"
            f"• *Title:* {title}\n"
            f"• *Description:* {desc}\n"
            f"• *Location:* 📍 ({lat:.4f}, {lon:.4f})\n"
            f"• *Photos:* 📸 {photos_txt}\n\n"
            "Reply with *YES* to register this grievance, or *CANCEL* to discard."
        )

    async def _finalize_submission(
        self,
        user: User,
        session_data: dict[str, Any],
    ) -> str:
        """Constructs and submits complaint via ComplaintService, then returns formatted confirmation."""
        desc = session_data.get("draft_description", "").strip()
        if len(desc) < 10:
            desc = f"Citizen Grievance via WhatsApp: {desc}"

        title = session_data.get("draft_title", "").strip()
        if len(title) < 3:
            title = desc[:60] if len(desc[:60]) >= 3 else "Citizen Grievance"

        lat = float(session_data.get("latitude", 12.9716))
        lon = float(session_data.get("longitude", 77.5946))
        lang = session_data.get("detected_language", "en")

        raw_att_ids = session_data.get("attachment_ids", [])
        attachment_uuids = [uuid.UUID(aid) for aid in raw_att_ids]

        address = f"GPS Pin: ({lat:.5f}, {lon:.5f})"

        payload = CreateComplaintRequest(
            title=title,
            description=desc,
            original_language=lang,
            latitude=lat,
            longitude=lon,
            address=address,
            channel="WHATSAPP",
            attachment_ids=attachment_uuids,
        )

        complaint = await self.complaint_service.create_complaint(user, payload)
        await self.session.commit()

        # Clear session upon successful submission
        await self.session_store.clear_session(user.phone_number)

        # Department resolution
        dept_name = await self._resolve_department_name(complaint)

        # Standard required template response
        return (
            f"✅ Grievance Registered!\n"
            f"Tracking ID: {complaint.tracking_number}\n"
            f"Department: {dept_name}\n"
            f"Status: Submitted (Awaiting Officer Triage)\n\n"
            f"Track anytime: https://frontend-nine-sandy-25.vercel.app/track\n"
            f"Or simply text \"STATUS\" to this chat."
        )

    async def _resolve_department_name(self, complaint: Complaint) -> str:
        """Determines best-matching department for the complaint."""
        try:
            routing_service = RoutingService(self.session)
            rec = await routing_service.generate_routing_recommendation(complaint.id)
            if rec.recommended_departments:
                name = rec.recommended_departments[0].get("department_name")
                if name:
                    return str(name)
        except Exception:
            pass
        return "Roads and Infrastructure"

    async def _store_attachment(
        self,
        user: User,
        content: bytes,
        content_type: str,
    ) -> Attachment:
        sha256 = hashlib.sha256(content).hexdigest()
        ext = ".jpg"
        if "png" in content_type:
            ext = ".png"
        elif "webp" in content_type:
            ext = ".webp"

        user_dir = Path(settings.LOCAL_UPLOAD_DIR) / str(user.id)
        user_dir.mkdir(parents=True, exist_ok=True)
        unique_name = f"{uuid.uuid4().hex}{ext}"
        target_path = user_dir / unique_name
        with open(target_path, "wb") as f:
            f.write(content)

        file_url = f"/uploads/{user.id}/{unique_name}"
        attachment = Attachment(
            uploader_id=user.id,
            file_url=file_url,
            file_name=f"whatsapp_{unique_name}",
            mime_type=content_type,
            file_size_bytes=len(content),
            sha256_hash=sha256,
            attachment_type="CITIZEN_SUBMISSION",
        )
        return await self.attachment_repo.create(attachment)

    async def _download_media(self, url: str) -> Optional[bytes]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                headers = {}
                if settings.WHATSAPP_ACCESS_TOKEN and "facebook.com" in url:
                    headers["Authorization"] = f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    return resp.content
        except Exception as e:
            logger.warning("Failed to fetch WhatsApp media from %s: %s", url, e)
        return None
