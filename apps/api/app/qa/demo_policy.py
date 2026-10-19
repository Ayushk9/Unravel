"""Which policy the Q&A scripts (latency, profiling, cache warm-up) use: a real one.

The policy seeded by scripts/seed_demo_claims.py is a SYNTHETIC test fixture
(policy number SYNTHETIC_FIXTURE_NUMBER): hand-written, 15 clauses. It stays
out of the demo and out of headline metrics. These scripts use the dev
household's newest policy that is NOT that fixture, which is the uploaded
Star policy, unless a policy id is given.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Policy

DEV_HOUSEHOLD = UUID("01920000-0000-7000-8000-000000000001")  # scripts/seed.py
SYNTHETIC_FIXTURE_NUMBER = "KHA/FAM/2024/DEMO-0001"  # scripts/seed_demo_claims.py


async def find_real_policy(session: AsyncSession, policy_id: UUID | None = None) -> Policy:
    if policy_id is not None:
        policy = await session.get(Policy, policy_id)
    else:
        policy = await session.scalar(
            select(Policy)
            .where(Policy.household_id == DEV_HOUSEHOLD,
                   or_(Policy.policy_number.is_(None), Policy.policy_number != SYNTHETIC_FIXTURE_NUMBER))
            .order_by(Policy.id.desc())
            .limit(1)
        )
    if policy is None:
        raise SystemExit("No real policy found in the dev household. Upload one, or pass a policy id.")
    if policy.policy_number == SYNTHETIC_FIXTURE_NUMBER:
        raise SystemExit("That is the synthetic test fixture; it is kept out of the demo and metrics. Choose a real policy.")
    return policy
