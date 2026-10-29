import logging
from typing import Any, Optional
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


@whatsapp_router.get("/webhook", summary="WhatsApp / Meta Hub Verification & Twilio GET Webhook")
async def verify_or_handle_get(
    request: Request,
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    # Query parameters for Twilio GET compatibility
    from_number: Optional[str] = Query(None, alias="From"),
    body: Optional[str] = Query(None, alias="Body"),
    latitude: Optional[float] = Query(None, alias="Latitude"),
    longitude: Optional[float] = Query(None, alias="Longitude"),
    media_url: Optional[str] = Query(None, alias="MediaUrl0"),
    media_content_type: Optional[str] = Query(None, alias="MediaContentType0"),
    db_session: AsyncSession = Depends(get_db),
) -> Response:
    """
    Handles:
    1. Meta WhatsApp Cloud API Webhook Verification (hub.mode, hub.challenge, hub.verify_token).
    2. Twilio Webhook GET queries (From, Body, Latitude, Longitude, MediaUrl0).
    """
    # 1. Meta Webhook Verification challenge
    if hub_mode:
        if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
            logger.info("Meta WhatsApp Cloud API webhook verified successfully.")
            return PlainTextResponse(content=hub_challenge or "", status_code=status.HTTP_200_OK)
        logger.warning(
            "Meta webhook verification failed: mode=%s, token=%s", hub_mode, hub_verify_token
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verification token mismatch or invalid mode.",
        )

    # 2. Twilio GET Webhook simulation
    if from_number:
        try:
            user = await resolve_or_create_whatsapp_citizen(db_session, from_number)
            inbound = WhatsAppInboundMessage(
                sender_phone=normalize_phone_number(from_number),
                body=body,
                latitude=latitude,
                longitude=longitude,
                media_url=media_url,
                media_content_type=media_content_type,
            )
            service = WhatsAppService(db_session)
            reply_text = await service.process_inbound_message(user, inbound)
            return _build_twiml_response(reply_text)
        except Exception as exc:
            logger.exception("Error processing Twilio GET webhook: %s", exc)
            return _build_twiml_response(
                "An error occurred while processing your request. Please try again."
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
    """
    content_type = request.headers.get("content-type", "").lower()
    sender_phone: Optional[str] = None
    body_text: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    media_url: Optional[str] = None
    media_content_type: Optional[str] = None
    is_form_request = False

    if "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type:
        is_form_request = True
        form_data = await request.form()
        sender_phone = str(form_data.get("From") or "")
        body_text = str(form_data.get("Body") or "") if form_data.get("Body") else None

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
    reply_text = await service.process_inbound_message(user, inbound_msg)

    # 3. Format response according to caller type
    if is_form_request:
        return _build_twiml_response(reply_text)
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"status": "success", "reply": reply_text},
    )
