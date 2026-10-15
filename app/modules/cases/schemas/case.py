import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CreateCaseRequest(BaseModel):
    complaint_id: uuid.UUID
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None


class LinkComplaintRequest(BaseModel):
    complaint_id: uuid.UUID
    is_primary: bool = False


class AddDepartmentRequest(BaseModel):
    department_id: uuid.UUID
    is_lead: bool = False


class SetLeadDepartmentRequest(BaseModel):
    department_id: uuid.UUID


class TransitionCaseRequest(BaseModel):
    target_state: str
    reason: Optional[str] = None
    department_id: Optional[uuid.UUID] = None
    assigned_officer_id: Optional[uuid.UUID] = None


class AssignOfficerRequest(BaseModel):
    officer_id: uuid.UUID


class ReassignCaseRequest(BaseModel):
    suggested_department_id: Optional[uuid.UUID] = None
    reason: str = Field(..., min_length=5, max_length=1000)


class CaseDepartmentResponse(BaseModel):
    id: uuid.UUID
    department_id: uuid.UUID
    department_name: str
    is_lead: bool
    added_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CaseResponse(BaseModel):
    id: uuid.UUID
    case_number: str
    title: str
    description: str
    status: str
    priority: str
    lead_department_id: Optional[uuid.UUID] = None
    assigned_officer_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    departments: list[CaseDepartmentResponse] = []
    complaint_ids: list[uuid.UUID] = []

    model_config = ConfigDict(from_attributes=True)
