"""Between the database and Engine B.

Engine B (engines/rules) is a pure library: it never touches the database.
This module does the loading: it reads the rows, builds the engine's typed
inputs, and nothing more. The judging happens entirely inside the engine.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Claim, ClaimEvent, Member, Policy
from app.services.policy_reader import build_coverage_profile
from engines.rules.models import AlertInput, ClaimFacts, EligibilityInput, PolicyFacts


def policy_facts(policy: Policy) -> PolicyFacts:
    return PolicyFacts(policy_id=policy.id, start_date=policy.start_date, end_date=policy.end_date)


async def eligibility_input(session: AsyncSession, claim: Claim) -> EligibilityInput:
    policy = await session.get(Policy, claim.policy_id)
    assert policy is not None  # foreign key
    intimated_at = await session.scalar(
        select(ClaimEvent.occurred_at).where(ClaimEvent.claim_id == claim.id, ClaimEvent.to_state == "intimated").order_by(ClaimEvent.seq).limit(1)
    )
    return EligibilityInput(
        policy=policy_facts(policy),
        coverage_profile=await build_coverage_profile(session, policy.id, policy.start_date),
        claim=ClaimFacts(
            claim_id=claim.id,
            admitted_on=claim.admitted_on,
            claimed_amount=claim.claimed_amount,
            intimated_at=intimated_at,
            condition_is_pre_existing=claim.condition_is_pre_existing,
            first_diagnosed_on=claim.first_diagnosed_on,
            matched_waiting_periods=tuple(claim.matched_waiting_periods) if claim.matched_waiting_periods is not None else None,
            matched_exclusions=tuple(claim.matched_exclusions) if claim.matched_exclusions is not None else None,
            planned_room_rent_per_day=claim.planned_room_rent_per_day,
        ),
    )


async def alert_inputs(session: AsyncSession, household_id) -> list[AlertInput]:
    members = await session.scalar(select(func.count()).select_from(Member).where(Member.household_id == household_id)) or 0
    policies = await session.scalars(select(Policy).where(Policy.household_id == household_id).order_by(Policy.id))
    inputs = []
    for policy in policies:
        inputs.append(
            AlertInput(
                policy=policy_facts(policy),
                coverage_profile=await build_coverage_profile(session, policy.id, policy.start_date),
                household_member_count=members,
                # Not stored anywhere yet; the room-rent alert is skipped (D-38).
                household_city=None,
            )
        )
    return inputs
