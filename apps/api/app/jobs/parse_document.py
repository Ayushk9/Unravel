"""The `parse_document` job: one uploaded file, from storage to stored policy.

Stages, each written to job.progress so a polling client can show them:

    uploading          set when the job is created (app/api/v1/documents.py)
    parsing_layout     Engine A is running in a child process
    extracting_fields  Engine A has returned; its output is being checked
    storing            the result is being written to the database
    indexing           each chunk gets its search vector (D-42); see below

Engine A is one function call with no progress callbacks, and its signature
is not changed. Its two internal stages (Docling layout parsing, then Gemini
field extraction) therefore both happen while the job says "parsing_layout".
The percentages are fixed markers for each stage, not a measurement.
"""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func

from app.core.config import Settings
from app.db.models import Document, Job
from app.jobs.queue import ClaimedJob, SessionFactory, set_progress
from app.jobs.worker_process import ChildCrashed, ChildTarget, ChildTimedOut, run_in_child_process
from app.models_server.client import Models, ModelServerError
from app.qa.indexing import index_document
from app.services.policy_writer import store_extraction
from app.storage.base import DocumentStorage, StorageError
from contracts.models import ExtractionResult

logger = logging.getLogger("unravel.jobs")

UPLOADING = ("uploading", 5)
PARSING_LAYOUT = ("parsing_layout", 20)
EXTRACTING_FIELDS = ("extracting_fields", 80)
STORING = ("storing", 90)
INDEXING = ("indexing", 95)

PDF_CONTENT_TYPE = "application/pdf"


class JobFailure(Exception):
    """A job cannot be completed, for a reason we can explain to the user.

    `message` is shown to the user. `detail` goes to the server log only.
    """

    def __init__(self, code: str, message: str, *, retryable: bool, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.detail = detail


async def run_parse_document(
    job: ClaimedJob,
    *,
    session_factory: SessionFactory,
    storage: DocumentStorage,
    settings: Settings,
    extraction_target: ChildTarget,
    models: Models | None = None,
) -> None:
    """Run one parse job to completion. Raises JobFailure if it cannot succeed."""
    document_id = UUID(job.payload["document_id"])
    document_kind = job.payload["document_kind"]

    async with session_factory() as session:
        document = await session.get(Document, document_id)
        if document is None or document.storage_path is None:
            raise JobFailure("document_missing", "This document is no longer available.", retryable=False)
        storage_path, mime_type = document.storage_path, document.mime_type

    if mime_type != PDF_CONTENT_TYPE:
        # Engine A reads PDFs only. Fail now with a clear reason rather than
        # start a parse that is certain to fail.
        raise JobFailure(
            "unsupported_document",
            "Image documents can't be read yet. Please upload the policy as a PDF.",
            retryable=False,
        )

    await set_progress(session_factory, job.id, *PARSING_LAYOUT)
    try:
        # The temporary file exists only inside this block. It is deleted on
        # the way out whether the parse succeeded, failed or timed out.
        async with storage.open_to_tempfile(storage_path) as file_path:
            outcome = await run_in_child_process(
                extraction_target,
                (str(file_path), document_kind, settings.gemini_api_key, settings.gemini_model, settings.parse_timeout_seconds),
                settings.parse_timeout_seconds,
            )
    except StorageError as exc:
        raise JobFailure(
            "storage_unavailable",
            "We couldn't fetch this document from storage. Please try again.",
            retryable=True,
            detail=str(exc),
        ) from exc

    if isinstance(outcome, ChildTimedOut):
        minutes = max(1, round(settings.parse_timeout_seconds / 60))
        raise JobFailure(
            "parse_timeout",
            f"Reading this document took longer than {minutes} minutes and was stopped. "
            "Try again, or upload a smaller or clearer file.",
            retryable=True,
            detail=f"child pid {outcome.pid} terminated after {settings.parse_timeout_seconds}s",
        )
    if isinstance(outcome, ChildCrashed):
        raise JobFailure(
            "parse_crashed",
            "The document reader stopped unexpectedly. Please try again.",
            retryable=True,
            detail=f"child pid {outcome.pid} exited with code {outcome.exit_code} without answering",
        )
    if not outcome.message.get("ok"):
        raise JobFailure(
            "parse_failed",
            "We couldn't read this document. It may be damaged, password-protected or not a readable PDF.",
            retryable=False,
            detail=f"{outcome.message.get('error_type')}: {outcome.message.get('detail')}",
        )

    await set_progress(session_factory, job.id, *EXTRACTING_FIELDS)
    try:
        # The child is a separate program; its answer is validated like any
        # other input before it is trusted.
        result = ExtractionResult.model_validate_json(outcome.message["result_json"])
    except (KeyError, ValidationError) as exc:
        raise JobFailure(
            "parse_failed",
            "We couldn't make sense of this document's contents. Please try again.",
            retryable=True,
            detail=f"child returned an invalid result: {exc}",
        ) from exc

    await set_progress(session_factory, job.id, *STORING)

    # The policy rows and the document's new status are committed first; the
    # job itself is marked succeeded only after indexing (below), so a client
    # polling it sees "indexing" before "done".
    async with session_factory() as session, session.begin():
        document = await session.get(Document, document_id, with_for_update=True)
        job_row = await session.get(Job, job.id, with_for_update=True)
        if document is None or job_row is None:
            raise JobFailure("document_missing", "This document is no longer available.", retryable=False)

        policy_id = await store_extraction(session, document, result)

        document.parse_status = "parsed"
        document.parse_error = None

    # INDEXING. A failure here does not fail the parse: the policy is fully
    # usable without search vectors except for Q&A, which answers 409
    # policy_not_indexed until scripts/index_chunks.py fills them in.
    indexed_warning = None
    if policy_id is not None:
        await set_progress(session_factory, job.id, *INDEXING)
        if models is None:
            # No model server on this process (MODEL_SERVER_ENABLED=false). Not a
            # failure of this document; questions answer 409 until it is indexed.
            logger.info("Indexing skipped: no model server. document_id=%s", document_id)
        else:
            try:
                count = await index_document(session_factory, models, document_id)
                logger.info("Indexed document. document_id=%s chunks=%s", document_id, count)
            except ModelServerError as exc:
                logger.warning("Indexing failed. document_id=%s detail=%s", document_id, exc)
                indexed_warning = "Not indexed for questions yet: the search models were unavailable. It can be indexed later."

    async with session_factory() as session, session.begin():
        job_row = await session.get(Job, job.id, with_for_update=True)
        if job_row is None:
            raise JobFailure("document_missing", "This document is no longer available.", retryable=False)
        if indexed_warning:
            document = await session.get(Document, document_id, with_for_update=True)
            if document is not None:
                document.warnings = [*(document.warnings or []), indexed_warning]
        job_row.status = "succeeded"
        job_row.progress = {"step": "done", "percent": 100}
        job_row.result = {"document_id": str(document_id), "policy_id": str(policy_id) if policy_id else None}
        job_row.finished_at = func.now()

    logger.info("Parsed document. job_id=%s document_id=%s policy_id=%s", job.id, document_id, policy_id)
