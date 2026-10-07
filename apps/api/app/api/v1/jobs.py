"""GET /jobs/{job_id} (CONTRACTS.md row 24): the endpoint clients poll."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentHousehold, get_current_household
from app.core.errors import ApiError
from app.db.models import Job as JobRow
from app.db.session import get_session
from app.schemas.jobs import Job

router = APIRouter()


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: UUID,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Job:
    # Filtering by household in the query itself means another household's
    # job id behaves exactly like one that does not exist (D-10).
    row = await session.scalar(select(JobRow).where(JobRow.id == job_id, JobRow.household_id == household.household_id))
    if row is None:
        raise ApiError(404, "not_found", "No job with that id.")
    return Job(job_id=row.id, kind=row.kind, status=row.status, progress=row.progress, result=row.result, error=row.error)
