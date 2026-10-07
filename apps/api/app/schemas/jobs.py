"""Wire shapes for long-running jobs (API_DECISIONS D-07)."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from app.schemas.base import ApiModel

JobKind = Literal["parse_document", "answer_question", "generate_grievance_draft"]
JobStatus = Literal["queued", "running", "succeeded", "failed"]


class JobAccepted(ApiModel):
    """Body of a 202 response: the job exists and is waiting to run."""

    job_id: UUID
    kind: JobKind
    status: Literal["queued"]


class JobProgress(ApiModel):
    step: str
    percent: int


class Job(ApiModel):
    """What GET /jobs/{job_id} returns while a client polls."""

    job_id: UUID
    kind: JobKind
    status: JobStatus
    progress: JobProgress | None
    # For parse_document: {"document_id": ..., "policy_id": ... or null}.
    result: dict[str, Any] | None
    # A sentence for the user, or null. Never a stack trace (D-28).
    error: str | None
