"""GET /local-files: serves a stored file to the holder of a valid signed link.

Only used with the local-disk storage backend. This is where the `url`
returned by GET /documents/{id}/file points (API_DECISIONS D-26).

The route takes no bearer token on purpose: a PDF viewer loads a plain URL.
What protects the file is the signature in the link, which only this server
can produce, and the five-minute expiry. See app/storage/local.py.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from app.api.deps import get_storage
from app.core.errors import ApiError
from app.storage.base import DocumentStorage, StorageError
from app.storage.local import LocalDiskStorage

router = APIRouter()


@router.get("/local-files")
async def get_local_file(
    path: str,
    expires: int,
    signature: str,
    storage: Annotated[DocumentStorage, Depends(get_storage)],
) -> FileResponse:
    if not isinstance(storage, LocalDiskStorage):
        raise ApiError(404, "not_found", "The requested resource was not found.")
    try:
        file_path = storage.open_signed(path, expires, signature)
    except StorageError as exc:
        # One answer for every reason (wrong signature, expired, missing), so
        # the response does not help someone probing for valid links.
        raise ApiError(403, "link_not_valid", "This file link is not valid or has expired.") from exc
    # FileResponse sets the content type from the file extension and answers
    # Range requests, which lets a PDF viewer fetch the pages it needs.
    return FileResponse(file_path)
