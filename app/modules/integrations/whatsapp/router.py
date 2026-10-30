import hashlib
import hmac
import logging
from base64 import b64encode
from typing import Any, Optional
from urllib.parse import urlencode
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.modules.integrations.whatsapp.service import WhatsAppInboundMessage, WhatsAppService
from app.modules.integrations.whatsapp.user_resolver import (
    normalize_phone_number,
    resolve_or_create_whatsapp_citizen,
)

logger = logging.getLogger("app.integrations.whatsapp.router")

whatsapp_router = APIRouter(prefix="/integrations/whatsapp", tags=["WhatsApp Integration"])


def _build_twiml_response(message: str) -> Response:
    escaped_msg = escape(message)
    xml_content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f"<Response><Message>{escaped_msg}</Message></Response>"
    )
    return Response(content=xml_content, media_type="application/xml")


def _is_production() -> bool:
    return settings.ENVIRONMENT.lower() == "production"


def _signature_verification_required() -> bool:
    """Return True if webhook signature verification must be enforced."""
    if _is_production():
        return True
    return settings.WHATSAPP_SIGNATURE_REQUIRED


def _verify_meta_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """Verify X-Hub-Signature-256 header for Meta/JSON webhooks.

    Returns True if the signature is valid.
    Raises HTTPException(403) on failure.
    """
    secret = settings.WHATSAPP_APP_SECRET
    if not secret:
        if _is_production():
            logger.error("WHATSAPP_APP_SECRET is not configured in production — rejecting request.")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Webhook signature verification not configured.",
            )
        if not _signature_verification_required():
            return True
        logger.error("WHATSAPP_APP_SECRET is not configured and signature is required.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhook signature verification not configured.",
        )

    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Hub-Signature-256 header.",
        )

    if not signature_header.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature format.",
        )

    expected_sig = signature_header[len("sha256=") :]
    computed_sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_sig, expected_sig):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature.",
        )
    return True


def _verify_twilio_signature(
    request_url: str, form_params: dict[str, str], signature_header: str | None
) -> bool:
    """Verify X-Twilio-Signature header for Twilio form webhooks.

    Twilio signs: URL + sorted(param keys) with values concatenated, HMAC-SHA1, base64.
    """
    token = settings.TWILIO_AUTH_TOKEN
    if not token:
        if _is_production():
            logger.error("TWILIO_AUTH_TOKEN is not configured in production — rejecting request.")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Webhook signature verification not configured.",
            )
        if not _signature_verification_required():
            return True
        logger.error("TWILIO_AUTH_TOKEN is not configured and signature is required.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhook signature verification not configured.",
        )

    if not signature_header:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing X-Twilio-Signature header.",
        )

    # Build the data string: URL + sorted param key-value pairs concatenated
    data_str = request_url
    for key in sorted(form_params.keys()):
        data_str += key + form_params[key]

    computed_sig = b64encode(
        hmac.new(token.encode("utf-8"), data_str.encode("utf-8"), hashlib.sha1).digest()
    ).decode("utf-8")

    if not hmac.compare_digest(computed_sig, signature_header):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature.",
        )
    return True


@whatsapp_router.get("/webhook", summary="WhatsApp / Meta Hub Verification")
async def verify_or_handle_get(
    request: Request,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
) -> Response:
    """
    Handles Meta WhatsApp Cloud API Webhook Verification only.
    GET-based message processing is no longer supported for security.
    """
    # Meta Webhook Verification challenge
    if hub_mode:
        if hub_mode == "subscribe" and hub_verify_token is not None and hmac.compare_digest(
            hub_verify_token, settings.WHATSAPP_VERIFY_TOKEN
        ):
            logger.info("Meta WhatsApp Cloud API webhook verified successfully.")
            return PlainTextResponse(content=hub_challenge or "", status_code=status.HTTP_200_OK)
        logger.warning("Meta webhook verification failed: mode=%s", hub_mode)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verification token mismatch or invalid mode.",
        )

    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "ok", "message": "WhatsApp webhook endpoint is operational."},
    )


