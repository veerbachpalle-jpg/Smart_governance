import base64
import uuid
from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


def encode_cursor(timestamp: datetime, entity_id: uuid.UUID) -> str:
    """Encodes timestamp and UUID into an opaque base64 cursor string."""
    raw = f"{timestamp.isoformat()}|{entity_id}"
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("utf-8")


def decode_cursor(cursor_str: str) -> tuple[datetime, uuid.UUID]:
    """Decodes an opaque base64 cursor string into timestamp and UUID."""
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        ts_part, id_part = raw.split("|", 1)
        return datetime.fromisoformat(ts_part), uuid.UUID(id_part)
    except Exception as err:
        raise ValueError("Invalid cursor format") from err


def encode_offset_cursor(offset: int) -> str:
    return base64.urlsafe_b64encode(f"offset:{offset}".encode("utf-8")).decode("utf-8")


def decode_offset_cursor(cursor_str: str) -> int:
    try:
        raw = base64.urlsafe_b64decode(cursor_str.encode("utf-8")).decode("utf-8")
        prefix, value = raw.split(":", 1)
        if prefix != "offset":
            raise ValueError
        return max(0, int(value))
    except Exception as err:
        raise ValueError("Invalid cursor format") from err


class PaginatedResponse(BaseModel, Generic[T]):
    """Standardized keyset/cursor paginated response structure."""

    items: list[T] = Field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False
    total_count: int | None = None
