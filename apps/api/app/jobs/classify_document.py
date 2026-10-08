"""The claim-document job: label one uploaded file, without the full parse.

Same job kind and same queue as a policy parse (`parse_document`), but a
different amount of work. A policy needs every clause read, with positions.
A claim document only needs to be recognised ("this is a discharge summary")
so the missing-document list can be worked out. That takes one cheap look at
the first page, so this job does not start Docling.

Stages written to job.progress:  uploading -> classifying -> storing
"""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func

from app.classification.classifier import Classification
from app.core.config import Settings
from app.db.models import Document, Job
from app.jobs.parse_document import JobFailure
from app.jobs.queue import ClaimedJob, SessionFactory, set_progress
from app.jobs.worker_process import ChildCrashed, ChildTarget, ChildTimedOut, run_in_child_process
from app.services.extracted_columns import extracted_to_columns
from app.storage.base import DocumentStorage, StorageError
from contracts.models import Extracted, Provenance

logger = logging.getLogger("unravel.jobs")

CLASSIFYING = ("classifying", 40)
STORING = ("storing", 90)

_TRY_AGAIN = "We couldn't work out what kind of document this is. You can set its type yourself, or try uploading it again."


async def run_classify_document(
    job: ClaimedJob,
    *,
    session_factory: SessionFactory,
    storage: DocumentStorage,
    settings: Settings,
    classification_target: ChildTarget,
) -> None:
    """Run one classification job to completion. Raises JobFailure if it cannot succeed."""
    document_id = UUID(job.payload["document_id"])

    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None or document.storage_path is None:
            raise JobFailure("document_missing", "This document is no longer available.", retryable=False)
        storage_path, mime_type = document.storage_path, document.mime_type

    await set_progress(session_factory, job.id, *CLASSIFYING)
    try:
        async with storage.open_to_tempfile(storage_path) as file_path:
            # A child process, like the parse: it can be stopped on timeout,
            # and the PDF and Gemini libraries stay out of the API process.
            outcome = await run_in_child_process(
                classification_target,
                (str(file_path), mime_type, settings.gemini_api_key, settings.classify_timeout_seconds),
                settings.classify_timeout_seconds,
            )
    except StorageError as exc:
        raise JobFailure(
            "storage_unavailable", "We couldn't fetch this document from storage. Please try again.", retryable=True, detail=str(exc)
        ) from exc

    if isinstance(outcome, ChildTimedOut):
        raise JobFailure("classify_timeout", _TRY_AGAIN, retryable=True, detail=f"child pid {outcome.pid} timed out")
    if isinstance(outcome, ChildCrashed):
        raise JobFailure(
            "classify_crashed", _TRY_AGAIN, retryable=True, detail=f"child pid {outcome.pid} exit code {outcome.exit_code}"
        )
    if not outcome.message.get("ok"):
        raise JobFailure(
            "classify_failed",
            _TRY_AGAIN,
            retryable=True,
            detail=f"{outcome.message.get('error_type')}: {outcome.message.get('detail')}",
        )
    try:
        result = Classification.model_validate(
            {"detected_type": outcome.message.get("detected_type"), "confidence": outcome.message.get("confidence")}
        )
        page_count = int(outcome.message.get("page_count") or 1)
    except (ValidationError, TypeError, ValueError) as exc:
        raise JobFailure("classify_failed", _TRY_AGAIN, retryable=True, detail=f"invalid child result: {exc}") from exc

    await set_progress(session_factory, job.id, *STORING)

    detected_type: Extracted[str] = Extracted(
        value=result.detected_type,
        confidence=result.confidence,
        # The label was read from the start of the document: page 1. There
        # is no single box on the page that "is" the document's type.
        provenance=Provenance(document_id=document_id, page=1, bbox=None, snippet=outcome.message.get("snippet")),
    )
    async with session_factory() as session, session.begin():
        document = await session.get(Document, document_id, with_for_update=True)
        job_row = await session.get(Job, job.id, with_for_update=True)
        if document is None or job_row is None:
            raise JobFailure("document_missing", "This document is no longer available.", retryable=False)

        # Sets _value and _original_value to the classifier's answer; a later
        # correction by the user changes only _value.
        for column, value in extracted_to_columns("detected_type", detected_type).items():
            setattr(document, column, value)
        document.page_count = page_count
        document.parse_status = "parsed"
        document.parse_error = None
        job_row.status = "succeeded"
        job_row.progress = {"step": "done", "percent": 100}
        job_row.result = {"document_id": str(document_id), "policy_id": None}
        job_row.finished_at = func.now()

    logger.info(
        "Classified document. job_id=%s document_id=%s type=%s confidence=%s cached=%s",
        job.id, document_id, result.detected_type, result.confidence, outcome.message.get("cached"),
    )
