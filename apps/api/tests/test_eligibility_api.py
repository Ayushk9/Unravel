"""Claim facts, eligibility and alerts through the API, against a real Postgres (temporary schema).

The policy comes from tests/fake_workers.build_policy_result: sum insured
Rs 5,00,000, a Rs 5,000/day room-rent cap, two procedure caps, a 48-month PED
waiting period (set to 48 below), one exclusion. The tests set its start date directly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.claims.deadlines import india_date
from tests.db import ApiTester, Database

CHECK_KEYS = {"id", "title", "status", "explanation", "governing_clause", "missing_fact", "resolving_document", "confidence", "values", "missing_facts"}
FACTS_NONE = {
    "diagnosis": None,
    "condition_is_pre_existing": None,
    "first_diagnosed_on": None,
    "matched_waiting_periods": None,
    "matched_exclusions": None,
    "planned_room_rent_per_day": None,
    "denial_ground": None,
}


@pytest.fixture(scope="module")
def world(database: Database) -> SimpleNamespace:
    household_id = database.create_household()
    api = ApiTester(database, household_id)
    policy_id = str(database.create_policy(household_id))
    database.execute("UPDATE policy SET start_date = '2024-03-14', end_date = '2027-03-13' WHERE id = :p", p=policy_id)
    database.execute("UPDATE coverage_profile SET intimation_deadline_hours_value = 24 WHERE policy_id = :p", p=policy_id)
    # The fake extraction says 36 months; the panel scenario needs 48.
    database.execute(
        "UPDATE waiting_period SET months_value = 48 WHERE kind = 'pre_existing' AND coverage_profile_id = "
        "(SELECT id FROM coverage_profile WHERE policy_id = :p)",
        p=policy_id,
    )
    # And it has no initial waiting period; without one that critical check is unknown. Add a 1-month one.
    database.execute(
        "INSERT INTO waiting_period (id, coverage_profile_id, position, kind, months_value, months_confidence, "
        "months_original_value, months_user_confirmed) SELECT gen_random_uuid(), id, 1, 'initial', 1, 'high', 1, false "
        "FROM coverage_profile WHERE policy_id = :p",
        p=policy_id,
    )
    members = [str(database.create_member(household_id, name)) for name in ("Ananya Rao", "Vikram Rao")]
    return SimpleNamespace(api=api, db=database, household_id=household_id, policy_id=policy_id, member_id=members[0])


def _claim(world: SimpleNamespace, admitted_on: str = "2026-04-02", claimed_amount: int | None = 18_500_000) -> str:
    response = world.api.post("/claims", json={
        "policy_id": world.policy_id, "member_id": world.member_id, "claim_type": "reimbursement", "admission_type": "planned",
        "hospital_name": "Sahyadri Hospital", "admitted_on": admitted_on, "discharged_on": None, "claimed_amount": claimed_amount,
    })
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _facts(world: SimpleNamespace, claim_id: str, **facts):
    return world.api.request("PUT", f"/claims/{claim_id}/facts", json=FACTS_NONE | facts)


def _assess(world: SimpleNamespace, claim_id: str) -> dict:
    response = world.api.post(f"/claims/{claim_id}/eligibility")
    assert response.status_code == 200, response.text
    return response.json()


def test_a_new_claim_has_unanswered_facts_and_is_insufficient_information(world: SimpleNamespace) -> None:
    claim_id = _claim(world)

    claim = world.api.get(f"/claims/{claim_id}").json()
    assessment = _assess(world, claim_id)

    assert claim["facts"] == FACTS_NONE
    assert set(assessment) == {"claim_id", "band", "checks", "ombudsman_precedent", "ombudsman_precedent_note", "generated_at"}
    assert assessment["band"] == "insufficient_information"
    assert assessment["checks"][0]["status"] == "unknown", "missing facts come first"
    assert assessment["ombudsman_precedent"] == [] and "not yet loaded" in assessment["ombudsman_precedent_note"]
    for check in assessment["checks"]:
        assert set(check) == CHECK_KEYS
        assert check["confidence"] in {"high", "medium", "low"}
        if check["status"] == "unknown":
            assert check["missing_facts"] and check["missing_fact"] == check["missing_facts"][0]["fact"]
            assert all(set(m) == {"fact", "where_to_get", "resolving_document"} for m in check["missing_facts"])


def test_panel_scenario_through_the_api(world: SimpleNamespace) -> None:
    claim_id = _claim(world)

    saved = _facts(world, claim_id, diagnosis="Type 2 diabetes complications", condition_is_pre_existing=True,
                   first_diagnosed_on="2023-11-05", matched_waiting_periods=[], matched_exclusions=[], planned_room_rent_per_day=450_000)
    assessment = _assess(world, claim_id)

    assert saved.status_code == 200 and saved.json()["facts"]["first_diagnosed_on"] == "2023-11-05"
    assert assessment["band"] == "likely_ineligible"
    ped = assessment["checks"][0]
    assert ped["id"] == "ped_waiting_period" and ped["status"] == "failed" and ped["confidence"] == "high"
    assert ped["values"]["waiting_period_ends"] == "2028-03-14"
    assert (ped["values"]["elapsed_months"], ped["values"]["elapsed_days"], ped["values"]["remaining_months"], ped["values"]["remaining_days"]) == (24, 19, 23, 12)
    assert "24 months and 19 days into the waiting period, with 23 months and 12 days still to run" in ped["explanation"]
    assert ped["governing_clause"]["page"] == 18, "opens the clause the 48 months was read from"


def test_each_band_through_the_api(world: SimpleNamespace) -> None:
    # Admitted today, so the claim (created now) is intimated in time and that check is satisfied.
    today = india_date(datetime.now(timezone.utc)).isoformat()
    answered = dict(condition_is_pre_existing=False, first_diagnosed_on=today, matched_waiting_periods=[], matched_exclusions=[])
    cases = {
        "likely_eligible": dict(answered, planned_room_rent_per_day=450_000),
        "at_risk": dict(answered, planned_room_rent_per_day=800_000),
        "likely_ineligible": dict(answered, matched_exclusions=[0]),
        "insufficient_information": dict(answered, condition_is_pre_existing=None),
    }
    for band, facts in cases.items():
        claim_id = _claim(world, admitted_on=today)
        assert _facts(world, claim_id, **facts).status_code == 200
        assert _assess(world, claim_id)["band"] == band, band


def test_room_rent_over_the_cap_explains_proportionate_deduction_in_rupees(world: SimpleNamespace) -> None:
    claim_id = _claim(world, admitted_on="2026-08-10")
    _facts(world, claim_id, condition_is_pre_existing=False, first_diagnosed_on="2026-08-09", matched_waiting_periods=[], matched_exclusions=[], planned_room_rent_per_day=800_000)

    room = next(c for c in _assess(world, claim_id)["checks"] if c["id"] == "room_rent_sub_limit")

    assert room["status"] == "at_risk"
    assert room["values"] == {"room_rent_per_day": 800_000, "room_rent_cap_per_day": 500_000, "excess_per_day": 300_000}
    assert "₹5,000 per day" in room["explanation"] and "whole bill" in room["explanation"]
    assert "%" not in room["explanation"]


@pytest.mark.parametrize(
    ("facts", "field"),
    [
        ({"matched_waiting_periods": [0]}, "matched_waiting_periods"),  # position 0 is the PED period, not disease-specific
        ({"matched_waiting_periods": [9]}, "matched_waiting_periods"),
        ({"matched_exclusions": [5]}, "matched_exclusions"),
        ({"matched_exclusions": [0, 0]}, "matched_exclusions"),
        ({"matched_exclusions": [-1]}, "matched_exclusions"),
        ({"first_diagnosed_on": "2099-01-01"}, "first_diagnosed_on"),
        ({"planned_room_rent_per_day": 4500.5}, "planned_room_rent_per_day"),
        ({"planned_room_rent_per_day": "4500"}, "planned_room_rent_per_day"),
        ({"condition_is_pre_existing": "yes"}, "condition_is_pre_existing"),
    ],
)
def test_invalid_facts_are_422_and_nothing_is_saved(world: SimpleNamespace, facts: dict, field: str) -> None:
    claim_id = _claim(world)

    response = _facts(world, claim_id, **facts)

    assert response.status_code == 422, response.text
    assert field in response.json()["error"]["field_errors"][0]["field"]
    assert world.api.get(f"/claims/{claim_id}").json()["facts"] == FACTS_NONE


def test_facts_are_a_full_replacement(world: SimpleNamespace) -> None:
    claim_id = _claim(world)
    _facts(world, claim_id, condition_is_pre_existing=True, planned_room_rent_per_day=450_000)

    _facts(world, claim_id, diagnosis="Cataract")

    assert world.api.get(f"/claims/{claim_id}").json()["facts"] == FACTS_NONE | {"diagnosis": "Cataract"}


def test_policy_now_reports_waiting_period_dates(world: SimpleNamespace) -> None:
    policy = world.api.get(f"/policies/{world.policy_id}").json()

    (ped,) = [w for w in policy["coverage_profile"]["waiting_periods"] if w["kind"] == "pre_existing"]
    assert (ped["starts_on"], ped["expires_on"]) == ("2024-03-14", "2028-03-14")


def test_another_households_claim_is_404_for_eligibility_and_facts(world: SimpleNamespace) -> None:
    claim_id = _claim(world)

    with world.api.acting_as(world.db.create_household()):
        eligibility = world.api.post(f"/claims/{claim_id}/eligibility")
        facts = _facts(world, claim_id, diagnosis="x")
        alerts = world.api.get("/alerts")

    assert eligibility.status_code == 404 and facts.status_code == 404
    assert alerts.json() == []
    assert world.api.get(f"/claims/{claim_id}").json()["facts"]["diagnosis"] is None


def test_alerts_are_computed_for_the_households_policies(world: SimpleNamespace) -> None:
    response = world.api.get("/alerts")

    assert response.status_code == 200
    alerts = response.json()
    assert isinstance(alerts, list)
    by_kind = {alert["kind"]: alert for alert in alerts}
    # Rs 5,00,000 for a 2-person household is below the (unverified) Rs 7,50,000 reference: an estimate.
    assert by_kind["low_sum_insured"]["verified"] is False and "estimate" in by_kind["low_sum_insured"]["explanation"]
    assert by_kind["low_sum_insured"]["provenance"]["page"] == 1, "points at the sum insured clause"
    assert by_kind["no_maternity_cover"]["provenance"] is None
    assert "room_rent_below_market" not in by_kind, "skipped: no household city"
    for alert in alerts:
        assert set(alert) == {"id", "policy_id", "kind", "severity", "title", "explanation", "suggested_action", "reference_source", "triggers_on", "verified", "provenance"}
        assert alert["policy_id"] == world.policy_id



def test_the_denial_ground_is_the_users_choice_of_a_check_and_may_be_left_out(world: SimpleNamespace) -> None:
    claim_id = _claim(world)

    chosen = _facts(world, claim_id, denial_ground="ped_waiting_period")
    unknown = _facts(world, claim_id, denial_ground="pre-existing disease")
    older_client = world.api.request("PUT", f"/claims/{claim_id}/facts", json={k: v for k, v in FACTS_NONE.items() if k != "denial_ground"})

    assert chosen.status_code == 200 and chosen.json()["facts"]["denial_ground"] == "ped_waiting_period"
    assert unknown.status_code == 422, "only an eligibility check id; free text is never read as a ground"
    assert older_client.status_code == 200 and older_client.json()["facts"]["denial_ground"] is None, "D-37 full replacement"
