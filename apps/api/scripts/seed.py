"""Seed the development database: one household, four members, two insurers.

Run from apps/api, after `alembic upgrade head`:
    ../../.venv/bin/python scripts/seed.py

Safe to run repeatedly. Every row has a fixed id and is written with
`merge`, which inserts the row if it is missing and updates it if it is
already there, so a second run changes nothing.

The household belongs to the stub user: in ENVIRONMENT=dev the web app's
fixed token (`mock-household-token`) resolves to this household.

Names match the web app's mock fixtures (apps/web/mocks/fixtures), so the
screens show the same people and insurers on mock data and on the real API.
The insurers and their codes are fictional on purpose: attaching data to a
real insurer's name would misrepresent it.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path
from uuid import UUID

# Make `app` importable when this file is run directly as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

from app.core.auth import STUB_AUTH_USER_ID  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models import Household, Insurer, Member  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402

# Fixed ids, written in UUIDv7 form. Member ids ascend in display order,
# because GET /members orders by id.
HOUSEHOLD_ID = UUID("01920000-0000-7000-8000-000000000001")

MEMBERS = [
    Member(
        id=UUID("01920000-0000-7000-8000-000000000011"),
        household_id=HOUSEHOLD_ID,
        full_name="Ananya Rao",
        relationship="self",
        date_of_birth=date(1990, 2, 14),
    ),
    Member(
        id=UUID("01920000-0000-7000-8000-000000000012"),
        household_id=HOUSEHOLD_ID,
        full_name="Vikram Rao",
        relationship="spouse",
        date_of_birth=date(1988, 11, 2),
    ),
    Member(
        id=UUID("01920000-0000-7000-8000-000000000013"),
        household_id=HOUSEHOLD_ID,
        full_name="Ishaan Rao",
        relationship="child",
        date_of_birth=date(2019, 6, 30),
    ),
    Member(
        id=UUID("01920000-0000-7000-8000-000000000014"),
        household_id=HOUSEHOLD_ID,
        full_name="Lakshmi Rao",
        relationship="parent",
        date_of_birth=date(1962, 9, 18),
    ),
]

INSURERS = [
    Insurer(
        id=UUID("01920000-0000-7000-8000-000000000021"),
        name="Kavach Health Assurance",
        irdai_code="IRDAI-KHA-014",
    ),
    Insurer(
        id=UUID("01920000-0000-7000-8000-000000000022"),
        name="Suraksha General Insurance",
        irdai_code="IRDAI-SGI-027",
    ),
]


async def seed(session: AsyncSession) -> None:
    await session.merge(Household(id=HOUSEHOLD_ID, name="Rao household", auth_user_id=STUB_AUTH_USER_ID))
    # The household must exist before rows that reference it.
    await session.flush()
    for row in [*MEMBERS, *INSURERS]:
        await session.merge(row)
    await session.commit()


async def main() -> None:
    engine = create_engine(get_settings().database_url)
    async with create_session_factory(engine)() as session:
        await seed(session)
    await engine.dispose()
    print(f"Seeded 1 household, {len(MEMBERS)} members, {len(INSURERS)} insurers.")


if __name__ == "__main__":
    asyncio.run(main())
