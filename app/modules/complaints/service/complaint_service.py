import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import UploadFile
from shapely.geometry import Point, shape
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BadRequestError, ForbiddenError, NotFoundError
from app.core.outbox import enqueue_outbox_event
from app.core.pagination import PaginatedResponse
from app.modules.audit.service.audit_service import AuditService
from app.modules.complaints.models.complaint import Attachment, Complaint
from app.modules.complaints.repository.complaint_repository import (
    AttachmentRepository,
    ComplaintRepository,
    WardRepository,
)
from app.modules.complaints.schemas.complaint import (
    ComplaintFilterParams,
    ComplaintResponse,
    CreateComplaintRequest,
    PublicTrackingResponse,
)
from app.modules.identity.models.user import User

ALLOWED_MIME_TYPES = {
    "image/jpeg": [".jpg", ".jpeg"],
    "image/png": [".png"],
    "image/webp": [".webp"],
    "application/pdf": [".pdf"],
}
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MB
UPLOAD_DIR = Path("uploads")


class WardLookupService:
    def __init__(self, session: AsyncSession) -> None:
        self.ward_repo = WardRepository(session)

    async def lookup_ward(
        self, latitude: float, longitude: float
    ) -> tuple[Optional[uuid.UUID], Optional[str]]:
        """Identifies municipal ward from GPS coordinates using point-in-polygon matching."""
        wards = await self.ward_repo.list_all()
        if not wards:
            return None, "Unassigned Ward"

        point = Point(longitude, latitude)
        for ward in wards:
            try:
                poly = shape(ward.boundary_geojson)
                if poly.contains(point) or poly.touches(point):
                    return ward.id, ward.name
            except Exception:
                # Fallback to bounding box if geojson parse fails
                if (
                    ward.min_lat <= latitude <= ward.max_lat
                    and ward.min_lon <= longitude <= ward.max_lon
                ):
                    return ward.id, ward.name

        # Default to first ward if outside known municipal boundaries
        return wards[0].id, wards[0].name


