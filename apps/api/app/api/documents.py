"""Document upload and retrieval endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.jobs import JobAccepted, accepted_job
from app.api.serializers import document_read
from app.core.auth import CurrentHousehold, get_current_household, get_household_owned_or_404
from app.core.config import Settings, get_settings
from app.db.models import Document, Job
from app.db.session import session_scope
from app.services.jobs import enqueue_job
from app.services.stub_extraction import parse_uploaded_document


router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_UPLOADS = {
    "application/pdf": (".pdf", {".pdf"}),
    "image/png": (".png", {".png"}),
    "image/jpeg": (".jpg", {".jpg", ".jpeg"}),
}


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=JobAccepted)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(...)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1)],
    claim_id: Annotated[str | None, Form()] = None,
    current: CurrentHousehold = Depends(get_current_household),
    session: AsyncSession = Depends(session_scope),
    settings: Settings = Depends(get_settings),
) -> JobAccepted:
    """Store a supported upload then enqueue deterministic stub extraction."""
    del claim_id  # Claims are introduced in the next slice; policy uploads are unclaimed.
    mime_type = (file.content_type or "").lower()
    extension = Path(file.filename or "").suffix.lower()
    if mime_type not in ALLOWED_UPLOADS or extension not in ALLOWED_UPLOADS[mime_type][1]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Only PDF, PNG, and JPEG uploads are supported.")

    existing = await session.scalar(
        select(Job).where(Job.household_id == current.household_id, Job.idempotency_key == idempotency_key)
    )
    if existing is not None:
        return accepted_job(existing)

    document = Document(
        household_id=current.household_id,
        file_name=file.filename or f"upload{ALLOWED_UPLOADS[mime_type][0]}",
        mime_type=mime_type,
        storage_path="pending",
        parse_status="queued",
    )
    session.add(document)
    await session.flush()
    storage_directory = settings.upload_directory / str(current.household_id)
    storage_directory.mkdir(parents=True, exist_ok=True)
    destination = storage_directory / f"{document.id}{ALLOWED_UPLOADS[mime_type][0]}"
    bytes_written = 0
    try:
        with destination.open("xb") as stored_file:
            while chunk := await file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Upload exceeds the 25 MB limit.")
                stored_file.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        await session.rollback()
        raise
    finally:
        await file.close()

    document.storage_path = str(destination)
    job = await enqueue_job(
        background_tasks=background_tasks,
        session=session,
        current_household=current,
        kind="parse_document",
        work=lambda reporter: parse_uploaded_document(reporter, document.id),
        idempotency_key=idempotency_key,
    )
    return accepted_job(job)


@router.get("/{id}")
async def get_document(
    id: UUID,
    current: CurrentHousehold = Depends(get_current_household),
    session: AsyncSession = Depends(session_scope),
) -> dict[str, object]:
    """Return a document only within the authenticated household."""
    document = await get_household_owned_or_404(session, Document, id, current)
    return document_read(document)
