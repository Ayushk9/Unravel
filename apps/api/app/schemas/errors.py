"""The single error body shape (API_DECISIONS D-03)."""

from __future__ import annotations

from app.schemas.base import ApiModel


class FieldError(ApiModel):
    field: str
    message: str


class ErrorDetail(ApiModel):
    code: str
    message: str
    field_errors: list[FieldError]
    request_id: str
    retryable: bool


class ErrorBody(ApiModel):
    error: ErrorDetail
