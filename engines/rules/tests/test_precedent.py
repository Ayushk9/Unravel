"""Ombudsman precedent: only checked awards, matched by tag, never presented as a prediction."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from engines.rules.models import CheckResult
from engines.rules.precedent import (
    AWARDS_FILE,
    NOTE_MATCHED,
    NOTE_NO_MATCH,
    NOTE_NONE_LOADED,
    award_id,
    load_awards,
    match_precedent,
    parse_awards,
)


def entry(reference: str, ground: str = "ped_waiting_period", checked: bool = True, decided_on: str = "2025-06-01") -> dict:
    return {
        "case_reference": reference, "insurer_name": "Example Insurer", "decided_on": decided_on, "denial_ground": ground,
        "outcome": "overturned", "summary": "A summary.", "external_url": None, "checked_by_ayush": checked,
    }


def check(check_id: str, status: str) -> CheckResult:
    return CheckResult(id=check_id, title=check_id, critical=True, status=status, confidence="high", values={},
                       explanation="", governing_clause=None, missing_facts=())


def test_the_shipped_file_is_valid_and_serves_nothing() -> None:
    assert load_awards(AWARDS_FILE) == ()


def test_an_award_not_checked_by_ayush_is_never_served() -> None:
    awards = parse_awards({"version": 1, "awards": [entry("A/1", checked=False), entry("A/2", checked=True)]})
    assert [a.case_reference for a in awards] == ["A/2"]


def test_awards_are_newest_first_with_stable_ids_and_plain_labels() -> None:
    awards = parse_awards({"version": 1, "awards": [entry("OLD", decided_on="2024-01-01"), entry("NEW", decided_on="2025-01-01")]})
    assert [a.case_reference for a in awards] == ["NEW", "OLD"]
    assert awards[0].id == award_id("NEW") == parse_awards({"version": 1, "awards": [entry("NEW")]})[0].id
    assert awards[0].denial_ground_label == "Pre-existing disease waiting period"
    assert awards[0].decided_on == date(2025, 1, 1)


@pytest.mark.parametrize(
    "bad",
    [
        {"version": 1, "awards": [entry("A/1", ground="pre-existing disease")]},  # not a tag
        {"version": 1, "awards": [entry("A/1"), entry("A/1")]},  # duplicate reference
        {"version": 1, "awards": [{**entry("A/1"), "outcome": "won"}]},
        {"version": 1, "awards": [{**entry("A/1"), "similarity": 0.9}]},  # unknown key
    ],
)
def test_a_bad_file_is_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        parse_awards(bad)


def test_no_awards_loaded_keeps_the_not_loaded_note() -> None:
    result = match_precedent([check("ped_waiting_period", "failed")], ())
    assert result.awards == () and result.note == NOTE_NONE_LOADED


def test_matching_is_by_tag_of_a_failed_or_at_risk_check_only() -> None:
    awards = parse_awards({"version": 1, "awards": [
        entry("PED", "ped_waiting_period"), entry("ROOM", "room_rent_sub_limit"), entry("EXCL", "permanent_exclusions"),
    ]})
    checks = [check("ped_waiting_period", "failed"), check("room_rent_sub_limit", "at_risk"), check("permanent_exclusions", "satisfied")]

    result = match_precedent(checks, awards)

    assert {a.case_reference for a in result.awards} == {"PED", "ROOM"}
    assert result.note == NOTE_MATCHED


def test_no_matching_ground_says_so() -> None:
    awards = parse_awards({"version": 1, "awards": [entry("PED")]})
    result = match_precedent([check("ped_waiting_period", "unknown")], awards)
    assert result.awards == () and result.note == NOTE_NO_MATCH


@pytest.mark.parametrize("note", [NOTE_NONE_LOADED, NOTE_NO_MATCH, NOTE_MATCHED])
def test_every_note_says_it_is_not_a_prediction(note: str) -> None:
    assert "not a prediction of how your claim will be decided" in note
