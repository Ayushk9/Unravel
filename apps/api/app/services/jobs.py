"""Persisted in-process job runner built on FastAPI ``BackgroundTasks``."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.auth import CurrentHousehold
from app.db.models import Job
from app.db.session import build_async_session_factory


logger = logging.getLogger(__name__)
TERMINAL_STATUSES = {"succeeded", "failed"}
JOB_RETENTION = timedelta(hours=24)
JobWork = Callable[["ProgressReporter"], Awaitable[dict[str, Any] | None]]


class ProgressReporter:
    """Worker-facing progress writer; each update is visible to pollers."""

    def __init__(self, job_id: UUID, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._job_id = job_id
        self._session_factory = session_factory

    async def update(self, progress: dict[str, Any]) -> None:
        """Persist a JSON progress snapshot, e.g. ``{step, percent}``."""
        async with self._session_factory() as session:
            job = await session.get(Job, self._job_id)
            if job is None or job.status in TERMINAL_STATUSES:
                return
            job.progress = progress
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()


async def enqueue_job(
    *,
    background_tasks: BackgroundTasks,
    session: AsyncSession,
    current_household: CurrentHousehold,
    kind: str,
    work: JobWork,
    idempotency_key: str | None = None,
) -> Job:
    """Create a queued, household-scoped job and schedule it after the response."""
    if idempotency_key is not None:
        existing = await session.scalar(
            select(Job).where(
                Job.household_id == current_household.household_id,
                Job.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing

    job = Job(
        household_id=current_household.household_id,
        kind=kind,
        status="queued",
        progress={"step": "queued", "percent": 0},
        idempotency_key=idempotency_key,
    )
    session.add(job)
    try:
        await session.flush()  # Allocates the UUIDv7 before returning the 202 body.
        await session.commit()
    except IntegrityError:
        # Concurrent duplicate submissions converge on the first persisted job.
        await session.rollback()
        existing = await session.scalar(
            select(Job).where(
                Job.household_id == current_household.household_id,
                Job.idempotency_key == idempotency_key,
            )
        )
        if existing is None:
            raise
        return existing

    background_tasks.add_task(run_job, job.id, work)
    background_tasks.add_task(purge_expired_jobs)
    return job


async def run_job(job_id: UUID, work: JobWork) -> None:
    """Execute one job and persist all state transitions using a fresh session."""
    session_factory = build_async_session_factory()
    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job is None or job.status != "queued":
            return
        job.status = "running"
        job.progress = {"step": "starting", "percent": 1}
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()

    reporter = ProgressReporter(job_id, session_factory)
    try:
        result = await work(reporter)
    except Exception:
        logger.exception("Background job %s failed", job_id)
        async with session_factory() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.error = {"code": "job_failed", "message": "The job could not be completed."}
                job.updated_at = datetime.now(timezone.utc)
                await session.commit()
        return

    async with session_factory() as session:
        job = await session.get(Job, job_id)
        if job is not None:
            job.status = "succeeded"
            job.progress = {"step": "complete", "percent": 100}
            job.result = result or {}
            job.error = None
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()


async def purge_expired_jobs() -> None:
    """Best-effort cleanup, triggered by enqueueing; terminal rows live at least 24h."""
    cutoff = datetime.now(timezone.utc) - JOB_RETENTION
    session_factory = build_async_session_factory()
    async with session_factory() as session:
        await session.execute(
            delete(Job).where(Job.status.in_(TERMINAL_STATUSES), Job.updated_at < cutoff)
        )
        await session.commit()
