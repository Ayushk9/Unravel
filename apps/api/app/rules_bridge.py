"""Between the database and Engine B.

Engine B (engines/rules) is a pure library: it never touches the database.
This module does the loading: it reads the rows, builds the engine's typed
inputs, and nothing more. The judging happens entirely inside the engine.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Claim, ClaimEvent, Household, Member, Policy
from app.services.policy_reader import build_coverage_profile, coverage_terms, load_policies
from engines.rules.models import AlertInput, ClaimFacts, EligibilityInput, PolicyFacts


def policy_facts(policy: Policy) -> PolicyFacts:
    return PolicyFacts(
        policy_id=policy.id, start_date=policy.start_date, end_date=policy.end_date, first_inception_date=policy.first_inception_date
    )


async def eligibility_input(session: AsyncSession, claim: Claim) -> EligibilityInput:
    # The claim was found in this household, and so is its policy (foreign key, same household).
    [policy] = await load_policies(session, claim.household_id, policy_id=claim.policy_id, options=coverage_terms())
    intimated_at = await session.scalar(
        select(ClaimEvent.occurred_at).where(ClaimEvent.claim_id == claim.id, ClaimEvent.to_state == "intimated").order_by(ClaimEvent.seq).limit(1)
    )
    return EligibilityInput(
        policy=policy_facts(policy),
        coverage_profile=build_coverage_profile(policy),
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
    # The household's kind of city and its member count in one query, then
    # every policy's terms in a fixed number more (policy_reader.load_policies).
    member_count = select(func.count()).select_from(Member).where(Member.household_id == Household.id).scalar_subquery()
    city_tier, members = (await session.execute(select(Household.city_tier, member_count).where(Household.id == household_id))).one()
    return [
        AlertInput(
            policy=policy_facts(policy),
            coverage_profile=build_coverage_profile(policy),
            household_member_count=members,
            household_city_tier=city_tier,
        )
        for policy in await load_policies(session, household_id, options=coverage_terms())
    ]
