"""Put the demo back to its panel starting state, without touching the event log.

    SAMPLE-0001 (the Star policy)   its 36-month PED waiting period UNCONFIRMED, at the
                                    parser's original value, so it can be confirmed live
    SAMPLE-0002 (Rajan's policy)    its 36-month PED waiting period CONFIRMED, through the
                                    same code as PATCH .../coverage-profile/fields/{path}
    the demo claims                 their facts as scripts/seed_demo_claims.py seeds them,
                                    through the same code as PUT /claims/{id}/facts

The claim event log is append-only and is never changed here. Each demo
claim's log is compared with the seeded one:

    an event beyond the seeded ones   reported, never removed; the claim keeps that state
    a missing grievance step (D-49)   appended with --apply, as seed_demo_claims.py would

Dry run by default: it prints what it would change and changes nothing.

Run from apps/api, after scripts/seed_demo_claims.py:
    ../../.venv/bin/python scripts/reset_demo_state.py           show what would change
    ../../.venv/bin/python scripts/reset_demo_state.py --apply   change it
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.claims.deadlines import india_date  # noqa: E402
from app.claims.facts import save_facts  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models import Claim, ClaimEvent, CoverageProfile, Policy, WaitingPeriod  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.schemas.claims import ClaimFacts  # noqa: E402
from app.services.field_correction import correct_field  # noqa: E402
from seed_demo_claims import CLAIMS, GRIEVANCE_STEPS, INDIA, RENEWED_POLICY_ID, STAR_IDENTITY, seed_grievance_steps  # noqa: E402

PED_MONTHS = 36  # the value both policies' PED rows must hold; a different one is reported, never overwritten


async def ped_row(session: AsyncSession, policy: Policy) -> WaitingPeriod:
    profile_id = await session.scalar(select(CoverageProfile.id).where(CoverageProfile.policy_id == policy.id))
    rows = list(await session.scalars(
        select(WaitingPeriod).where(WaitingPeriod.coverage_profile_id == profile_id, WaitingPeriod.kind == "pre_existing")
    ))
    if len(rows) != 1:
        raise SystemExit(f"{policy.policy_number} has {len(rows)} pre-existing waiting periods, not one. Nothing changed.")
    return rows[0]


async def reset_star(session: AsyncSession, apply: bool) -> str:
    """SAMPLE-0001: the PED period back to the parser's value, unconfirmed."""
    star = await session.scalar(select(Policy).where(Policy.policy_number == STAR_IDENTITY.policy_number))
    if star is None:
        raise SystemExit("SAMPLE-0001 not found. Run scripts/seed_demo_claims.py first.")
    row = await ped_row(session, star)
    if row.months_original_value != PED_MONTHS:
        return f"left alone: the parser's value is {row.months_original_value}, not {PED_MONTHS}"
    if row.months_value == row.months_original_value and not row.months_user_confirmed:
        return f"already unconfirmed at {row.months_value:g} months"
    was = f"{row.months_value:g} months, confirmed={row.months_user_confirmed}"
    if apply:
        # The reverse of apply_correction: the original value and the provenance were never changed.
        row.months_value = row.months_original_value
        row.months_user_confirmed = False
    return f"{'set' if apply else 'would set'} to {row.months_original_value:g} months, unconfirmed (was {was})"


async def reset_renewed(session: AsyncSession, apply: bool) -> str:
    """SAMPLE-0002: the PED period confirmed at 36 months, by the PATCH route's own code."""
    renewed = await session.get(Policy, RENEWED_POLICY_ID)
    if renewed is None:
        raise SystemExit("SAMPLE-0002 not found. Run scripts/seed_demo_claims.py first.")
    row = await ped_row(session, renewed)
    if row.months_value == PED_MONTHS and row.months_user_confirmed:
        return f"already confirmed at {PED_MONTHS} months"
    if row.months_original_value != PED_MONTHS:
        return f"left alone: the parser's value is {row.months_original_value}, not {PED_MONTHS}"
    was = f"{row.months_value:g} months, confirmed={row.months_user_confirmed}"
    if apply:
        profile = await session.scalar(select(CoverageProfile).where(CoverageProfile.policy_id == renewed.id))
        await correct_field(session, profile, f"waiting_periods.{row.position}.months", PED_MONTHS)
    return f"{'confirmed' if apply else 'would confirm'} at {PED_MONTHS} months (was {was})"


