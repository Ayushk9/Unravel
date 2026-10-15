"""The caller's household (D-40).

GET   /household    the household: id, name, city_tier
PATCH /household    set or clear city_tier

There is no household id in the path: the household is always the one the
login token belongs to (D-10).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentHousehold, get_current_household
from app.db.models import Household as HouseholdRow
from app.db.session import get_session
from app.schemas.household import Household, HouseholdUpdate

router = APIRouter()


async def _load(session: AsyncSession, household: CurrentHousehold) -> HouseholdRow:
    row = await session.get(HouseholdRow, household.household_id)
    assert row is not None  # get_current_household just found it
    return row


@router.get("/household")
async def get_household(
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Household:
    return Household.model_validate(await _load(session, household))


@router.patch("/household")
async def update_household(
    body: HouseholdUpdate,
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Household:
    row = await _load(session, household)
    row.city_tier = body.city_tier
    await session.commit()
    return Household.model_validate(row)
