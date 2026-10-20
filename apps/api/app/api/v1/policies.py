"""Policy endpoints.

GET   /policies                                               CONTRACTS.md row 7
GET   /policies/{id}                                          CONTRACTS.md row 9
PATCH /policies/{id}                                          CONTRACTS.md row 27, D-39, D-46
PATCH /policies/{id}/coverage-profile/fields/{field_path}     CONTRACTS.md row 10, D-15
POST  /policies/{id}/questions                                CONTRACTS.md row 11, D-42
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.deadlines import india_date
from app.core.auth import CurrentHousehold, get_current_household
from app.core.errors import ApiError
from app.core.ids import new_id
from app.db.models import Job as JobRow
from app.qa.indexing import index_counts
from app.schemas.jobs import JobAccepted
from app.schemas.questions import QuestionRequest
from app.db.session import get_session
from app.schemas.errors import FieldError
from app.schemas.policies import FieldCorrectionRequest, Policy, PolicyUpdate
from app.services.field_correction import correct_field, find_profile
from app.services.policy_update import apply_policy_update
from app.services.policy_reader import build_policy, find_policy_row, load_policies, load_policy

router = APIRouter()


def _policy_not_found() -> ApiError:
    return ApiError(404, "not_found", "No policy with that id belongs to your household.")


@router.get("/policies")
async def list_policies(
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Policy]:
    """A full array, not paginated: a household has a handful of policies (API_DECISIONS section 5)."""
    # A fixed number of queries however many policies there are (policy_reader.load_policies).
    return [build_policy(row) for row in await load_policies(session, household.household_id)]


@router.get("/policies/{policy_id}")
async def get_policy(
    policy_id: UUID,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Policy:
    row = await load_policy(session, household.household_id, policy_id)
    if row is None:
        raise _policy_not_found()
    return build_policy(row)


async def _reloaded(session: AsyncSession, household_id: UUID, policy_id: UUID) -> Policy:
    """The policy as stored, after a change was committed."""
    row = await load_policy(session, household_id, policy_id)
    assert row is not None  # it was found before the change, and nothing deletes it
    return build_policy(row)


@router.patch("/policies/{policy_id}")
async def update_policy(
    policy_id: UUID,
    body: PolicyUpdate,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Policy:
    """Set what the user copies from their schedule: insurer, product and number (D-46), and the dates (D-39)."""
    row = await find_policy_row(session, household.household_id, policy_id)
    if row is None:
        raise _policy_not_found()
    apply_policy_update(row, body, india_date(datetime.now(timezone.utc)))
    await session.commit()
    return await _reloaded(session, household.household_id, policy_id)


# `:path` lets the parameter contain dots and be matched whole; the service
# then checks it against an explicit allow-list.
@router.patch("/policies/{policy_id}/coverage-profile/fields/{field_path:path}")
async def correct_policy_field(
    policy_id: UUID,
    field_path: str,
    body: FieldCorrectionRequest,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Policy:
    """Record the user's confirmed or corrected value for one field.

    Returns the whole updated policy, so the client can replace what it has
    without a second request.
    """
    row = await find_policy_row(session, household.household_id, policy_id)
    if row is None:
        raise _policy_not_found()

    if body.user_confirmed is not True:
        # This endpoint exists to record "the user says this is right". There
        # is no way to un-confirm through it.
        raise ApiError(
            422,
            "validation_error",
            "user_confirmed must be true.",
            field_errors=[FieldError(field="user_confirmed", message="Must be true.")],
        )

    profile = await find_profile(session, policy_id)
    if profile is None:
        raise ApiError(409, "profile_not_ready", "This policy's coverage profile isn't ready yet.")

    await correct_field(session, profile, field_path, body.value)
    await session.commit()
    return await _reloaded(session, household.household_id, policy_id)


@router.post("/policies/{policy_id}/questions", status_code=202)
async def ask_question(
    policy_id: UUID,
    body: QuestionRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> JobAccepted:
    """Queue a question about this policy. The answer arrives through GET /jobs/{id} (D-07, D-42)."""
    row = await find_policy_row(session, household.household_id, policy_id)
    if row is None:
        raise _policy_not_found()

    # Every clause must have its search vector, or the answer could miss the one that matters.
    total, indexed = await index_counts(session, row.source_document_id)
    if total == 0 or indexed < total:
        raise ApiError(
            409,
            "policy_not_indexed",
            "This policy hasn't been prepared for questions yet. Try again once it has finished processing.",
            retryable=True,
        )

    job = JobRow(
        id=new_id(),
        household_id=household.household_id,
        kind="answer_question",
        status="queued",
        progress={"step": "queued", "percent": 0},
        payload={"policy_id": str(policy_id), "question": body.question},
    )
    session.add(job)
    await session.commit()
    # Only a nudge: the job is already committed, whether or not this runs.
    background_tasks.add_task(request.app.state.runner.wake)
    return JobAccepted(job_id=job.id, kind="answer_question", status="queued")
