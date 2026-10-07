"""Policy endpoints.

GET   /policies                                               CONTRACTS.md row 7
GET   /policies/{id}                                          CONTRACTS.md row 9
PATCH /policies/{id}/coverage-profile/fields/{field_path}     CONTRACTS.md row 10, D-15
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentHousehold, get_current_household
from app.core.errors import ApiError
from app.db.session import get_session
from app.schemas.errors import FieldError
from app.schemas.policies import FieldCorrectionRequest, Policy
from app.services.field_correction import correct_field, find_profile
from app.services.policy_reader import build_policy, find_policy_row, list_policy_rows

router = APIRouter()


def _policy_not_found() -> ApiError:
    return ApiError(404, "not_found", "No policy with that id belongs to your household.")


@router.get("/policies")
async def list_policies(
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Policy]:
    """A full array, not paginated: a household has a handful of policies (API_DECISIONS section 5)."""
    rows = await list_policy_rows(session, household.household_id)
    return [await build_policy(session, row) for row in rows]


@router.get("/policies/{policy_id}")
async def get_policy(
    policy_id: UUID,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Policy:
    row = await find_policy_row(session, household.household_id, policy_id)
    if row is None:
        raise _policy_not_found()
    return await build_policy(session, row)


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
    return await build_policy(session, row)
