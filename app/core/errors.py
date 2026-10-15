from typing import Any

from pydantic import BaseModel, Field


class ProblemDetails(BaseModel):
    """RFC 7807 compliant problem details response payload."""

    type: str = Field(default="about:blank")
    title: str
    status: int
    detail: str
    instance: str
    code: str
    errors: list[dict[str, Any]] = Field(default_factory=list)


class AppException(Exception):
    """Base application exception supporting RFC 7807 attributes."""

    def __init__(
        self,
        title: str,
        status: int,
        detail: str,
        code: str,
        errors: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(detail)
        self.title = title
        self.status = status
        self.detail = detail
        self.code = code
        self.errors = errors or []


class NotFoundError(AppException):
    def __init__(self, detail: str = "Resource not found", code: str = "NOT_FOUND") -> None:
        super().__init__(
            title="Not Found",
            status=404,
            detail=detail,
            code=code,
        )


class UnauthorizedError(AppException):
    def __init__(self, detail: str = "Authentication required", code: str = "UNAUTHORIZED") -> None:
        super().__init__(
            title="Unauthorized",
            status=401,
            detail=detail,
            code=code,
        )


class ForbiddenError(AppException):
    def __init__(
        self,
        detail: str = "You do not have permission to perform this action",
        code: str = "FORBIDDEN",
    ) -> None:
        super().__init__(
            title="Forbidden",
            status=403,
            detail=detail,
            code=code,
        )


class ConflictError(AppException):
    def __init__(self, detail: str = "Resource conflict detected", code: str = "CONFLICT") -> None:
        super().__init__(
            title="Conflict",
            status=409,
            detail=detail,
            code=code,
        )


class BadRequestError(AppException):
    def __init__(self, detail: str = "Invalid request", code: str = "BAD_REQUEST") -> None:
        super().__init__(
            title="Bad Request",
            status=400,
            detail=detail,
            code=code,
        )


class ValidationError(AppException):
    def __init__(
        self,
        detail: str = "Validation failed",
        errors: list[dict[str, Any]] | None = None,
        code: str = "VALIDATION_ERROR",
    ) -> None:
        super().__init__(
            title="Unprocessable Entity",
            status=422,
            detail=detail,
            code=code,
            errors=errors or [],
        )
