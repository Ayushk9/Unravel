"""Build the wire `Claim` from database rows: facts, event log, state and deadlines.

Nothing about a claim's state or deadlines is stored. Each read derives:

    current_state   from the claim_current_state view (latest event per claim)
    deadlines       from the events + the policy's coverage profile + the rule file

Works on a list of claims at once, with one query per kind of data rather
than one per claim, so listing ten claims costs the same number of queries
as fetching one.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.claims.deadlines import ClaimFacts, EventFact, compute_deadlines
from app.db.models import Claim as ClaimRow
from app.db.models import ClaimEvent as ClaimEventRow
from app.db.models import CoverageProfile, claim_current_state
from app.rules.loader import load_deadline_rules
from app.schemas.claims import Claim, ClaimEvent


async def find_claim_row(session: AsyncSession, household_id: UUID, claim_id: UUID) -> ClaimRow | None:
    """The claim, only if it belongs to this household (D-10)."""
    return await session.scalar(select(ClaimRow).where(ClaimRow.id == claim_id, ClaimRow.household_id == household_id))


async def list_claim_rows(session: AsyncSession, household_id: UUID) -> list[ClaimRow]:
    rows = await session.scalars(select(ClaimRow).where(ClaimRow.household_id == household_id).order_by(ClaimRow.id))
    return list(rows)


async def build_claims(session: AsyncSession, rows: list[ClaimRow], today: date) -> list[Claim]:
    """`today` is passed in by the caller; no code below reads the clock."""
    if not rows:
        return []
    claim_ids = [row.id for row in rows]

    events_by_claim: dict[UUID, list[ClaimEventRow]] = defaultdict(list)
    for event in await session.scalars(
        select(ClaimEventRow).where(ClaimEventRow.claim_id.in_(claim_ids)).order_by(ClaimEventRow.claim_id, ClaimEventRow.seq)
    ):
        events_by_claim[event.claim_id].append(event)

    state_rows = await session.execute(
        select(claim_current_state.c.claim_id, claim_current_state.c.current_state).where(
            claim_current_state.c.claim_id.in_(claim_ids)
        )
    )
    state_by_claim = {claim_id: state for claim_id, state in state_rows}

    hours_rows = await session.execute(
        select(CoverageProfile.policy_id, CoverageProfile.intimation_deadline_hours_value).where(
            CoverageProfile.policy_id.in_({row.policy_id for row in rows})
        )
    )
    intimation_hours_by_policy = {policy_id: hours for policy_id, hours in hours_rows}

    rules = load_deadline_rules()
    claims = []
    for row in rows:
        events = events_by_claim[row.id]
        current_state = state_by_claim[row.id]
        facts = ClaimFacts(
            claim_id=row.id,
            current_state=current_state,
            admitted_on=row.admitted_on,
            events=tuple(EventFact(seq=e.seq, to_state=e.to_state, occurred_at=e.occurred_at) for e in events),
        )
        deadlines, omitted = compute_deadlines(facts, intimation_hours_by_policy.get(row.policy_id), rules, today)
        claims.append(
            Claim(
                id=row.id,
                policy_id=row.policy_id,
                member_id=row.member_id,
                claim_type=row.claim_type,
                admission_type=row.admission_type,
                hospital_name=row.hospital_name,
                admitted_on=row.admitted_on,
                discharged_on=row.discharged_on,
                claimed_amount=row.claimed_amount,
                settled_amount=row.settled_amount,
                current_state=current_state,
                events=[
                    ClaimEvent(
                        id=e.id,
                        claim_id=e.claim_id,
                        from_state=e.from_state,
                        to_state=e.to_state,
                        occurred_at=e.occurred_at,
                        note=e.note,
                        source=e.source,
                    )
                    for e in events
                ],
                deadlines=deadlines,
                omitted_deadlines=omitted,
            )
        )
    return claims
