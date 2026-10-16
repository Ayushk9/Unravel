"""The job queue. The `job` table IS the queue; there is no other one.

A job's whole life is a row changing state:

    queued  ->  running  ->  succeeded
                         ->  failed

Because every piece of state is in the database, nothing is lost when the
server restarts, and whoever runs jobs does not have to be this process. A
separate worker program on another machine could call the same functions in
this file against the same database and the API would not need to change.

Each function opens its own short transaction. A job that takes minutes to
run must not hold a database transaction open for that whole time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Document, Job

SessionFactory = async_sessionmaker[AsyncSession]

# Finished jobs are kept this long so a client that reloads the page can
# still fetch the result (D-07), and so an Idempotency-Key can be replayed
# (D-13). After that they are deleted.
JOB_RETENTION = timedelta(hours=24)

INTERRUPTED_MESSAGE = "This document was being read when the server restarted. Please upload it again."
INTERRUPTED_QUESTION_MESSAGE = "This question was being answered when the server restarted. Please ask it again."


def interrupted_message(kind: str) -> str:
    return INTERRUPTED_QUESTION_MESSAGE if kind == "answer_question" else INTERRUPTED_MESSAGE


@dataclass(frozen=True)
class ClaimedJob:
    """The parts of a job row a worker needs, copied out of the session."""

    id: UUID
    household_id: UUID
    kind: str
    payload: dict[str, Any]


def _document_id(payload: dict[str, Any] | None) -> UUID | None:
    value = (payload or {}).get("document_id")
    return UUID(value) if value else None


async def claim_next_job(session_factory: SessionFactory, kinds: tuple[str, ...] | None = None) -> ClaimedJob | None:
    """Take the oldest queued job (of one of `kinds`, if given) and mark it running, or return None.

    `kinds` lets the runner keep separate lanes: questions are never stuck
    behind a five-minute parse (app/jobs/runner.py).

    The important part is `FOR UPDATE SKIP LOCKED`:

      FOR UPDATE   locks the selected row until this transaction ends, so
                   nobody else can change it in the meantime.
      SKIP LOCKED  tells any other worker running this same query at the same
                   moment to pass over a locked row instead of waiting for it.

    Together they guarantee that two workers can never claim the same job,
    without any lock held in application memory. This is the standard way to
    use a Postgres table as a work queue.

    Ordering by id is oldest-first, because ids are UUIDv7 (time-ordered).
    """
    async with session_factory() as session, session.begin():
        query = select(Job).where(Job.status == "queued")
        if kinds is not None:
            query = query.where(Job.kind.in_(kinds))
        job = await session.scalar(query.order_by(Job.id).limit(1).with_for_update(skip_locked=True))
        if job is None:
            return None

        job.status = "running"
        job.started_at = func.now()

        document_id = _document_id(job.payload)
        if document_id is not None:
            await session.execute(update(Document).where(Document.id == document_id).values(parse_status="parsing"))

        return ClaimedJob(id=job.id, household_id=job.household_id, kind=job.kind, payload=dict(job.payload or {}))


async def set_progress(session_factory: SessionFactory, job_id: UUID, step: str, percent: int) -> None:
    """Record which stage a running job has reached, for clients polling it."""
    async with session_factory() as session, session.begin():
        await session.execute(
            update(Job).where(Job.id == job_id, Job.status == "running").values(progress={"step": step, "percent": percent})
        )


async def mark_failed(
    session_factory: SessionFactory, job_id: UUID, *, code: str, message: str, retryable: bool
) -> None:
    """End a job as failed, and its document with it.

    `message` is shown to the user, so it must be a plain sentence and never
    a stack trace. A job that has already finished is left alone.
    """
    async with session_factory() as session, session.begin():
        job = await session.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is None or job.status in ("succeeded", "failed"):
            return
        _fail(job, code=code, message=message, retryable=retryable)
        await _fail_document(session, job, message)


async def recover_interrupted_jobs(session_factory: SessionFactory) -> int:
    """Fail every job still marked `running`. Called once, at startup.

    A job is `running` only while a worker is actively processing it. If the
    server is starting up, no worker of this process can be mid-job, so any
    `running` row is left over from a crash or restart: its worker is gone
    and nothing will ever finish it. Without this step such a job would stay
    `running` forever and the user would watch a progress bar that never ends.

    The job is not re-run automatically. It is marked failed and retryable,
    and the user uploads again.

    Note for a future multi-worker setup: "running at startup means dead" is
    only true while there is a single worker. With several, each worker would
    record a heartbeat time on its job and this function would fail only jobs
    whose heartbeat is stale.
    """
    async with session_factory() as session, session.begin():
        jobs = (await session.scalars(select(Job).where(Job.status == "running").with_for_update())).all()
        for job in jobs:
            message = interrupted_message(job.kind)
            _fail(job, code="interrupted", message=message, retryable=True)
            await _fail_document(session, job, message)
        return len(jobs)


async def delete_expired_jobs(session_factory: SessionFactory) -> int:
    """Delete finished jobs older than the retention period. Returns how many."""
    async with session_factory() as session, session.begin():
        result = await session.execute(
            delete(Job).where(
                Job.status.in_(("succeeded", "failed")),
                Job.finished_at < func.now() - JOB_RETENTION,
            )
        )
        return result.rowcount


def _fail(job: Job, *, code: str, message: str, retryable: bool) -> None:
    job.status = "failed"
    job.error = message
    job.error_code = code
    job.retryable = retryable
    job.finished_at = func.now()


async def _fail_document(session: AsyncSession, job: Job, message: str) -> None:
    """Mark the job's document failed too, unless it was already stored as parsed.

    A parse commits the policy, then indexes, then marks the job succeeded
    (parse_document.py). If the server stops during indexing, the job is
    failed but the document and its policy are fine and must stay "parsed".
    """
    document_id = _document_id(job.payload)
    if document_id is not None:
        await session.execute(
            update(Document)
            .where(Document.id == document_id, Document.parse_status != "parsed")
            .values(parse_status="failed", parse_error=message)
        )
