"""Job polling API."""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentHousehold, get_current_household
from app.db.models import Job
from app.db.session import session_scope


router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])
JobStatus = Literal["queued", "running", "succeeded", "failed"]


class JobAccepted(BaseModel):
    job_id: UUID
    kind: str
    status: Literal["queued"]


class JobRead(BaseModel):
    job_id: UUID
    kind: str
    status: JobStatus
    progress: dict[str, Any] | None
    result: dict[str, Any] | None
    error: dict[str, Any] | None


def accepted_job(job: Job) -> JobAccepted:
    """Convert a newly persisted queued job to the contract response."""
    return JobAccepted(job_id=job.id, kind=job.kind, status="queued")


def job_read(job: Job) -> JobRead:
    """Convert a persisted job to its polling representation."""
    return JobRead(
        job_id=job.id,
        kind=job.kind,
        status=job.status,  # Database writes are constrained by the runner.
        progress=job.progress,
        result=job.result,
        error=job.error,
    )


@router.get("/{job_id}", response_model=JobRead)
async def get_job(
    job_id: UUID,
    current: CurrentHousehold = Depends(get_current_household),
    session: AsyncSession = Depends(session_scope),
) -> JobRead:
    """Return a job only when it belongs to the authenticated household."""
    job = await session.scalar(
        select(Job).where(Job.id == job_id, Job.household_id == current.household_id)
    )
    if job is None:
        # Do not reveal whether an ID belongs to another household.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job_read(job)
