"""Recording what the user tells us about a claim (PUT /claims/{id}/facts, D-37).

Unlike the event log, facts can be changed: the user may correct an answer.
They are checked against the policy before being stored, so a selection
always points at a real entry of the right kind.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.db.models import Claim, CoverageProfile, Exclusion, WaitingPeriod
from app.schemas.claims import ClaimFacts
from app.schemas.errors import FieldError


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(422, "validation_error", "Those claim facts aren't valid.", field_errors=[FieldError(field=field, message=message)])


async def save_facts(session: AsyncSession, claim: Claim, facts: ClaimFacts, today: date) -> None:
    if facts.first_diagnosed_on is not None and facts.first_diagnosed_on > today:
        raise _invalid("first_diagnosed_on", "Can't be in the future.")

    profile_id = await session.scalar(select(CoverageProfile.id).where(CoverageProfile.policy_id == claim.policy_id))
    if facts.matched_waiting_periods:
        kinds = (
            list(await session.scalars(
                select(WaitingPeriod.kind).where(WaitingPeriod.coverage_profile_id == profile_id).order_by(WaitingPeriod.position)
            ))
            if profile_id
            else []
        )
        _check_positions("matched_waiting_periods", facts.matched_waiting_periods, len(kinds))
        for position in facts.matched_waiting_periods:
            if kinds[position] != "disease_specific":
                raise _invalid("matched_waiting_periods", f"Entry {position} is not a condition-specific waiting period.")
    if facts.matched_exclusions:
        count = (
            len(list(await session.scalars(select(Exclusion.id).where(Exclusion.coverage_profile_id == profile_id))))
            if profile_id
            else 0
        )
        _check_positions("matched_exclusions", facts.matched_exclusions, count)

    claim.diagnosis = facts.diagnosis
    claim.condition_is_pre_existing = facts.condition_is_pre_existing
    claim.first_diagnosed_on = facts.first_diagnosed_on
    claim.matched_waiting_periods = facts.matched_waiting_periods
    claim.matched_exclusions = facts.matched_exclusions
    claim.planned_room_rent_per_day = facts.planned_room_rent_per_day
    claim.denial_ground = facts.denial_ground
    await session.commit()


def _check_positions(field: str, positions: list[int], length: int) -> None:
    if len(set(positions)) != len(positions):
        raise _invalid(field, "Each entry may be chosen only once.")
    for position in positions:
        if position >= length:
            raise _invalid(field, f"Entry {position} does not exist in this policy's list.")
