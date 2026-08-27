"""Contract-compliant API error responses and exception handlers."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request identifier before routing and echo it in the response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Any) -> JSONResponse:
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


def _request_id(request: Request) -> str:
    """Return the request identifier even if an error occurs before middleware."""
    return getattr(request.state, "request_id", str(uuid4()))


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    field_errors: list[dict[str, str]] | None = None,
    retryable: bool = False,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the single error envelope permitted by the API contract."""
    response_headers = {"X-Request-ID": _request_id(request)}
    if headers:
        response_headers.update(headers)

    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "field_errors": field_errors or [],
                "request_id": _request_id(request),
                "retryable": retryable,
            }
        },
        headers=response_headers,
    )


def _http_error_code(status_code: int) -> str:
    return {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        413: "payload_too_large",
        429: "rate_limited",
    }.get(status_code, "http_error")


def _validation_field_error(error: dict[str, Any]) -> dict[str, str]:
    location = ".".join(str(part) for part in error.get("loc", ()))
    return {"field": location or "request", "message": error.get("msg", "Invalid value")}


def install_exception_handlers(app: FastAPI) -> None:
    """Register handlers for every error path exposed by FastAPI/Starlette."""

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return error_response(
            request,
            status_code=422,
            code="validation_error",
            message="Request validation failed.",
            field_errors=[_validation_field_error(error) for error in exc.errors()],
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        message = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."
        return error_response(
            request,
            status_code=exc.status_code,
            code=_http_error_code(exc.status_code),
            message=message,
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        return error_response(
            request,
            status_code=500,
            code="internal_server_error",
            message="An unexpected error occurred.",
            retryable=False,
        )
