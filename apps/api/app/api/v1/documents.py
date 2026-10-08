"""Document endpoints.

POST   /documents              CONTRACTS.md row 2   (D-07 job, D-13 idempotency, D-18 upload rules)
GET    /documents              CONTRACTS.md row 3   (cursor pagination, optional claim_id filter)
GET    /documents/{id}         CONTRACTS.md row 4
PATCH  /documents/{id}         CONTRACTS.md row 5   (correct the detected type)
DELETE /documents/{id}         CONTRACTS.md row 6   (soft delete, D-20)
GET    /documents/{id}/file    D-26
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, Query, Request, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_runner, get_storage
from app.core.auth import CurrentHousehold, get_current_household
from app.core.errors import ApiError
from app.core.ids import new_id
from app.db.models import Claim as ClaimRow
from app.db.models import Document as DocumentRow
from app.db.models import Job as JobRow
from app.db.session import get_session
from app.jobs.parse_document import UPLOADING
from app.jobs.runner import JobRunner
from app.schemas.common import Collection
from app.schemas.documents import DocumentFile, DocumentTypeCorrectionRequest, StoredDocument
from app.schemas.errors import FieldError
from app.schemas.jobs import JobAccepted
from app.services.extracted_columns import apply_correction, columns_to_extracted
from app.services.file_validation import read_upload, sha256_hex, validate_file
from app.storage.base import DocumentStorage, StorageError, build_object_path

router = APIRouter()

SIGNED_URL_LIFETIME_SECONDS = 300
_MAX_IDEMPOTENCY_KEY_LENGTH = 255
_MAX_FILE_NAME_LENGTH = 255


def _accepted(job: JobRow) -> JobAccepted:
    # Always "queued": this is the body of the ORIGINAL 202, and a replay
    # must return it unchanged even if the job has moved on since (D-13).
    return JobAccepted(job_id=job.id, kind=job.kind, status="queued")


def _replay_or_conflict(existing: JobRow, request_hash: str) -> JobAccepted:
    """Same key seen before: same file replays, a different file is refused (D-27)."""
    if existing.request_hash == request_hash:
        return _accepted(existing)
    raise ApiError(
        409,
        "idempotency_key_reused",
        "This Idempotency-Key was already used for a different file. Use a new key for a new upload.",
        field_errors=[FieldError(field="Idempotency-Key", message="Already used with different content.")],
    )


async def _find_job_by_key(session: AsyncSession, household_id: UUID, key: str) -> JobRow | None:
    # Keys are scoped to a household: two households may use the same key.
    return await session.scalar(
        select(JobRow).where(JobRow.household_id == household_id, JobRow.idempotency_key == key)
    )


@router.post("/documents", status_code=202)
async def upload_document(
    background_tasks: BackgroundTasks,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[DocumentStorage, Depends(get_storage)],
    runner: Annotated[JobRunner, Depends(get_runner)],
    file: Annotated[UploadFile, File()],
    claim_id: Annotated[str | None, Form()] = None,
    idempotency_key: Annotated[str | None, Header()] = None,
) -> JobAccepted:
    """Accept a file and queue it for parsing. Returns at once with a job to poll.

    Parsing takes tens of seconds, far longer than a request should stay
    open, so the request only records the work and the job runner does it.
    """
    if not idempotency_key or len(idempotency_key) > _MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ApiError(
            422,
            "validation_error",
            "Idempotency-Key is required on this endpoint.",
            field_errors=[FieldError(field="Idempotency-Key", message="This header is required.")],
        )
    # An upload with a claim_id is a claim document; one without is a policy.
    owned_claim_id = await _owned_claim_id(session, household.household_id, claim_id) if claim_id else None

    content = await read_upload(file)
    content_type = validate_file(content, file.content_type)
    request_hash = sha256_hex(content)

    existing = await _find_job_by_key(session, household.household_id, idempotency_key)
    if existing is not None:
        return _replay_or_conflict(existing, request_hash)

    document_id = new_id()
    file_name = (file.filename or "document")[:_MAX_FILE_NAME_LENGTH]
    storage_path = build_object_path(household.household_id, document_id, file_name)

    try:
        await storage.save(storage_path, content, content_type)
    except StorageError as exc:
        raise ApiError(
            503, "storage_unavailable", "We couldn't store your file right now. Please try again.", retryable=True
        ) from exc

    job = JobRow(
        id=new_id(),
        household_id=household.household_id,
        kind="parse_document",
        status="queued",
        progress={"step": UPLOADING[0], "percent": UPLOADING[1]},
        # "policy" runs the full Engine A parse. "claim_document" only needs
        # a label, which is far cheaper (app/jobs/classify_document.py).
        payload={
            "document_id": str(document_id),
            "document_kind": "claim_document" if owned_claim_id else "policy",
        },
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    session.add(
        DocumentRow(
            id=document_id,
            household_id=household.household_id,
            claim_id=owned_claim_id,
            file_name=file_name,
            mime_type=content_type,
            storage_path=storage_path,
            sha256=request_hash,
            size_bytes=len(content),
            parse_status="queued",
        )
    )
    session.add(job)
    try:
        # The document and its job are committed together: there is never a
        # document nobody will parse, or a job with nothing to parse.
        await session.commit()
    except IntegrityError:
        # Two requests with the same key arrived together and the other one
        # won the unique constraint. Undo ours and answer from the winner's row.
        await session.rollback()
        await storage.delete(storage_path)
        winner = await _find_job_by_key(session, household.household_id, idempotency_key)
        if winner is None:
            raise
        return _replay_or_conflict(winner, request_hash)

    # Runs after the response is sent. It only nudges the runner; the job is
    # already safely in the table whether or not this runs.
    background_tasks.add_task(runner.wake)
    return _accepted(job)


async def _owned_claim_id(session: AsyncSession, household_id: UUID, claim_id: str) -> UUID:
    """The claim id from an upload form, checked to belong to the caller's household."""
    unknown = ApiError(
        422,
        "validation_error",
        "That claim doesn't belong to your household.",
        field_errors=[FieldError(field="claim_id", message="Unknown claim.")],
    )
    try:
        parsed = UUID(claim_id)
    except ValueError:
        raise unknown from None
    found = await session.scalar(select(ClaimRow.id).where(ClaimRow.id == parsed, ClaimRow.household_id == household_id))
    if found is None:
        raise unknown
    return found


