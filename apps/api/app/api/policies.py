"""Policy reads and targeted extraction corrections."""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.serializers import policy_read
from app.core.auth import CurrentHousehold, get_current_household
from app.db.models import CoverageProfile, Member, Policy, SubLimit, WaitingPeriod
from app.db.session import session_scope


router = APIRouter(prefix="/api/v1/policies", tags=["policies"])


class FieldCorrection(BaseModel):
    value: str | int | float | bool | None
    user_confirmed: Literal[True]


def _policy_options() -> list[Any]:
    return [
        selectinload(Policy.insurer),
        selectinload(Policy.coverage_profile).selectinload(CoverageProfile.sub_limits),
        selectinload(Policy.coverage_profile).selectinload(CoverageProfile.waiting_periods),
        selectinload(Policy.coverage_profile).selectinload(CoverageProfile.exclusions),
    ]


async def _load_policy(session: AsyncSession, policy_id: UUID, household_id: UUID) -> Policy:
    policy = await session.scalar(
        select(Policy).where(Policy.id == policy_id, Policy.household_id == household_id).options(*_policy_options())
    )
    if policy is None:
        raise HTTPException(status_code=404, detail="Policy not found.")
    return policy


async def _members(session: AsyncSession, household_id: UUID) -> list[Member]:
    return list(await session.scalars(select(Member).where(Member.household_id == household_id).order_by(Member.full_name)))


@router.get("")
async def list_policies(
    current: CurrentHousehold = Depends(get_current_household),
    session: AsyncSession = Depends(session_scope),
) -> dict[str, object]:
    policies = list(await session.scalars(select(Policy).where(Policy.household_id == current.household_id).options(*_policy_options())))
    members = await _members(session, current.household_id)
    return {"items": [policy_read(policy, members) for policy in policies], "next_cursor": None, "total": len(policies)}


@router.get("/{id}")
async def get_policy(
    id: UUID,
    current: CurrentHousehold = Depends(get_current_household),
    session: AsyncSession = Depends(session_scope),
) -> dict[str, object]:
    return policy_read(await _load_policy(session, id, current.household_id), await _members(session, current.household_id))


@router.patch("/{id}/coverage-profile/fields/{field_path:path}")
async def correct_coverage_field(
    id: UUID,
    field_path: Annotated[str, Path(min_length=1)],
    correction: FieldCorrection,
    current: CurrentHousehold = Depends(get_current_household),
    session: AsyncSession = Depends(session_scope),
) -> dict[str, object]:
    """Correct one extracted value while retaining the parser value and evidence."""
    policy = await _load_policy(session, id, current.household_id)
    profile = policy.coverage_profile
    if profile is None:
        raise HTTPException(status_code=409, detail="Policy extraction has not completed.")

    target: object
    attribute: str
    original_attribute: str
    if field_path in {"sum_insured", "co_pay_percent", "intimation_deadline_hours"}:
        target, attribute = profile, f"{field_path}_value"
        original_attribute = f"{field_path}_original_value"
    else:
        parts = field_path.split(".")
        if len(parts) == 3 and parts[0] == "sub_limits" and parts[2] == "cap_amount":
            target = next((item for item in profile.sub_limits if item.category == parts[1]), None)
            attribute, original_attribute = "cap_amount_value", "cap_amount_original_value"
        elif len(parts) == 3 and parts[0] == "waiting_periods" and parts[2] == "months":
            target = next((item for item in profile.waiting_periods if item.kind == parts[1]), None)
            attribute, original_attribute = "months_value", "months_original_value"
        else:
            target = None
            attribute = original_attribute = ""
    if target is None:
        raise HTTPException(status_code=422, detail="Unsupported coverage field path.")

    if getattr(target, original_attribute) is None:
        setattr(target, original_attribute, getattr(target, attribute))
    setattr(target, attribute, correction.value)
    setattr(target, attribute.removesuffix("_value") + "_user_confirmed", True)
    await session.commit()
    return policy_read(policy, await _members(session, current.household_id))