class ComplaintService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.complaint_repo = ComplaintRepository(session)
        self.attachment_repo = AttachmentRepository(session)
        self.ward_lookup = WardLookupService(session)
        self.audit_service = AuditService(session)

    async def create_complaint(
        self,
        citizen: User,
        payload: CreateComplaintRequest,
    ) -> Complaint:
        """Creates a new complaint, assigns ward, emits outbox event, and records audit node."""
        # 1. Determine ward from coordinates
        ward_id, ward_name = await self.ward_lookup.lookup_ward(payload.latitude, payload.longitude)

        # 2. Generate unique tracking number
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        tracking_number = f"GRV-{date_str}-{uuid.uuid4().hex[:6].upper()}"

        # 3. Associate any uploaded attachments
        attachments: list[Attachment] = []
        if payload.attachment_ids:
            fetched = await self.attachment_repo.get_by_ids(payload.attachment_ids)
            for att in fetched:
                if att.uploader_id == citizen.id and att.complaint_id is None:
                    attachments.append(att)

        # 4. Create complaint preserving original text exactly
        complaint = Complaint(
            tracking_number=tracking_number,
            citizen_id=citizen.id,
            original_title=payload.title.strip(),
            original_description=payload.description.strip(),
            original_language=payload.original_language.strip(),
            latitude=payload.latitude,
            longitude=payload.longitude,
            address=payload.address.strip(),
            ward_id=ward_id,
            ward_name=ward_name,
            channel=payload.channel.strip().upper(),
            status="SUBMITTED",
            attachments=attachments,
        )
        created_complaint = await self.complaint_repo.create(complaint)

        # 5. Transactional Outbox: Write ComplaintSubmitted event in SAME transaction
        await enqueue_outbox_event(
            session=self.session,
            event_type="ComplaintSubmitted",
            aggregate_type="complaint",
            aggregate_id=created_complaint.id,
            payload={
                "complaint_id": str(created_complaint.id),
                "tracking_number": created_complaint.tracking_number,
                "citizen_id": str(citizen.id),
                "title": created_complaint.original_title,
                "description": created_complaint.original_description,
                "ward_name": created_complaint.ward_name,
                "latitude": created_complaint.latitude,
                "longitude": created_complaint.longitude,
                "submitted_at": created_complaint.created_at.isoformat(),
            },
        )

        # 6. Audit Trail: Cryptographic append-only event
        await self.audit_service.record_event(
            entity_type="complaint",
            entity_id=created_complaint.id,
            action="complaint.submitted",
            actor_id=citizen.id,
            actor_role=citizen.role,
            new_state={
                "tracking_number": created_complaint.tracking_number,
                "status": "SUBMITTED",
                "ward_name": created_complaint.ward_name,
            },
        )

        return created_complaint

    async def list_complaints(
        self,
        current_user: User,
        params: ComplaintFilterParams,
    ) -> PaginatedResponse[ComplaintResponse]:
        """Lists complaints filtered by role: citizen sees only own; staff sees all."""
        scoped_citizen_id: Optional[uuid.UUID] = (
            current_user.id if current_user.role == "citizen" else None
        )
        items, next_cursor, has_more, total_count = await self.complaint_repo.list_complaints(
            scoped_citizen_id, params
        )
        return PaginatedResponse[ComplaintResponse](
            items=[ComplaintResponse.model_validate(c) for c in items],
            next_cursor=next_cursor,
            has_more=has_more,
            total_count=total_count,
        )

    async def get_complaint(self, current_user: User, complaint_id: uuid.UUID) -> Complaint:
        """Retrieves complaint detail enforcing object-level ownership for citizens."""
        complaint = await self.complaint_repo.get_by_id(complaint_id)
        if not complaint:
            raise NotFoundError(
                detail=f"Complaint with ID '{complaint_id}' was not found.",
                code="COMPLAINT_NOT_FOUND",
            )

        if current_user.role == "citizen" and complaint.citizen_id != current_user.id:
            raise ForbiddenError(
                detail="You do not have permission to view another citizen's grievance.",
                code="FORBIDDEN_COMPLAINT_ACCESS",
            )

        return complaint

    async def get_public_tracking(self, identifier: str) -> PublicTrackingResponse:
        """Publicly accessible status check without revealing citizen PII."""
        complaint = None
        try:
            complaint_uuid = uuid.UUID(identifier)
            complaint = await self.complaint_repo.get_by_id(complaint_uuid)
        except ValueError:
            pass

        if not complaint:
            complaint = await self.complaint_repo.get_by_tracking_number(identifier)

        if not complaint:
            raise NotFoundError(
                detail=f"No grievance found matching reference '{identifier}'.",
                code="TRACKING_NOT_FOUND",
            )

        return PublicTrackingResponse(
            tracking_number=complaint.tracking_number,
            status=complaint.status,
            ward_name=complaint.ward_name,
            created_at=complaint.created_at,
            updated_at=complaint.updated_at,
        )

    async def upload_attachment(
        self,
        user: User,
        file: UploadFile,
    ) -> Attachment:
        """Validates file type, size, magic bytes, calculates SHA256, and stores attachment."""
        if not file.filename:
            raise BadRequestError(detail="Missing filename", code="INVALID_FILENAME")

        # 1. Validate MIME type
        content_type = file.content_type or ""
        if content_type not in ALLOWED_MIME_TYPES:
            raise BadRequestError(
                detail=f"MIME type '{content_type}' is not allowed. Supported: {list(ALLOWED_MIME_TYPES.keys())}",
                code="INVALID_FILE_TYPE",
            )

        # 2. Validate file extension
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_MIME_TYPES[content_type]:
            raise BadRequestError(
                detail=f"File extension '{ext}' does not match content type '{content_type}'.",
                code="EXTENSION_MISMATCH",
            )

        # 3. Read content and validate size
        content = await file.read()
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise BadRequestError(
                detail=f"File size exceeds {MAX_FILE_SIZE_BYTES // (1024 * 1024)}MB maximum limit.",
                code="FILE_TOO_LARGE",
            )

        # 4. Anti-malware: check magic bytes for executable or script content
        if (
            content.startswith(b"MZ")  # Windows PE binary / EXE
            or content.startswith(b"\x7fELF")  # Linux ELF executable
            or content.startswith(b"#!/")  # Shell scripts
            or content.startswith(b"<?php")  # PHP scripts
            or b"<script" in content[:1024].lower()  # Inlined HTML/JS
        ):
            raise BadRequestError(
                detail="Executable files and script payloads are strictly rejected.",
                code="EXECUTABLE_FILE_PROHIBITED",
            )

        # 5. Compute SHA256 integrity hash
        sha256 = hashlib.sha256(content).hexdigest()

        # 6. Save to local storage or object store
        user_dir = UPLOAD_DIR / str(user.id)
        user_dir.mkdir(parents=True, exist_ok=True)
        unique_filename = f"{uuid.uuid4().hex}_{file.filename}"
        target_path = user_dir / unique_filename
        with open(target_path, "wb") as f:
            f.write(content)

        file_url = f"/uploads/{user.id}/{unique_filename}"

        # 7. Persist attachment record
        attachment = Attachment(
            uploader_id=user.id,
            file_url=file_url,
            file_name=file.filename,
            mime_type=content_type,
            file_size_bytes=len(content),
            sha256_hash=sha256,
            attachment_type="CITIZEN_SUBMISSION",
        )
        return await self.attachment_repo.create(attachment)
