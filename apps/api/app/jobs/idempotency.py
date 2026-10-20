"""Idempotency-Key handling for the two endpoints that require it (D-13, D-27).

POST /documents and POST /claims/{id}/grievance-drafts. The key is stored on
the job row, unique per household. A repeat of a key with the same request
(same `request_hash`) gets the original 202 body back and creates nothing;
the same key with different content is a 409.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.models import Job as JobRow
from app.schemas.errors import FieldError
from app.schemas.jobs import JobAccepted

MAX_IDEMPOTENCY_KEY_LENGTH = 255


def require_key(key: str | None) -> str:
    """The header's value, or 422 naming the header when it is missing or too long (D-27)."""
    if not key or len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ApiError(
            422,
            "validation_error",
            "Idempotency-Key is required on this endpoint.",
            field_errors=[FieldError(field="Idempotency-Key", message="This header is required.")],
        )
    return key


def accepted(job: JobRow) -> JobAccepted:
    # Always "queued": this is the body of the ORIGINAL 202, and a replay
    # must return it unchanged even if the job has moved on since (D-13).
    return JobAccepted(job_id=job.id, kind=job.kind, status="queued")


def replay_or_conflict(existing: JobRow, request_hash: str, message: str) -> JobAccepted:
    """Same key seen before: the same request replays, different content is refused with `message` (D-27)."""
    if existing.request_hash == request_hash:
        return accepted(existing)
    raise ApiError(
        409,
        "idempotency_key_reused",
        message,
        field_errors=[FieldError(field="Idempotency-Key", message="Already used with different content.")],
    )


async def find_job_by_key(session: AsyncSession, household_id: UUID, key: str) -> JobRow | None:
    # Keys are scoped to a household: two households may use the same key.
    return await session.scalar(select(JobRow).where(JobRow.household_id == household_id, JobRow.idempotency_key == key))
