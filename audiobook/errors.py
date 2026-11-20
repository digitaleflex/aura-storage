"""Typed application errors mapped to explicit HTTP responses."""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    code = "INTERNAL_ERROR"
    http_status = 500

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        http_status: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        if code is not None:
            self.code = code
        if http_status is not None:
            self.http_status = http_status
        self.details = details


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    http_status = 422


class UnauthorizedError(AppError):
    code = "UNAUTHORIZED"
    http_status = 401


class ForbiddenError(AppError):
    code = "FORBIDDEN"
    http_status = 403


class NotFoundError(AppError):
    code = "NOT_FOUND"
    http_status = 404


class ConflictError(AppError):
    code = "CONFLICT"
    http_status = 409


class UnavailableError(AppError):
    code = "UNAVAILABLE"
    http_status = 503
