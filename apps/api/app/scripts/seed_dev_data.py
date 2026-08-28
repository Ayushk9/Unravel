"""Seed the fixed development household and reference data.

Run after ``alembic upgrade head`` with ``ENVIRONMENT=dev``:
``python -m app.scripts.seed_dev_data``.
"""

from __future__ import annotations

import asyncio
from datetime import date

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import Household, Insurer, Member
from app.db.session import build_async_session_factory


MEMBERS = (
    ("Aarav Mehta", "self", date(1990, 6, 14)),
    ("Diya Mehta", "spouse", date(1992, 11, 3)),
    ("Ishaan Mehta", "child", date(2018, 2, 20)),
    ("Nirmala Mehta", "parent", date(1963, 9, 8)),
)
INSURERS = (
    ("Star Health and Allied Insurance Co. Ltd.", "SHAI"),
    ("HDFC ERGO General Insurance Company Limited", "HEGI"),
)


async def seed() -> None:
    """Idempotently create data for the fixed ``mock-household-token`` identity."""
    settings = get_settings()
    if settings.environment.casefold() != "dev":
        raise RuntimeError("Refusing to seed development data unless ENVIRONMENT=dev.")

    session_factory = build_async_session_factory()
    async with session_factory() as session:
        household = await session.get(Household, settings.dev_stub_household_id)
        if household is None:
            session.add(Household(id=settings.dev_stub_household_id))

        for full_name, relationship, date_of_birth in MEMBERS:
            existing_member = await session.scalar(
                select(Member).where(Member.household_id == settings.dev_stub_household_id, Member.full_name == full_name)
            )
            if existing_member is None:
                session.add(Member(household_id=settings.dev_stub_household_id, full_name=full_name, relationship=relationship, date_of_birth=date_of_birth))

        for name, irdai_code in INSURERS:
            if await session.scalar(select(Insurer).where(Insurer.irdai_code == irdai_code)) is None:
                session.add(Insurer(name=name, irdai_code=irdai_code))
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())
