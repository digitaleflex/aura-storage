"""HTTP middlewares and request context binding (#339)."""
from __future__ import annotations
from fastapi import Request
from . import ids
from .audit import bind_request_context, reset_request_context


def _incoming_request_id(request: Request) -> str:
    incoming = request.headers.get("x-request-id", "")
    if incoming and len(incoming) <= 128 and all(33 <= ord(ch) <= 126 for ch in incoming):
        return incoming
    return ids.new_id()


def register_http_middlewares(app):
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = _incoming_request_id(request)
        _, token = bind_request_context(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            reset_request_context(token)
