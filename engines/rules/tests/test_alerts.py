from __future__ import annotations

from datetime import date

import pytest

from engines.rules import compute_alerts, load_reference
from engines.rules.tests.builders import alert_input, policy, profile, waiting

TODAY = date(2026, 10, 15)
REFERENCE = load_reference()


def kinds(outcome) -> list[str]:
    return [alert.kind for alert in outcome.alerts]


def test_waiting_period_ending_within_90_days_alerts_and_cites_its_clause() -> None:
    # Start 14 Mar 2024 + 32 months = 14 Nov 2026: 30 days from today.
    outcome = compute_alerts(alert_input(profile(waiting_periods=[waiting("disease_specific", 32, applies_to="hernia"), waiting("maternity", 9)], sum_insured=200_000_000)), REFERENCE, TODAY)

    (alert,) = [a for a in outcome.alerts if a.kind == "waiting_period_expiring"]
    assert alert.triggers_on == date(2026, 11, 14)
    assert alert.title == "Your waiting period for hernia ends in 30 days"
    assert alert.provenance is not None and alert.verified is True


@pytest.mark.parametrize(("months", "fires"), [(31, False), (32, True), (33, True), (34, False)])  # ends 14 Oct (past), 14 Nov (30 days), 14 Dec (60), 14 Jan (91)
def test_waiting_period_window_is_today_to_90_days(months: int, fires: bool) -> None:
    outcome = compute_alerts(alert_input(profile(waiting_periods=[waiting("disease_specific", months), waiting("maternity", 9)], sum_insured=200_000_000)), REFERENCE, TODAY)

    assert ("waiting_period_expiring" in kinds(outcome)) is fires


@pytest.mark.parametrize(("end", "fires"), [(date(2026, 11, 14), True), (date(2026, 10, 15), True), (date(2026, 11, 15), False), (date(2026, 10, 14), False)])
def test_renewal_due_within_30_days(end: date, fires: bool) -> None:
    outcome = compute_alerts(alert_input(profile(waiting_periods=[waiting("maternity", 9)], sum_insured=200_000_000), policy(end=end)), REFERENCE, TODAY)

    assert ("renewal_due" in kinds(outcome)) is fires


def test_maternity_alert_only_when_no_maternity_period_was_found() -> None:
    with_maternity = compute_alerts(alert_input(profile(waiting_periods=[waiting("maternity", 24)])), REFERENCE, TODAY)
    without = compute_alerts(alert_input(profile(waiting_periods=[])), REFERENCE, TODAY)

    assert "no_maternity_cover" not in kinds(with_maternity)
    (alert,) = [a for a in without.alerts if a.kind == "no_maternity_cover"]
    assert "didn't find" in alert.title and alert.provenance is None


@pytest.mark.parametrize(("sum_insured", "members", "fires"), [(50_000_000, 4, True), (100_000_000, 4, False), (50_000_000, 1, False), (60_000_000, 2, True)])
def test_low_sum_insured_is_an_unverified_estimate(sum_insured: int, members: int, fires: bool) -> None:
    outcome = compute_alerts(alert_input(profile(sum_insured=sum_insured), members=members), REFERENCE, TODAY)

    matching = [a for a in outcome.alerts if a.kind == "low_sum_insured"]
    assert bool(matching) is fires
    if fires:
        assert matching[0].verified is False
        assert "estimate" in matching[0].explanation and matching[0].reference_source


def test_inputs_that_are_missing_skip_alerts_with_a_reason_and_never_guess() -> None:
    outcome = compute_alerts(alert_input(profile(waiting_periods=[waiting("initial", 1)], sum_insured=None), policy(start=None, end=None)), REFERENCE, TODAY)

    reasons = {s.kind: s.reason for s in outcome.skipped}
    assert set(reasons) == {"waiting_period_expiring", "renewal_due", "low_sum_insured", "room_rent_below_market"}
    assert "city" in reasons["room_rent_below_market"]
    assert kinds(outcome) == ["no_maternity_cover"]


def test_no_coverage_profile_skips_the_profile_alerts() -> None:
    outcome = compute_alerts(alert_input(None), REFERENCE, TODAY)

    assert {s.kind for s in outcome.skipped} >= {"no_maternity_cover", "low_sum_insured", "room_rent_below_market"}


def test_every_reference_figure_is_unverified() -> None:
    assert REFERENCE.low_sum_insured_source.verified is False
    assert REFERENCE.typical_room_rent_source.verified is False
    assert all(type(band.minimum_paise) is int for band in REFERENCE.low_sum_insured)


def test_alert_ids_are_stable() -> None:
    data = alert_input(profile())

    assert [a.id for a in compute_alerts(data, REFERENCE, TODAY).alerts] == [a.id for a in compute_alerts(data, REFERENCE, TODAY).alerts]
