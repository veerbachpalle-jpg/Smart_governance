import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRole(str, Enum):
    CITIZEN = "citizen"
    OFFICER = "officer"
    DEPARTMENT_LEAD = "department_lead"
    SUPERVISOR = "supervisor"
    ADMIN = "admin"
    AUDITOR = "auditor"


class RegisterRequest(BaseModel):
    email: EmailStr
    phone_number: str = Field(min_length=7, max_length=20)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=128)
    address: Optional[str] = None
    preferred_language: str = Field(default="en", max_length=16)
    notification_preference: str = Field(default="email", max_length=32)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int


class CitizenProfileResponse(BaseModel):
    id: uuid.UUID
    full_name: str
    address: Optional[str] = None
    preferred_language: str
    notification_preference: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DepartmentResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: Optional[str] = None
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    phone_number: str
    role: str
    is_active: bool
    created_at: datetime
    citizen_profile: Optional[CitizenProfileResponse] = None

    model_config = ConfigDict(from_attributes=True)