@whatsapp_router.post("/webhook", summary="WhatsApp Inbound Message Webhook")
async def handle_whatsapp_post(
    request: Request,
    db_session: AsyncSession = Depends(get_db),
) -> Response:
    """
    Handles incoming citizen messages asynchronously. Compatible with:
    - Twilio Webhook payloads (application/x-www-form-urlencoded / multipart/form-data)
    - Meta WhatsApp Cloud API payloads (application/json)

    Signature verification is performed BEFORE any parsing, user resolution or DB writes.
    """
    content_type = request.headers.get("content-type", "").lower()
    is_form_request = (
        "application/x-www-form-urlencoded" in content_type
        or "multipart/form-data" in content_type
    )

    # ── Signature verification (BEFORE any parsing) ──────────────────────
    raw_body = await request.body()

    if is_form_request:
        # Twilio-style form request → verify X-Twilio-Signature
        form_data = await request.form()
        form_params: dict[str, str] = {k: str(v) for k, v in form_data.items()}
        request_url = str(request.url)
        twilio_sig = request.headers.get("X-Twilio-Signature")
        _verify_twilio_signature(request_url, form_params, twilio_sig)
    else:
        # JSON/Meta request → verify X-Hub-Signature-256
        meta_sig = request.headers.get("X-Hub-Signature-256")
        _verify_meta_signature(raw_body, meta_sig)

    # ── Parse the verified payload ───────────────────────────────────────
    sender_phone: Optional[str] = None
    body_text: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    media_url: Optional[str] = None
    media_content_type: Optional[str] = None
    message_id: Optional[str] = None

    if is_form_request:
        form_data = await request.form()
        sender_phone = str(form_data.get("From") or "")
        body_text = str(form_data.get("Body") or "") if form_data.get("Body") else None
        message_id = str(form_data.get("MessageSid") or form_data.get("SmsMessageSid") or "") or None

        raw_lat = form_data.get("Latitude")
        raw_lon = form_data.get("Longitude")
        if raw_lat is not None and str(raw_lat).strip():
            try:
                lat = float(str(raw_lat))
            except ValueError:
                pass
        if raw_lon is not None and str(raw_lon).strip():
            try:
                lon = float(str(raw_lon))
            except ValueError:
                pass

        media_url = str(form_data.get("MediaUrl0") or "") or None
        media_content_type = str(form_data.get("MediaContentType0") or "") or None

    else:
        # JSON payload (Meta Cloud API or standard JSON)
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            payload = {}

        # Check for Meta WhatsApp Cloud API structure
        if "entry" in payload:
            try:
                entry = payload["entry"][0]
                changes = entry["changes"][0]
                value = changes["value"]
                messages = value.get("messages", [])
                if not messages:
                    return JSONResponse(
                        content={"status": "acknowledged", "message": "No messages in payload"}
                    )

                msg_item = messages[0]
                message_id = str(msg_item.get("id", "")) or None
                sender_phone = str(msg_item.get("from", ""))
                msg_type = msg_item.get("type", "")

                if msg_type == "text":
                    body_text = msg_item.get("text", {}).get("body")
                elif msg_type == "location":
                    loc = msg_item.get("location", {})
                    lat = float(loc.get("latitude", 0.0))
                    lon = float(loc.get("longitude", 0.0))
                elif msg_type in {"audio", "voice"}:
                    audio_info = msg_item.get("voice") or msg_item.get("audio") or {}
                    media_content_type = audio_info.get("mime_type", "audio/ogg")
                    media_url = audio_info.get("id") or audio_info.get("link")
                elif msg_type == "image":
                    img_info = msg_item.get("image", {})
                    media_content_type = img_info.get("mime_type", "image/jpeg")
                    media_url = img_info.get("id") or img_info.get("link")
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                logger.warning("Error parsing Meta webhook JSON: %s", exc)

        else:
            # Generic JSON support (e.g. from tests or API integrations)
            sender_phone = str(
                payload.get("From")
                or payload.get("from")
                or payload.get("sender_phone")
                or payload.get("phone_number")
                or ""
            )
            message_id = str(payload.get("MessageSid") or payload.get("id") or "") or None
            body_text = payload.get("Body") or payload.get("body") or payload.get("text")
            if "Latitude" in payload or "latitude" in payload:
                lat = float(payload.get("Latitude") or payload.get("latitude") or 0.0)
            if "Longitude" in payload or "longitude" in payload:
                lon = float(payload.get("Longitude") or payload.get("longitude") or 0.0)
            media_url = payload.get("MediaUrl0") or payload.get("media_url")
            media_content_type = payload.get("MediaContentType0") or payload.get(
                "media_content_type"
            )

    if not sender_phone:
        logger.warning("Inbound message missing sender phone number.")
        if is_form_request:
            return _build_twiml_response("Error: Missing sender phone number.")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"error": "Missing sender phone number"},
        )

    # 1. Citizen Identity & Uniqueness Resolution
    user = await resolve_or_create_whatsapp_citizen(db_session, sender_phone)

    # 2. Conversational State Machine Processing
    inbound_msg = WhatsAppInboundMessage(
        sender_phone=normalize_phone_number(sender_phone),
        body=body_text,
        latitude=lat,
        longitude=lon,
        media_url=media_url,
        media_content_type=media_content_type,
    )

    service = WhatsAppService(db_session)
    reply_text = await service.process_inbound_message(user, inbound_msg, message_id=message_id)

    # 3. Format response according to caller type
    if is_form_request:
        return _build_twiml_response(reply_text)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "success", "reply": reply_text},
    )
