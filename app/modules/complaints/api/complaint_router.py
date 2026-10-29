import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, require_roles
from app.core.idempotency import IdempotencyManager, extract_idempotency_key
from app.core.pagination import PaginatedResponse
from app.db.session import get_db
from app.modules.complaints.schemas.complaint import (
    AttachmentResponse,
    ComplaintFilterParams,
    ComplaintResponse,
    CreateComplaintRequest,
    PublicTrackingResponse,
    TrendingComplaintResponse,
)
from app.modules.complaints.service.complaint_service import ComplaintService
from app.modules.identity.models.user import User
from app.modules.identity.schemas.identity import UserRole

complaints_router = APIRouter(prefix="/complaints", tags=["Complaints"])


@complaints_router.post(
    "",
    response_model=ComplaintResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new municipal grievance with mandatory Idempotency-Key",
)
async def submit_complaint(
    request: Request,
    payload: CreateComplaintRequest,
    idempotency_key: str = Depends(extract_idempotency_key),
    current_user: User = Depends(require_roles(UserRole.CITIZEN)),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # 1. Retrieve raw request body for idempotency hashing
    raw_body = await request.body()

    # 2. Check idempotency store for replay or conflict
    existing_record = await IdempotencyManager.get_or_validate(
        session=session,
        key=idempotency_key,
        request_path=request.url.path,
        raw_body=raw_body,
    )
    if existing_record is not None:
        return JSONResponse(
            status_code=existing_record.response_status,
            content=existing_record.response_body,
            headers={"X-Idempotent-Replay": "true"},
        )

    # 3. Create complaint within current transaction
    service = ComplaintService(session)
    complaint = await service.create_complaint(current_user, payload)
    complaint_data = ComplaintResponse.model_validate(complaint).model_dump(mode="json")

    # 4. Save response in idempotency store
    await IdempotencyManager.record_response(
        session=session,
        key=idempotency_key,
        request_path=request.url.path,
        raw_body=raw_body,
        status_code=status.HTTP_201_CREATED,
        response_body=complaint_data,
    )

    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=complaint_data,
    )


@complaints_router.get(
    "",
    response_model=PaginatedResponse[ComplaintResponse],
    status_code=status.HTTP_200_OK,
    summary="List complaints (citizens view only own; municipal staff view all with filters)",
)
async def list_complaints(
    complaint_status: str | None = Query(None, alias="status"),
    ward_id: uuid.UUID | None = Query(None),
    ward_number: int | None = Query(None, ge=1),
    ward_name: str | None = Query(None),
    department_id: uuid.UUID | None = Query(None),
    department_name: str | None = Query(None),
    sort: Literal["priority_score", "upvotes", "recent"] = Query("priority_score"),
    start_time: datetime | None = Query(None),
    end_time: datetime | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[ComplaintResponse]:
    params = ComplaintFilterParams(
        status=complaint_status,
        ward_id=ward_id,
        ward_number=ward_number,
        ward_name=ward_name,
        department_id=department_id,
        department_name=department_name,
        sort=sort,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
        cursor=cursor,
    )
    service = ComplaintService(session)
    return await service.list_complaints(current_user, params)


@complaints_router.get(
    "/trending-nearby",
    response_model=list[TrendingComplaintResponse],
    status_code=status.HTTP_200_OK,
    summary="List open complaints within a regional radius ordered by citizen endorsements",
)
async def list_trending_nearby(
    lat: float = Query(..., ge=-90.0, le=90.0),
    lng: float = Query(..., ge=-180.0, le=180.0),
    radius_meters: float = Query(2000.0, ge=50.0, le=20000.0),
    current_user: User = Depends(require_roles(UserRole.CITIZEN)),
    session: AsyncSession = Depends(get_db),
) -> list[TrendingComplaintResponse]:
    service = ComplaintService(session)
    return await service.list_trending_nearby(
        current_user=current_user,
        latitude=lat,
        longitude=lng,
        radius_meters=radius_meters,
    )


@complaints_router.get(
    "/{complaint_id}",
    response_model=ComplaintResponse,
    status_code=status.HTTP_200_OK,
    summary="Get comprehensive complaint dossier with authorization check",
)
async def get_complaint_detail(
    complaint_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ComplaintResponse:
    service = ComplaintService(session)
    complaint = await service.get_complaint(current_user, complaint_id)
    return ComplaintResponse.model_validate(complaint)


@complaints_router.get(
    "/{identifier}/tracking",
    response_model=PublicTrackingResponse,
    status_code=status.HTTP_200_OK,
    summary="Public-safe status tracking by complaint ID or tracking number without personal data",
)
async def get_public_tracking(
    identifier: str,
    session: AsyncSession = Depends(get_db),
) -> PublicTrackingResponse:
    service = ComplaintService(session)
    return await service.get_public_tracking(identifier)


@complaints_router.post(
    "/attachments/upload",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload media attachment (validates MIME, size, rejects executables)",
)
async def upload_attachment(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> AttachmentResponse:
    service = ComplaintService(session)
    attachment = await service.upload_attachment(current_user, file)
    return AttachmentResponse.model_validate(attachment)


@complaints_router.get(
    "/{complaint_id}/attachments",
    response_model=list[AttachmentResponse],
    status_code=status.HTTP_200_OK,
    summary="List all media attachments associated with a complaint",
)
async def get_complaint_attachments(
    complaint_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[AttachmentResponse]:
    service = ComplaintService(session)
    complaint = await service.get_complaint(current_user, complaint_id)
    return [AttachmentResponse.model_validate(att) for att in complaint.attachments]
