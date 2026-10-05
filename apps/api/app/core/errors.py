"""Every non-2xx response is built here, in one shape (API_DECISIONS D-03).

    {"error": {"code", "message", "field_errors", "request_id", "retryable"}}

Routes signal a failure by raising ApiError. They never build an error body
themselves. Four handlers cover every way a request can fail:

  ApiError                 raised deliberately by our own code
  HTTPException            raised by Starlette/FastAPI, e.g. unknown route (404)
                           or wrong method (405)
  RequestValidationError   the request body, query or path failed validation
  Exception                anything unexpected: a bug

All four call build_error_response(), so FastAPI's default {"detail": ...}
body has no path to a client.

Unexpected exceptions are normally caught one step earlier, by
UnhandledErrorMiddleware at the bottom of this file. It does the same job
as the fourth handler but from inside the CORS layer, so that a browser is
allowed to read the 500 response (see its docstring).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.ids import new_id
from app.core.request_id import REQUEST_ID_HEADER
from app.schemas.errors import ErrorBody, ErrorDetail, FieldError

logger = logging.getLogger("unravel.api")


class ApiError(Exception):
    """A failure the API reports to the client on purpose."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        field_errors: list[FieldError] | None = None,
        retryable: bool = False,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors or []
        self.retryable = retryable
        self.headers = headers


# Code and message for errors raised by the framework rather than by us.
# The framework's own wording ("Not Found") is replaced so that clients see
# one consistent voice.
_FRAMEWORK_ERRORS: dict[int, tuple[str, str]] = {
    401: ("unauthorized", "Authentication is required."),
    403: ("forbidden", "You are not allowed to do that."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "That method is not allowed on this route."),
    413: ("payload_too_large", "The request body is too large."),
    429: ("rate_limited", "Too many requests. Try again shortly."),
}

# FastAPI reports where a validation error happened as a tuple whose first
# item is the part of the request: ("body", "claim_type"). The contract's
# example shows just "claim_type", so that first item is dropped.
_REQUEST_PARTS = {"body", "query", "path", "header", "cookie"}


def build_error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    field_errors: list[FieldError] | None = None,
    retryable: bool = False,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """Build the one permitted error body."""
    request_id = _request_id(request)
    body = ErrorBody(
        error=ErrorDetail(
            code=code,
            message=message,
            field_errors=field_errors or [],
            request_id=request_id,
            retryable=retryable,
        )
    )
    # The middleware normally adds this header. It is also set here because
    # the response to an unhandled exception is sent from outside that
    # middleware and would otherwise go out without it.
    response_headers = {REQUEST_ID_HEADER: request_id}
    if headers:
        response_headers.update(headers)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"), headers=response_headers)


def _request_id(request: Request) -> str:
    """The id set by RequestIdMiddleware, or a fresh one if it never ran."""
    request_id = getattr(request.state, "request_id", None)
    if request_id is None:
        request_id = str(new_id())
        request.state.request_id = request_id
    return request_id


def _field_name(location: tuple[int | str, ...]) -> str:
    """("body", "items", 0, "amount") -> "items.0.amount"."""
    parts = [str(part) for part in location]
    if len(parts) > 1 and parts[0] in _REQUEST_PARTS:
        parts = parts[1:]
    return ".".join(parts)


async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return build_error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        field_errors=exc.field_errors,
        retryable=exc.retryable,
        headers=exc.headers,
    )


async def handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code, message = _FRAMEWORK_ERRORS.get(exc.status_code, ("http_error", "The request could not be completed."))
    return build_error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
        retryable=exc.status_code == 429,
        # Keeps headers such as Allow (405) and Retry-After (429).
        headers=dict(exc.headers) if exc.headers else None,
    )


async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    field_errors = [
        FieldError(field=_field_name(error["loc"]), message=error["msg"]) for error in exc.errors()
    ]
    return build_error_response(
        request,
        status_code=422,
        code="validation_error",
        message="The request was not valid.",
        field_errors=field_errors,
    )


def unexpected_error_response(request: Request, exc: Exception) -> JSONResponse:
    """Log an unexpected exception and build the 500 response for it."""
    # The stack trace goes to the server log with the request id. The client
    # gets the id and a generic message, never the trace.
    logger.error(
        "Unhandled exception. request_id=%s method=%s path=%s",
        _request_id(request),
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return build_error_response(
        request,
        status_code=500,
        code="internal_error",
        message="Something went wrong on our side.",
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    return unexpected_error_response(request, exc)


class UnhandledErrorMiddleware:
    """Turn an unexpected exception into the 500 envelope, inside CORS.

    FastAPI's own catch-all handler runs outside every middleware, including
    the CORS one. A 500 built there has no CORS headers, so a browser refuses
    to let the web app read it and the user sees a bare network failure with
    no request_id. Catching the exception here, inside the CORS layer, means
    the response passes back out through it and gets those headers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:  # noqa: BLE001 - catching everything is this middleware's purpose
            if response_started:
                # Part of a response has already been sent; a second one
                # cannot be started. Let the server close the connection.
                raise
            response = unexpected_error_response(Request(scope), exc)
            await response(scope, receive, send)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, handle_api_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
