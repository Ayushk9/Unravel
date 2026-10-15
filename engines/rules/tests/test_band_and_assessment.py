"""Band precedence, ordering, and the whole assessment."""

from __future__ import annotations

import json
import re
from datetime import date

import pytest

from engines.rules import assess_eligibility, compute_alerts, load_reference
from engines.rules.band import decide_band
from engines.rules.models import CheckResult
from engines.rules.registry import ALERT_RULES, ELIGIBILITY_RULES
from engines.rules.tests.builders import alert_input, claim, eligibility_input, policy, profile, room_rent, waiting

TODAY = date(2026, 10, 15)


def check(status: str, critical: bool = True, confidence: str = "high") -> CheckResult:
    return CheckResult(id=f"{status}-{critical}-{confidence}", title="t", critical=critical, status=status, confidence=confidence,
                       values={}, explanation="e", governing_clause=None, missing_facts=())


@pytest.mark.parametrize(
    ("checks", "band"),
    [
        ([check("satisfied"), check("satisfied")], "likely_eligible"),
        ([check("satisfied"), check("unknown", critical=False)], "likely_eligible"),  # a non-critical unknown is listed only
        ([check("at_risk", critical=False), check("satisfied")], "at_risk"),
        ([check("failed", confidence="medium")], "at_risk"),  # failed, but not with high confidence
        ([check("failed", confidence="high")], "likely_ineligible"),
        ([check("failed", confidence="high"), check("unknown", critical=True)], "insufficient_information"),  # unknown critical beats failed
        ([check("at_risk"), check("unknown", critical=True)], "insufficient_information"),
        ([check("failed", confidence="high"), check("at_risk")], "likely_ineligible"),
        ([check("failed", confidence="low"), check("unknown", critical=False)], "at_risk"),
    ],
)
def test_band_precedence(checks, band) -> None:
    assert decide_band(checks) == band


def _ped_claim(**overrides):
    values = dict(admitted_on=date(2026, 4, 2), condition_is_pre_existing=True, first_diagnosed_on=date(2023, 11, 5))
    return claim(**(values | overrides))


FULL = profile(waiting_periods=[waiting("initial", 1), waiting("pre_existing", 48), waiting("disease_specific", 24, applies_to="cataract")], sub_limits=[room_rent()])


def test_panel_scenario_is_likely_ineligible_with_the_failed_check_first() -> None:
    assessment = assess_eligibility(eligibility_input(FULL, _ped_claim()), TODAY)

    assert assessment.band == "likely_ineligible"
    assert assessment.checks[0].id == "ped_waiting_period" and assessment.checks[0].status == "failed"
    assert assessment.precedent_note.startswith("Precedent corpus not yet loaded")


def test_insufficient_information_lists_the_missing_facts_first() -> None:
    assessment = assess_eligibility(eligibility_input(FULL, _ped_claim(condition_is_pre_existing=None)), TODAY)

    assert assessment.band == "insufficient_information"
    assert assessment.checks[0].status == "unknown" and assessment.checks[0].missing_facts


def test_each_band_is_reachable_from_real_inputs() -> None:
    eligible = assess_eligibility(eligibility_input(FULL, claim()), TODAY)
    at_risk = assess_eligibility(eligibility_input(FULL, claim(planned_room_rent_per_day=800_000)), TODAY)
    ineligible = assess_eligibility(eligibility_input(FULL, _ped_claim()), TODAY)
    unknown = assess_eligibility(eligibility_input(FULL, claim(matched_exclusions=None)), TODAY)

    assert [a.band for a in (eligible, at_risk, ineligible, unknown)] == ["likely_eligible", "at_risk", "likely_ineligible", "insufficient_information"]


def test_low_confidence_failure_gives_at_risk_not_ineligible() -> None:
    doubtful = profile(waiting_periods=[waiting("initial", 1), waiting("pre_existing", 48, confidence="low")], sub_limits=[room_rent()])

    assert assess_eligibility(eligibility_input(doubtful, _ped_claim()), TODAY).band == "at_risk"


def test_without_a_coverage_profile_only_that_check_is_returned() -> None:
    assessment = assess_eligibility(eligibility_input().model_copy(update={"coverage_profile": None}), TODAY)

    assert assessment.band == "insufficient_information"
    assert [c.id for c in assessment.checks] == ["coverage_profile"]


def test_same_inputs_same_answer() -> None:
    data = eligibility_input(FULL, _ped_claim())

    assert assess_eligibility(data, TODAY) == assess_eligibility(data, TODAY)


def test_no_score_probability_or_percentage_anywhere_in_the_output() -> None:
    outputs = [
        assess_eligibility(eligibility_input(FULL, c), TODAY).model_dump_json()
        for c in (claim(), claim(planned_room_rent_per_day=800_000), _ped_claim(), claim(matched_exclusions=None))
    ]
    outputs.append(compute_alerts(alert_input(FULL, policy(end=date(2026, 11, 1))), load_reference(), TODAY).model_dump_json())
    text = " ".join(outputs).lower()

    assert "%" not in text
    for word in ("score", "probability", "likelihood", "percent", "chance"):
        assert word not in text, word
    for key in ("confidence",):
        assert all(value in ("high", "medium", "low") for value in re.findall(r'"confidence":"(\w+)"', text))


def test_engine_source_has_no_clock_network_database_or_llm() -> None:
    from pathlib import Path

    source = " ".join(path.read_text() for path in Path(__file__).resolve().parents[1].glob("*.py"))
    for forbidden in ("datetime.now", "date.today", "time.time", "httpx", "requests", "sqlalchemy", "fastapi", "genai"):
        assert forbidden not in source, forbidden


def test_registry_lists_every_rule_once() -> None:
    ids = [rule.id for rule in ELIGIBILITY_RULES]
    assert len(ids) == len(set(ids)) == 8
    assert all(rule.title and rule.outcomes for rule in ELIGIBILITY_RULES)
    assert [rule.kind for rule in ALERT_RULES] == ["waiting_period_expiring", "renewal_due", "no_maternity_cover", "low_sum_insured", "room_rent_below_market"]
    assert json.dumps([rule.critical for rule in ELIGIBILITY_RULES]) == "[true, true, true, true, true, false, false, false]"