def facts_of(claim: Claim) -> ClaimFacts:
    return ClaimFacts(**{name: getattr(claim, name) for name in ClaimFacts.model_fields})


async def reset_claims(session: AsyncSession, apply: bool) -> tuple[list[str], list[str], bool]:
    """Each demo claim's facts back to the seeded ones; its event log compared, never changed."""
    facts_lines, event_lines, steps_missing = [], [], False
    today = india_date(datetime.now(INDIA))
    for demo in CLAIMS:
        claim = await session.get(Claim, demo.id)
        if claim is None:
            facts_lines.append(f"{demo.member}: claim missing. Run scripts/seed_demo_claims.py.")
            continue
        seeded = ClaimFacts(**demo.facts)
        changed = [name for name in ClaimFacts.model_fields if getattr(facts_of(claim), name) != getattr(seeded, name)]
        if not changed:
            facts_lines.append(f"{demo.member}: facts as seeded")
        else:
            if apply:
                await save_facts(session, claim, seeded, today)  # commits
            facts_lines.append(f"{demo.member}: {'reset' if apply else 'would reset'} {', '.join(changed)}")

        expected = [state for state, _, _ in demo.events] + [state for state, _, _ in GRIEVANCE_STEPS.get(demo.id, ())]
        events = list(await session.scalars(select(ClaimEvent).where(ClaimEvent.claim_id == demo.id).order_by(ClaimEvent.seq)))
        logged = [event.to_state for event in events]
        if logged == expected:
            event_lines.append(f"{demo.member}: {len(events)} events as seeded, state {logged[-1]}")
        elif logged == expected[: len(logged)]:
            steps_missing = True
            event_lines.append(f"{demo.member}: missing {', '.join(expected[len(logged):])}"
                               f" ({'appended below' if apply else 'would be appended with --apply'})")
        else:
            # Where the log first differs from the seeded one, every event from there on is extra.
            first = next((i for i, (a, b) in enumerate(zip(logged, expected)) if a != b), min(len(logged), len(expected)))
            event_lines.append(f"{demo.member}: EXTRA events, which stay (the log is append-only); the claim is now {logged[-1]}:")
            for event in events[first:]:
                event_lines.append(f"    seq {event.seq}: {event.from_state} -> {event.to_state}, "
                                   f"{event.occurred_at.astimezone(INDIA):%d %b %Y %H:%M}, {event.note or 'no note'}")
    return facts_lines, event_lines, steps_missing


async def main(apply: bool) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    async with factory() as session:
        star = await reset_star(session, apply)
        renewed = await reset_renewed(session, apply)
        if apply:
            await session.commit()
        facts_lines, event_lines, steps_missing = await reset_claims(session, apply)
        grievance = await seed_grievance_steps(session) if apply and steps_missing else None
        if not apply:
            await session.rollback()
    await engine.dispose()

    print("APPLIED" if apply else "DRY RUN: nothing changed. Run with --apply to change it.")
    print(f"SAMPLE-0001 PED waiting period: {star}")
    print(f"SAMPLE-0002 PED waiting period: {renewed}")
    print("Claim facts:")
    for line in facts_lines:
        print(f"  {line}")
    print("Claim events (never changed by this script):")
    for line in event_lines:
        print(f"  {line}")
    if grievance:
        print("Grievance steps appended: " + "; ".join(grievance))


if __name__ == "__main__":
    asyncio.run(main("--apply" in sys.argv[1:]))
