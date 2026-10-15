from typing import Optional

from pydantic import BaseModel, Field


class ChaosConfigRequest(BaseModel):
    disable_ai: Optional[bool] = None
    ai_garbage: Optional[bool] = None
    delay_worker_ms: Optional[int] = Field(default=None, ge=0, le=60000)
    stop_worker: Optional[bool] = None
    fail_notifications: Optional[bool] = None
    db_error_operations: Optional[list[str]] = None


class ChaosStateResponse(BaseModel):
    is_active: bool
    disable_ai: bool
    ai_garbage: bool
    delay_worker_ms: int
    stop_worker: bool
    fail_notifications: bool
    db_error_operations: list[str]
