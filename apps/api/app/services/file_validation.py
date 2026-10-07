"""Checks on an uploaded file before anything is stored (D-18).

The declared content type and the file name both come from the client, so
neither proves what the file is. The first bytes of the file do: every PDF,
PNG and JPEG starts with a fixed signature ("magic bytes"). A file is
accepted only when its signature is one of the three allowed types AND
agrees with the type the client declared.
"""

from __future__ import annotations

import hashlib

from fastapi import UploadFile

from app.core.errors import ApiError
from app.schemas.errors import FieldError

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_READ_CHUNK_BYTES = 1024 * 1024

# Signature -> content type. A PDF starts with "%PDF-"; a PNG with an 8-byte
# marker; a JPEG with FF D8 FF.
_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)
ALLOWED_CONTENT_TYPES = tuple(content_type for _, content_type in _SIGNATURES)


def detect_content_type(content: bytes) -> str | None:
    """The allowed type whose signature the file starts with, or None."""
    for signature, content_type in _SIGNATURES:
        if content.startswith(signature):
            return content_type
    return None


def _invalid_file(message: str) -> ApiError:
    return ApiError(
        422,
        "validation_error",
        "Only PDF, PNG and JPEG files are accepted.",
        field_errors=[FieldError(field="file", message=message)],
    )


async def read_upload(upload: UploadFile) -> bytes:
    """Read the whole upload, refusing anything over 25 MB.

    Read in chunks and stop as soon as the limit is passed, so an oversized
    upload is rejected without holding all of it in memory.
    """
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_READ_CHUNK_BYTES):
        total += len(chunk)
        if total > MAX_UPLOAD_BYTES:
            raise ApiError(413, "file_too_large", "Upload exceeds 25 MB.")
        chunks.append(chunk)
    return b"".join(chunks)


def validate_file(content: bytes, declared_content_type: str | None) -> str:
    """Return the file's real content type, or raise a 422 ApiError."""
    if not content:
        raise _invalid_file("The file is empty.")

    detected = detect_content_type(content)
    if detected is None:
        raise _invalid_file("This file is not a PDF, PNG or JPEG.")
    if declared_content_type != detected:
        raise _invalid_file(
            f"The file was sent as {declared_content_type or 'an unknown type'} but its contents are {detected}."
        )
    return detected


def sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
