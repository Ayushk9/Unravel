"""Table-driven tests: every rule, every outcome."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from engines.rules.eligibility import (
    claim_intimation,
    coverage_profile_present,
    disease_specific_waiting_period,
    initial_waiting_period,
    permanent_exclusions,
    ped_waiting_period,
    room_rent_sub_limit,
    sum_insured_adequacy,
)
from engines.rules.tests.builders import claim, eligibility_input, extracted, policy, profile, room_rent, waiting

START = date(2024, 3, 14)


# --- initial waiting period (30 days written as 1 month) ---


@pytest.mark.parametrize(
    ("admitted_on", "status"),
    [
        (date(2024, 4, 13), "failed"),  # the day before the end date
        (date(2024, 4, 14), "satisfied"),  # exactly on the end date: served
        (date(2024, 4, 15), "satisfied"),
        (date(2024, 3, 1), "failed"),  # before the policy even started
    ],
)
def test_initial_waiting_period(admitted_on: date, status: str) -> None:
    result = initial_waiting_period(eligibility_input(profile(waiting_periods=[waiting("initial", 1)]), claim(admitted_on=admitted_on)))

    assert result.status == status
    assert result.values["waiting_period_ends"] == date(2024, 4, 14)
    assert "on or after the end date counts as outside" in result.explanation
    assert "policy start date we hold" in result.explanation, "the first-inception assumption is stated"
    assert result.governing_clause is not None and result.governing_clause.page == 3


def test_initial_waiting_period_from_31_january_ends_on_the_last_day_of_february() -> None:
    data = eligibility_input(profile(waiting_periods=[waiting("initial", 1)]), claim(admitted_on=date(2026, 2, 28)), policy(start=date(2026, 1, 31)))

    result = initial_waiting_period(data)

    assert result.values["waiting_period_ends"] == date(2026, 2, 28)
    assert result.status == "satisfied"


@pytest.mark.parametrize(
    ("profile_value", "policy_value", "claim_value", "missing"),
    [
        (profile(waiting_periods=[]), policy(), claim(), ["Your policy's initial waiting period, in whole months"]),
        (profile(waiting_periods=[waiting("initial", 1.5)]), policy(), claim(), ["Your policy's initial waiting period, in whole months"]),
        (profile(waiting_periods=[waiting("initial", 1)]), policy(start=None), claim(), ["Policy start date"]),
        (profile(waiting_periods=[waiting("initial", 1)]), policy(), claim(admitted_on=None), ["Date of admission"]),
    ],
)
def test_initial_waiting_period_unknown_names_what_is_missing(profile_value, policy_value, claim_value, missing) -> None:
    result = initial_waiting_period(eligibility_input(profile_value, claim_value, policy_value))

    assert result.status == "unknown"
    assert [m.fact for m in result.missing_facts] == missing


# --- pre-existing disease waiting period ---

PED = [waiting("pre_existing", 48)]


def test_panel_scenario_ped_failed_with_the_arithmetic_spelled_out() -> None:
    data = eligibility_input(profile(waiting_periods=PED), claim(admitted_on=date(2026, 4, 2), condition_is_pre_existing=True, first_diagnosed_on=date(2023, 11, 5)))

    result = ped_waiting_period(data)

    assert result.status == "failed" and result.confidence == "high"
    assert result.values["waiting_period_ends"] == date(2028, 3, 14)
    assert (result.values["elapsed_months"], result.values["elapsed_days"]) == (24, 19)
    assert (result.values["remaining_months"], result.values["remaining_days"]) == (23, 12)
    assert (
        "Your policy started 14 Mar 2024; the 48-month waiting period ends on 14 Mar 2028. Your admission on 2 Apr 2026 "
        "is before that date: 24 months and 19 days into the waiting period, with 23 months and 12 days still to run."
    ) in result.explanation


@pytest.mark.parametrize(
    ("is_ped", "first_dx", "admitted", "status"),
    [
        (True, date(2023, 1, 1), date(2028, 3, 13), "failed"),  # one day before the end
        (True, date(2023, 1, 1), date(2028, 3, 14), "satisfied"),  # exactly on the end date
        (False, date(2026, 8, 9), date(2026, 8, 10), "satisfied"),  # not pre-existing
        (False, date(2023, 1, 1), date(2026, 8, 10), "at_risk"),  # says no, but diagnosed before the start
    ],
)
def test_ped_outcomes(is_ped: bool, first_dx: date, admitted: date, status: str) -> None:
    data = eligibility_input(profile(waiting_periods=PED), claim(admitted_on=admitted, condition_is_pre_existing=is_ped, first_diagnosed_on=first_dx))

    assert ped_waiting_period(data).status == status


def test_ped_from_a_29_february_start() -> None:
    data = eligibility_input(
        profile(waiting_periods=[waiting("pre_existing", 12)]),
        claim(admitted_on=date(2025, 2, 28), condition_is_pre_existing=True, first_diagnosed_on=date(2023, 1, 1)),
        policy(start=date(2024, 2, 29)),
    )

    result = ped_waiting_period(data)

    assert result.values["waiting_period_ends"] == date(2025, 2, 28)
    assert result.status == "satisfied", "admitted on the clamped end date: served"


@pytest.mark.parametrize(
    ("is_ped", "first_dx", "missing"),
    [
        (None, date(2023, 1, 1), ["Whether this illness started before the policy did (a pre-existing condition)"]),
        (True, None, ["Date this illness was first diagnosed"]),
        (None, None, ["Whether this illness started before the policy did (a pre-existing condition)", "Date this illness was first diagnosed"]),
    ],
)
def test_ped_is_never_assumed(is_ped, first_dx, missing) -> None:
    result = ped_waiting_period(eligibility_input(profile(waiting_periods=PED), claim(condition_is_pre_existing=is_ped, first_diagnosed_on=first_dx)))

    assert result.status == "unknown"
    assert [m.fact for m in result.missing_facts] == missing
    first_dx_fact = next((m for m in result.missing_facts if m.fact.startswith("Date this illness")), None)
    if first_dx_fact:
        assert "consultation record" in first_dx_fact.where_to_get


def test_a_low_confidence_unconfirmed_period_lowers_the_check_and_confirming_restores_it() -> None:
    def run(confidence: str, confirmed: bool):
        data = eligibility_input(
            profile(waiting_periods=[waiting("pre_existing", 48, confidence=confidence, user_confirmed=confirmed)]),
            claim(admitted_on=date(2026, 4, 2), condition_is_pre_existing=True, first_diagnosed_on=date(2023, 1, 1)),
        )
        return ped_waiting_period(data).confidence

    assert run("low", False) == "low"
    assert run("medium", False) == "medium"
    assert run("low", True) == "high", "a user-confirmed input counts as high"


# --- disease-specific waiting periods and exclusions: only the user's selection decides ---

CATARACT = waiting("disease_specific", 24, applies_to="cataract")
HERNIA = waiting("disease_specific", 24, applies_to="hernia", confidence="medium")


@pytest.mark.parametrize(
    ("matched", "admitted", "status"),
    [
        (None, date(2026, 8, 10), "unknown"),
        ((), date(2026, 8, 10), "satisfied"),
        ((1,), date(2026, 3, 13), "failed"),  # cataract ends 14 Mar 2026
        ((1,), date(2026, 3, 14), "satisfied"),
        ((0,), date(2026, 8, 10), "unknown"),  # position 0 is the PED period, not disease-specific
        ((7,), date(2026, 8, 10), "unknown"),  # no such position
    ],
)
def test_disease_specific_waiting_period(matched, admitted, status) -> None:
    data = eligibility_input(profile(waiting_periods=[*PED, CATARACT]), claim(matched_waiting_periods=matched, admitted_on=admitted))

    assert disease_specific_waiting_period(data).status == status


def test_disease_specific_cites_the_unserved_period_and_takes_the_lowest_confidence() -> None:
    data = eligibility_input(profile(waiting_periods=[CATARACT, HERNIA]), claim(matched_waiting_periods=(0, 1), admitted_on=date(2026, 1, 1)))

    result = disease_specific_waiting_period(data)

    assert result.status == "failed" and result.confidence == "medium"
    assert "For cataract" in result.explanation and "For hernia" in result.explanation


@pytest.mark.parametrize(("matched", "status"), [(None, "unknown"), ((), "satisfied"), ((1,), "failed"), ((5,), "unknown")])
def test_permanent_exclusions(matched, status) -> None:
    exclusions = [extracted("Cosmetic surgery"), extracted("Dental treatment", page=21)]
    result = permanent_exclusions(eligibility_input(profile(exclusions=exclusions), claim(matched_exclusions=matched)))

    assert result.status == status
    if status == "failed":
        assert '"Dental treatment"' in result.explanation
        assert result.governing_clause.page == 21


def test_a_doubtful_exclusion_cannot_give_a_confident_failure() -> None:
    result = permanent_exclusions(eligibility_input(profile(exclusions=[extracted("Dental treatment", "low")]), claim(matched_exclusions=(0,))))

    assert result.status == "failed" and result.confidence == "low"


# --- room rent ---


@pytest.mark.parametrize(
    ("limit", "rent", "status", "cap"),
    [
        (room_rent(500_000), 450_000, "satisfied", 500_000),
        (room_rent(500_000), 500_000, "satisfied", 500_000),  # exactly at the cap
        (room_rent(500_000), 800_000, "at_risk", 500_000),
        (room_rent(1000, basis="percent_of_sum_insured", percent=1.0), 450_000, "satisfied", 500_000),  # 1% of Rs 5,00,000
        (room_rent(1000, basis="percent_of_sum_insured", percent=1.0), 600_000, "at_risk", 500_000),
    ],
)
def test_room_rent(limit, rent, status, cap) -> None:
    result = room_rent_sub_limit(eligibility_input(profile(sub_limits=[limit]), claim(planned_room_rent_per_day=rent)))

    assert result.status == status
    assert result.values["room_rent_cap_per_day"] == cap and type(result.values["room_rent_cap_per_day"]) is int
    if status == "at_risk":
        assert "proportionate deduction" in result.explanation and "whole bill" in result.explanation


def test_room_rent_unknowns() -> None:
    assert room_rent_sub_limit(eligibility_input(profile(sub_limits=[room_rent()]), claim(planned_room_rent_per_day=None))).status == "unknown"
    assert room_rent_sub_limit(eligibility_input(profile(sub_limits=[]), claim())).status == "unknown"
    assert room_rent_sub_limit(eligibility_input(profile(sub_limits=[room_rent(basis="per_claim")]), claim())).status == "unknown"
    assert room_rent_sub_limit(eligibility_input(profile(sub_limits=[room_rent(), room_rent(300_000)]), claim())).status == "unknown"


# --- intimation and sum insured ---


@pytest.mark.parametrize(
    ("hours", "told", "status"),
    [
        (24.0, "2026-08-11T22:00:00+05:30", "satisfied"),  # last permitted day
        (24.0, "2026-08-12T09:00:00+05:30", "at_risk"),
        (48.0, "2026-08-12T09:00:00+05:30", "satisfied"),
        (None, "2026-08-10T12:00:00+05:30", "unknown"),  # deadline not extracted: never guessed
    ],
)
def test_claim_intimation(hours, told, status) -> None:
    data = eligibility_input(profile(intimation_hours=hours), claim(admitted_on=date(2026, 8, 10), intimated_at=datetime.fromisoformat(told)))

    assert claim_intimation(data).status == status


@pytest.mark.parametrize(("claimed", "status"), [(50_000_000, "satisfied"), (50_000_001, "at_risk"), (None, "unknown")])
def test_sum_insured_adequacy(claimed, status) -> None:
    assert sum_insured_adequacy(eligibility_input(profile(), claim(claimed_amount=claimed))).status == status


def test_coverage_profile_rule() -> None:
    assert coverage_profile_present(eligibility_input()).status == "satisfied"
    data = eligibility_input().model_copy(update={"coverage_profile": None})
    assert coverage_profile_present(data).status == "unknown"


# --- the waiting clock: first inception of continuous cover, when the user gave it ---


def test_first_inception_date_starts_the_clock_and_is_named_in_the_explanation() -> None:
    # Same panel claim, but cover has run without a break since 14 Mar 2022: 48 months end 14 Mar 2026, before the admission.
    data = eligibility_input(
        profile(waiting_periods=PED),
        claim(admitted_on=date(2026, 4, 2), condition_is_pre_existing=True, first_diagnosed_on=date(2021, 11, 5)),
        policy(inception=date(2022, 3, 14)),
    )

    result = ped_waiting_period(data)

    assert result.status == "satisfied"
    assert result.values["first_inception_date"] == date(2022, 3, 14) and "policy_start" not in result.values
    assert result.values["waiting_period_ends"] == date(2026, 3, 14)
    assert "Your continuous cover started 14 Mar 2022" in result.explanation
    assert "the date you gave as the start of your cover" in result.explanation
    assert "could be earlier" not in result.explanation, "the start-date caveat is only for the fallback"


def test_without_a_first_inception_date_the_policy_start_is_used_and_said_to_be_an_assumption() -> None:
    result = initial_waiting_period(eligibility_input(profile(waiting_periods=[waiting("initial", 1)]), claim(admitted_on=date(2024, 4, 1))))

    assert result.values["policy_start"] == START
    assert "Counted from the policy start date we hold" in result.explanation


def test_first_inception_date_alone_is_enough_to_decide() -> None:
    data = eligibility_input(profile(waiting_periods=[waiting("initial", 1)]), claim(admitted_on=date(2024, 4, 15)), policy(start=None, inception=date(2024, 3, 14)))

    assert initial_waiting_period(data).status == "satisfied"


def test_no_start_and_no_inception_is_unknown_and_says_either_will_do() -> None:
    data = eligibility_input(profile(waiting_periods=[waiting("initial", 1)]), claim(), policy(start=None))

    result = initial_waiting_period(data)

    assert result.status == "unknown"
    assert result.missing_facts[0].fact == "Policy start date" and "first policy's start date" in result.missing_facts[0].where_to_get


def test_diagnosed_before_inception_but_answered_not_pre_existing_is_at_risk() -> None:
    data = eligibility_input(
        profile(waiting_periods=PED),
        claim(condition_is_pre_existing=False, first_diagnosed_on=date(2022, 1, 1)),
        policy(inception=date(2022, 3, 14)),
    )

    result = ped_waiting_period(data)

    assert result.status == "at_risk" and result.values["first_inception_date"] == date(2022, 3, 14)
    # Diagnosed after inception (but before this policy's start) is not a contradiction.
    later = eligibility_input(
        profile(waiting_periods=PED),
        claim(condition_is_pre_existing=False, first_diagnosed_on=date(2023, 1, 1)),
        policy(inception=date(2022, 3, 14)),
    )
    assert ped_waiting_period(later).status == "satisfied"
