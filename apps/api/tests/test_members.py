"""GET /members: shape of the response. The database is replaced by a fake."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from app.core.auth import CurrentHousehold, get_current_household
from app.db.models import Member as MemberRow
from app.db.session import get_session
from app.main import create_app

HOUSEHOLD_ID = UUID("01920000-0000-7000-8000-000000000001")
ROWS = [
    MemberRow(
        id=UUID("01920000-0000-7000-8000-000000000011"),
        household_id=HOUSEHOLD_ID,
        full_name="Ananya Rao",
        relationship="self",
        date_of_birth=date(1990, 2, 14),
    ),
    MemberRow(
        id=UUID("01920000-0000-7000-8000-000000000012"),
        household_id=HOUSEHOLD_ID,
        full_name="Vikram Rao",
        relationship="spouse",
        date_of_birth=None,
    ),
]


class _FakeSession:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    async def scalars(self, statement: Any) -> list[MemberRow]:
        self.statements.append(statement)
        return ROWS


def test_members_are_returned_as_a_bare_array_with_nulls_emitted() -> None:
    app = create_app()
    session = _FakeSession()

    async def fake_session() -> _FakeSession:
        return session

    async def fake_household() -> CurrentHousehold:
        return CurrentHousehold(household_id=HOUSEHOLD_ID, auth_user_id=UUID(int=1))

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_current_household] = fake_household

    response = TestClient(app).get("/api/v1/members")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "01920000-0000-7000-8000-000000000011",
            "full_name": "Ananya Rao",
            "relationship": "self",
            "date_of_birth": "1990-02-14",
        },
        {
            "id": "01920000-0000-7000-8000-000000000012",
            "full_name": "Vikram Rao",
            "relationship": "spouse",
            "date_of_birth": None,
        },
    ]


def test_members_query_is_scoped_to_the_callers_household() -> None:
    app = create_app()
    session = _FakeSession()

    async def fake_session() -> _FakeSession:
        return session

    async def fake_household() -> CurrentHousehold:
        return CurrentHousehold(household_id=HOUSEHOLD_ID, auth_user_id=UUID(int=1))

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_current_household] = fake_household

    TestClient(app).get("/api/v1/members")

    compiled = session.statements[0].compile()
    assert "member.household_id = " in str(compiled)
    assert HOUSEHOLD_ID in compiled.params.values()
