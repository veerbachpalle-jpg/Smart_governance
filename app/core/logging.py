import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# Context variable to hold request_id for the current request lifecycle
request_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class JSONFormatter(logging.Formatter):
    """Formats log records as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_obj: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        req_id = request_id_ctx.get()
        if req_id:
            log_obj["request_id"] = req_id

        if record.exc_info:
            log_obj["exception"] = self.formatException(record.exc_info)

        # Include custom extra fields if provided
        for key, value in record.__dict__.items():
            if key not in {
                "args",
                "asctime",
                "created",
                "exc_info",
                "exc_text",
                "filename",
                "funcName",
                "levelname",
                "levelno",
                "lineno",
                "module",
                "msecs",
                "message",
                "msg",
                "name",
                "pathname",
                "process",
                "processName",
                "relativeCreated",
                "stack_info",
                "thread",
                "threadName",
            } and not key.startswith("_"):
                log_obj[key] = value

        return json.dumps(log_obj)


def setup_logging(log_level: str = "INFO") -> None:
    """Configures structured JSON logging for the application."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(log_level.upper())

    # Quiet overly noisy loggers
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = True
