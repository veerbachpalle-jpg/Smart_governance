import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.errors import AppException, ProblemDetails
from app.core.logging import request_id_ctx

logger = logging.getLogger("app.middleware")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Middleware to inject and propagate X-Request-ID across the request lifecycle."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(request_id)
        request.state.request_id = request_id

        start_time = time.perf_counter()
        try:
            response: Response = await call_next(request)
            process_time = time.perf_counter() - start_time
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Process-Time"] = f"{process_time:.4f}s"
            return response
        finally:
            request_id_ctx.reset(token)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handles domain/application exceptions and formats as RFC 7807 problem details."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    problem = ProblemDetails(
        type=f"https://api.grievance.gov/errors/{exc.code.lower().replace('_', '-')}",
        title=exc.title,
        status=exc.status,
        detail=exc.detail,
        instance=f"{request.url.path}#{request_id}",
        code=exc.code,
        errors=exc.errors,
    )
    return JSONResponse(
        status_code=exc.status,
        content=problem.model_dump(),
        headers={"X-Request-ID": request_id},
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handles Pydantic validation errors and formats as RFC 7807 problem details."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    errors_list = [
        {"loc": list(err.get("loc", [])), "msg": err.get("msg", ""), "type": err.get("type", "")}
        for err in exc.errors()
    ]
    problem = ProblemDetails(
        type="https://api.grievance.gov/errors/validation-error",
        title="Unprocessable Entity",
        status=422,
        detail="One or more request parameters failed validation.",
        instance=f"{request.url.path}#{request_id}",
        code="VALIDATION_ERROR",
        errors=errors_list,
    )
    return JSONResponse(
        status_code=422,
        content=problem.model_dump(),
        headers={"X-Request-ID": request_id},
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catches unhandled errors and returns RFC 7807 problem details with code INTERNAL_ERROR."""
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.exception("Unhandled system error occurred: %s", str(exc))
    problem = ProblemDetails(
        type="https://api.grievance.gov/errors/internal-error",
        title="Internal Server Error",
        status=500,
        detail="An unexpected internal server error occurred.",
        instance=f"{request.url.path}#{request_id}",
        code="INTERNAL_ERROR",
        errors=[],
    )
    return JSONResponse(
        status_code=500,
        content=problem.model_dump(),
        headers={"X-Request-ID": request_id},
    )
