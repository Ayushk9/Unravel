"""PATCH /policies/{id} (D-39) and GET/PATCH /household (D-40), against a real Postgres (temporary schema)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.claims.deadlines import india_date
from tests.db import ApiTester, Database

DATES_NONE = {"start_date": None, "end_date": None, "first_inception_date": None}


@pytest.fixture
def world(database: Database) -> SimpleNamespace:
    # Function-scoped: every test starts from a policy with no dates and a household with no city.
    household_id = database.create_household()
    database.create_member(household_id)
    api = ApiTester(database, household_id)
    return SimpleNamespace(api=api, db=database, policy_id=str(database.create_policy(household_id)))


def _dates(world: SimpleNamespace, **body):
    return world.api.patch(f"/policies/{world.policy_id}", json=body)


def _field_errors(response) -> dict[str, str]:
    return {error["field"]: error["message"] for error in response.json()["error"]["field_errors"]}


# --- policy dates ---


def test_setting_dates_returns_the_policy_and_fills_waiting_period_dates(world: SimpleNamespace) -> None:
    response = _dates(world, start_date="2024-03-14", end_date="2025-03-13")

    assert response.status_code == 200, response.text
    policy = response.json()
    assert (policy["start_date"], policy["end_date"], policy["first_inception_date"]) == ("2024-03-14", "2025-03-13", None)
    ped = next(p for p in policy["coverage_profile"]["waiting_periods"] if p["kind"] == "pre_existing")
    assert (ped["starts_on"], ped["expires_on"]) == ("2024-03-14", "2027-03-14"), "36 months from the start date"


def test_first_inception_date_moves_the_waiting_periods(world: SimpleNamespace) -> None:
    _dates(world, start_date="2024-03-14", end_date="2025-03-13")

    policy = _dates(world, first_inception_date="2021-03-14").json()

    assert (policy["start_date"], policy["first_inception_date"]) == ("2024-03-14", "2021-03-14"), "start date kept: not sent"
    ped = next(p for p in policy["coverage_profile"]["waiting_periods"] if p["kind"] == "pre_existing")
    assert (ped["starts_on"], ped["expires_on"]) == ("2021-03-14", "2024-03-14")


def test_null_clears_a_date_and_a_missing_key_keeps_it(world: SimpleNamespace) -> None:
    _dates(world, start_date="2024-03-14", end_date="2025-03-13", first_inception_date="2022-01-01")

    policy = _dates(world, first_inception_date=None).json()

    assert (policy["start_date"], policy["end_date"], policy["first_inception_date"]) == ("2024-03-14", "2025-03-13", None)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"start_date": "2024-03-14", "end_date": "2024-03-14"}, "end_date"),
        ({"start_date": "2024-03-14", "end_date": "2023-03-14"}, "end_date"),
        ({"start_date": "2024-03-14", "first_inception_date": "2024-03-15"}, "first_inception_date"),
        ({"first_inception_date": "2999-01-01"}, "first_inception_date"),
        ({"start_date": "14/03/2024"}, "start_date"),
        ({"start_date": "2024-03-14", "renewed": True}, "renewed"),
    ],
)
def test_invalid_dates_are_422_and_change_nothing(world: SimpleNamespace, body: dict, field: str) -> None:
    response = _dates(world, **body)

    assert response.status_code == 422
    assert set(response.json()) == {"error"}
    assert any(field in name for name in _field_errors(response)), response.text
    policy = world.api.get(f"/policies/{world.policy_id}").json()
    assert {key: policy[key] for key in DATES_NONE} == DATES_NONE


def test_a_change_is_checked_against_the_dates_already_held(world: SimpleNamespace) -> None:
    _dates(world, start_date="2024-03-14", end_date="2025-03-13", first_inception_date="2022-01-01")

    moved_start = _dates(world, start_date="2021-06-01")

    assert moved_start.status_code == 422 and "first_inception_date" in _field_errors(moved_start)


def test_an_empty_body_is_422(world: SimpleNamespace) -> None:
    response = _dates(world)

    assert response.status_code == 422 and set(_field_errors(response)) == set(DATES_NONE)


def test_first_inception_today_is_accepted(world: SimpleNamespace) -> None:
    today = india_date(datetime.now(timezone.utc))

    response = _dates(world, first_inception_date=today.isoformat(), start_date=(today + timedelta(days=1)).isoformat())

    assert response.status_code == 200, response.text


def test_another_households_policy_is_404(world: SimpleNamespace) -> None:
    with world.api.acting_as(world.db.create_household()):
        response = _dates(world, start_date="2024-03-14")

    assert response.status_code == 404
    assert world.api.get(f"/policies/{world.policy_id}").json()["start_date"] is None


# --- household city tier ---


def test_a_household_starts_with_no_city_tier(world: SimpleNamespace) -> None:
    response = world.api.get("/household")

    assert response.status_code == 200
    assert set(response.json()) == {"id", "name", "city_tier"}
    assert response.json()["city_tier"] is None


@pytest.mark.parametrize("tier", ["metro", "tier_2", "other", None])
def test_setting_and_clearing_the_city_tier(world: SimpleNamespace, tier: str | None) -> None:
    response = world.api.patch("/household", json={"city_tier": tier})

    assert response.status_code == 200 and response.json()["city_tier"] == tier
    assert world.api.get("/household").json()["city_tier"] == tier


@pytest.mark.parametrize("body", [{"city_tier": "Mumbai"}, {}, {"city_tier": "metro", "name": "x"}])
def test_bad_household_updates_are_422(world: SimpleNamespace, body: dict) -> None:
    response = world.api.patch("/household", json=body)

    assert response.status_code == 422 and set(response.json()) == {"error"}
    assert world.api.get("/household").json()["city_tier"] is None


def test_the_city_tier_turns_on_the_room_rent_alert(world: SimpleNamespace) -> None:
    # The fake policy caps room rent at Rs 5,000 a day; the (unverified) metro estimate is Rs 6,000.
    before = {alert["kind"] for alert in world.api.get("/alerts").json()}

    world.api.patch("/household", json={"city_tier": "metro"})
    alerts = {alert["kind"]: alert for alert in world.api.get("/alerts").json()}
    world.api.patch("/household", json={"city_tier": "tier_2"})
    tier_2 = {alert["kind"] for alert in world.api.get("/alerts").json()}

    assert "room_rent_below_market" not in before
    room = alerts["room_rent_below_market"]
    assert room["verified"] is False and "estimate" in room["explanation"]
    assert room["provenance"] is not None and room["severity"] == "info"
    assert "room_rent_below_market" not in tier_2, "Rs 5,000 is above the Rs 3,500 tier-2 estimate"


def test_another_household_sees_its_own_city_tier(world: SimpleNamespace) -> None:
    world.api.patch("/household", json={"city_tier": "metro"})

    with world.api.acting_as(world.db.create_household()):
        other = world.api.get("/household").json()

    assert other["city_tier"] is None
