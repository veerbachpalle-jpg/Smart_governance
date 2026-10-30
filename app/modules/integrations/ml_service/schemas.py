from typing import Any, Optional
from pydantic import BaseModel, Field


class MLDeptScore(BaseModel):
    department: str
    confidence: float


class MLAnalysis(BaseModel):
    is_duplicate: bool = False
    duplicate_of: Optional[int] = None
    similarity_score: float = 0.0
    departments: list[str] = Field(default_factory=list)
    dept_scores: list[MLDeptScore] = Field(default_factory=list)
    ai_confidence: float = 0.0
    priority: str = "Medium"
    ai_summary: str = ""


class MLComplaintRequest(BaseModel):
    citizen_name: str = Field(min_length=2, max_length=100)
    contact: str = Field(min_length=5, max_length=100)
    location: str = Field(min_length=3, max_length=200)
    complaint_text: str = Field(min_length=20, max_length=2000)
    category: str = Field(min_length=2, max_length=100)


class MLComplaintResponse(BaseModel):
    success: bool
    message: str
    complaint_id: Optional[int] = None
    ai_analysis: MLAnalysis


class MLAnalyzeDryRunRequest(BaseModel):
    complaint_text: str
    citizen_name: Optional[str] = "Citizen"
    contact: Optional[str] = "9876543210"
    location: Optional[str] = "Municipal Ward Area"
    category: Optional[str] = "General Grievance"


class MLHealthResponse(BaseModel):
    connected: bool
    url: str
    status: Optional[str] = None
    model: Optional[str] = None
    embedding_model: Optional[str] = None
    details: Optional[dict[str, Any]] = None
    error: Optional[str] = None
