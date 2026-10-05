"""GET /members (CONTRACTS.md row 12): the caller's household members."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import CurrentHousehold, get_current_household
from app.db.models import Member as MemberRow
from app.db.session import get_session
from app.schemas.household import Member

router = APIRouter()


@router.get("/members")
async def list_members(
    household: Annotated[CurrentHousehold, Depends(get_current_household)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[Member]:
    """A full array, not paginated (API_DECISIONS section 5)."""
    # The household comes from the token, never from the request (D-10).
    # Ordering by id is ordering by creation time, because ids are UUIDv7.
    rows = await session.scalars(
        select(MemberRow).where(MemberRow.household_id == household.household_id).order_by(MemberRow.id)
    )
    return [Member.model_validate(row) for row in rows]