async def _find_document(session: AsyncSession, household_id: UUID, document_id: UUID) -> DocumentRow:
    row = await session.scalar(
        select(DocumentRow).where(
            DocumentRow.id == document_id,
            DocumentRow.household_id == household_id,
            DocumentRow.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ApiError(404, "not_found", "No document with that id belongs to your household.")
    return row


def _to_wire(row: DocumentRow) -> StoredDocument:
    return StoredDocument(
        id=row.id,
        file_name=row.file_name,
        mime_type=row.mime_type,
        page_count=row.page_count,
        uploaded_at=row.uploaded_at,
        # The current type: the user's correction if there is one, otherwise
        # what the classifier said. The classifier's answer is kept in a
        # separate column either way.
        detected_type=columns_to_extracted(row, "detected_type"),
        parse_status=row.parse_status,
        parse_error=row.parse_error,
        deleted_at=row.deleted_at,
        claim_id=row.claim_id,
    )


@router.get("/documents")
async def list_documents(
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
    cursor: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    claim_id: UUID | None = None,
) -> Collection[StoredDocument]:
    """This household's documents, oldest first, one page at a time.

    Keyset pagination: the cursor is the id of the last item already seen,
    and the next page is "ids greater than that". Ids are UUIDv7, so id
    order is upload order. Unlike OFFSET, a page cannot skip or repeat rows
    when a new document is uploaded while the client is paging.
    """
    filters = [DocumentRow.household_id == household.household_id, DocumentRow.deleted_at.is_(None)]
    if claim_id is not None:
        # Filtering by a claim in another household matches nothing, because
        # the household filter above still applies.
        filters.append(DocumentRow.claim_id == claim_id)

    total = await session.scalar(select(func.count()).select_from(DocumentRow).where(*filters))
    page_filters = [*filters, DocumentRow.id > cursor] if cursor is not None else filters
    # One extra row tells us whether another page exists, without a second query.
    rows = list(await session.scalars(select(DocumentRow).where(*page_filters).order_by(DocumentRow.id).limit(limit + 1)))
    page = rows[:limit]
    next_cursor = str(page[-1].id) if len(rows) > limit else None
    return Collection[StoredDocument](items=[_to_wire(row) for row in page], next_cursor=next_cursor, total=total)


@router.get("/documents/{document_id}")
async def get_document(
    document_id: UUID,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StoredDocument:
    return _to_wire(await _find_document(session, household.household_id, document_id))


@router.patch("/documents/{document_id}")
async def correct_document_type(
    document_id: UUID,
    body: DocumentTypeCorrectionRequest,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> StoredDocument:
    """Record the user's own label for a document.

    The classifier's answer stays in `detected_type_original_value` and its
    confidence is left as it was. Comparing the two afterwards shows how
    often the classifier was right, which is evaluation data for the report.
    """
    row = await _find_document(session, household.household_id, document_id)
    apply_correction(row, "detected_type", body.detected_type)
    await session.commit()
    return _to_wire(row)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Response:
    """Soft delete (D-20): the row is marked deleted and disappears from every
    read, but is kept so an accidental tap can be undone by an operator.
    The stored file is kept with it."""
    row = await _find_document(session, household.household_id, document_id)
    row.deleted_at = func.now()
    await session.commit()
    return Response(status_code=204)


@router.get("/documents/{document_id}/file")
async def get_document_file(
    request: Request,
    document_id: UUID,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
    storage: Annotated[DocumentStorage, Depends(get_storage)],
) -> DocumentFile:
    """A short-lived link to the file, for the provenance viewer.

    Ownership is checked here, with the caller's token. The link itself
    needs no token, which is what lets a PDF viewer load it directly, and it
    stops working after a few minutes.
    """
    row = await _find_document(session, household.household_id, document_id)
    if row.storage_path is None:
        raise ApiError(404, "not_found", "No document with that id belongs to your household.")
    try:
        url = await storage.signed_url(row.storage_path, SIGNED_URL_LIFETIME_SECONDS)
    except StorageError as exc:
        raise ApiError(
            503, "storage_unavailable", "We couldn't fetch this file right now. Please try again.", retryable=True
        ) from exc
    if url.startswith("/"):
        # The local backend returns a link to this server's own file route.
        # It is completed with the address the CLIENT used to reach us, so a
        # browser on this Mac gets http://localhost:8000/... and a phone on
        # the Wi-Fi gets http://<the Mac's IP>:8000/..., each one reachable
        # from where it was asked.
        url = str(request.base_url).rstrip("/") + url
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=SIGNED_URL_LIFETIME_SECONDS)
    return DocumentFile(url=url, expires_at=expires_at)
