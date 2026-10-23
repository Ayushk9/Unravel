"""Deadline rules with fixed dates. `today` is always passed in; nothing reads the clock."""

from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID

import pytest

from app.claims.deadlines import (
    INDIA,
    ClaimFacts,
    EventFact,
    add_months,
    add_offset,
    compute_deadlines,
    hours_to_whole_days,
    india_date,
    urgency_for,
)
from app.rules.loader import DeadlineRules, load_deadline_rules

CLAIM_ID = UUID("01920000-0000-7000-8000-0000000000c1")
RULES = load_deadline_rules()


def ist(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=INDIA)


def facts(*events: tuple[str, datetime], admitted_on: date | None = None) -> ClaimFacts:
    event_facts = tuple(EventFact(seq=i, to_state=state, occurred_at=when) for i, (state, when) in enumerate(events, start=1))
    return ClaimFacts(claim_id=CLAIM_ID, current_state=event_facts[-1].to_state, admitted_on=admitted_on, events=event_facts)


def only(deadlines: list, rule_id: str):
    matching = [d for d in deadlines if d.id == f"deadline-{rule_id}-{CLAIM_ID}"]
    assert len(matching) == 1, [d.id for d in deadlines]
    return matching[0]


# --- calendar arithmetic ---


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2026, 1, 15), 1, date(2026, 2, 15)),
        (date(2026, 1, 31), 1, date(2026, 2, 28)),  # month end, not a leap year
        (date(2028, 1, 31), 1, date(2028, 2, 29)),  # month end, leap year
        (date(2026, 3, 31), 1, date(2026, 4, 30)),
        (date(2026, 12, 15), 1, date(2027, 1, 15)),  # across a year end
        (date(2026, 11, 30), 3, date(2027, 2, 28)),
        (date(2028, 2, 29), 12, date(2029, 2, 28)),  # 29 Feb + a year
        (date(2027, 2, 28), 12, date(2028, 2, 28)),  # into a leap year: stays on the 28th
    ],
)
def test_adding_months_clamps_to_the_last_day_of_the_month(start: date, months: int, expected: date) -> None:
    assert add_months(start, months) == expected


def test_one_year_from_29_february_is_28_february() -> None:
    assert add_offset(date(2028, 2, 29), 1, "years") == date(2029, 2, 28)
    assert add_offset(date(2024, 2, 29), 4, "years") == date(2028, 2, 29)


def test_days_cross_month_ends_and_leap_days_exactly() -> None:
    assert add_offset(date(2026, 1, 31), 30, "days") == date(2026, 3, 2)
    assert add_offset(date(2028, 1, 31), 30, "days") == date(2028, 3, 1)  # February has 29 days in 2028
    assert add_offset(date(2026, 12, 15), 30, "days") == date(2027, 1, 14)


@pytest.mark.parametrize(("hours", "days"), [(24, 1), (48, 2), (36, 2), (1, 1), (720, 30), (24.5, 2)])
def test_hours_become_whole_days_rounded_up(hours: float, days: int) -> None:
    assert hours_to_whole_days(hours) == days


def test_an_instant_is_dated_by_the_india_calendar_not_utc() -> None:
    late_evening_utc = datetime(2026, 3, 31, 20, 0, tzinfo=timezone.utc)  # 01:30 on 1 April in India

    assert india_date(late_evening_utc) == date(2026, 4, 1)
    assert india_date(ist(2026, 3, 31, 23, 59)) == date(2026, 3, 31)


@pytest.mark.parametrize(
    ("days_remaining", "urgency"),
    [(-1, "expired"), (0, "critical"), (3, "critical"), (4, "soon"), (14, "soon"), (15, "normal"), (365, "normal")],
)
def test_urgency_bands(days_remaining: int, urgency: str) -> None:
    assert urgency_for(days_remaining, RULES.urgency) == urgency


# --- the Ombudsman: Rule 14(3) of the Insurance Ombudsman Rules, 2017 (D-49) ---
# A complaint lies only after a written grievance to the insurer; it may be made from one
# month after the grievance with no reply, and within one year of the reply (or, with no
# reply, of the month after the grievance).

DENIED = (("intimated", ist(2026, 7, 6)), ("documents_submitted", ist(2026, 7, 12)), ("under_review", ist(2026, 7, 14)), ("denied", ist(2026, 8, 10, 11)))
SENT = (*DENIED, ("grievance_sent", ist(2026, 8, 20)))
REPLIED = (*SENT, ("insurer_replied", ist(2026, 9, 10)))
URL = "https://www.cioins.co.in/notification/Insurance%20Ombudsman%20Rules,%202017(%20as%20amended%20till%2009.11.2023).pdf"


def ids(deadlines: list) -> set[str]:
    return {d.id.removesuffix(f"-{CLAIM_ID}").removeprefix("deadline-") for d in deadlines}


def test_a_denial_alone_starts_no_ombudsman_clock() -> None:
    deadlines, _ = compute_deadlines(facts(*DENIED, admitted_on=date(2026, 7, 5)), 24.0, RULES, today=date(2026, 8, 20))
    assert ids(deadlines) == set(), "a complaint lies only after a written grievance to the insurer"


def test_with_a_grievance_and_no_reply_the_ombudsman_opens_after_a_month_and_the_window_runs_a_year_from_then() -> None:
    deadlines, omitted = compute_deadlines(facts(*SENT, admitted_on=date(2026, 7, 5)), 24.0, RULES, today=date(2026, 8, 25))

    opens = only(deadlines, "ombudsman_opens")
    assert opens.label == "You may approach the Ombudsman from"
    assert opens.due_at == datetime(2026, 9, 20, 23, 59, 59, tzinfo=INDIA)
    assert opens.verified is True and opens.source.section == "Rule 14(3)(a)" and opens.source.url == URL
    filing = only(deadlines, "ombudsman_filing")
    assert filing.due_at.date() == date(2027, 9, 20), "one year from one month after 20 Aug 2026"
    assert filing.verified is True and filing.source.url == URL
    assert "Counted from 20 Sep 2026, 1 month after 20 Aug 2026, because no reply from the insurer is recorded." in filing.basis
    assert omitted == []


def test_after_the_insurers_reply_the_window_runs_a_year_from_the_reply() -> None:
    deadlines, _ = compute_deadlines(facts(*REPLIED), 24.0, RULES, today=date(2026, 9, 20))

    assert "ombudsman_opens" not in ids(deadlines), "only while no reply is recorded"
    filing = only(deadlines, "ombudsman_filing")
    assert filing.due_at.date() == date(2027, 9, 10) and filing.days_remaining == 355 and filing.urgency == "normal"
    assert "Counted from 10 Sep 2026." in filing.basis


def test_a_deadline_falling_exactly_on_today_is_open_and_critical() -> None:
    deadlines, _ = compute_deadlines(facts(*REPLIED), 24.0, RULES, today=date(2027, 9, 10))
    assert (only(deadlines, "ombudsman_filing").days_remaining, only(deadlines, "ombudsman_filing").urgency) == (0, "critical")


def test_the_day_after_the_due_date_it_is_expired_but_still_listed() -> None:
    deadlines, _ = compute_deadlines(facts(*REPLIED), 24.0, RULES, today=date(2027, 9, 11))
    assert (only(deadlines, "ombudsman_filing").days_remaining, only(deadlines, "ombudsman_filing").urgency) == (-1, "expired")


def test_a_reply_on_29_february_is_due_on_28_february_next_year() -> None:
    events = (*DENIED, ("grievance_sent", ist(2028, 2, 1)), ("insurer_replied", ist(2028, 2, 29)))
    deadlines, _ = compute_deadlines(facts(*events), 24.0, RULES, today=date(2028, 3, 1))
    assert only(deadlines, "ombudsman_filing").due_at.date() == date(2029, 2, 28)


def test_a_grievance_sent_on_31_january_opens_on_the_last_day_of_february() -> None:
    events = (*DENIED, ("grievance_sent", ist(2027, 1, 31)))
    deadlines, _ = compute_deadlines(facts(*events), 24.0, RULES, today=date(2027, 2, 1))
    assert only(deadlines, "ombudsman_opens").due_at.date() == date(2027, 2, 28)
    assert only(deadlines, "ombudsman_filing").due_at.date() == date(2028, 2, 28)


def test_a_reply_logged_late_at_night_utc_counts_from_the_india_date() -> None:
    reply = datetime(2026, 9, 9, 20, 0, tzinfo=timezone.utc)  # already 10 Sep in India
    events = (*SENT, ("insurer_replied", reply))
    deadlines, _ = compute_deadlines(facts(*events), 24.0, RULES, today=date(2026, 9, 20))
    assert only(deadlines, "ombudsman_filing").due_at.date() == date(2027, 9, 10)


def test_same_inputs_give_the_same_answer_whatever_the_real_date() -> None:
    first = compute_deadlines(facts(*SENT), 24.0, RULES, today=date(2026, 9, 1))
    second = compute_deadlines(facts(*SENT), 24.0, RULES, today=date(2026, 9, 1))
    assert first == second


def test_once_the_complaint_is_filed_no_ombudsman_clock_is_shown() -> None:
    deadlines, _ = compute_deadlines(facts(*REPLIED, ("escalated", ist(2026, 10, 1))), 24.0, RULES, today=date(2026, 10, 2))
    assert ids(deadlines) == set()


# --- the insurer's decision window (30 days from documents submitted) ---


def test_insurer_decision_window_crosses_a_month_end() -> None:
    events = (("intimated", ist(2026, 1, 20)), ("documents_submitted", ist(2026, 1, 31)))

    deadlines, _ = compute_deadlines(facts(*events), 24.0, RULES, today=date(2026, 2, 1))

    deadline = only(deadlines, "insurer_decision")
    assert deadline.due_at.date() == date(2026, 3, 2)
    assert deadline.days_remaining == 29


def test_insurer_decision_window_restarts_when_documents_are_resubmitted() -> None:
    events = (
        ("intimated", ist(2026, 1, 1)),
        ("documents_submitted", ist(2026, 1, 5)),
        ("queried", ist(2026, 1, 10)),
        ("documents_submitted", ist(2026, 1, 20)),
    )

    deadlines, _ = compute_deadlines(facts(*events), 24.0, RULES, today=date(2026, 1, 21))

    assert only(deadlines, "insurer_decision").due_at.date() == date(2026, 2, 19)


def test_a_deadline_disappears_when_the_claim_leaves_the_states_it_applies_to() -> None:
    events = (("intimated", ist(2026, 1, 1)), ("documents_submitted", ist(2026, 1, 5)), ("queried", ist(2026, 1, 10)))

    deadlines, _ = compute_deadlines(facts(*events), 24.0, RULES, today=date(2026, 1, 11))

    assert deadlines == []


@pytest.mark.parametrize("state", ["approved", "resolved"])
def test_closed_and_approved_claims_have_no_event_deadlines(state: str) -> None:
    events = (("intimated", ist(2026, 1, 1)), ("documents_submitted", ist(2026, 1, 2)), ("under_review", ist(2026, 1, 3)), ("approved", ist(2026, 1, 4)))
    if state == "resolved":
        events = (*events, ("resolved", ist(2026, 1, 5)))

    deadlines, _ = compute_deadlines(facts(*events), 24.0, RULES, today=date(2026, 6, 1))

    assert deadlines == []


# --- claim intimation (the policy's own number of hours) ---


def test_intimation_within_the_policy_window_shows_no_card() -> None:
    claim = facts(("intimated", ist(2026, 3, 2, 9)), admitted_on=date(2026, 3, 1))

    deadlines, omitted = compute_deadlines(claim, 24.0, RULES, today=date(2026, 3, 10))

    assert deadlines == [] and omitted == []


def test_intimation_on_the_last_permitted_day_is_in_time() -> None:
    claim = facts(("intimated", ist(2026, 3, 3, 23, 30)), admitted_on=date(2026, 3, 1))

    deadlines, _ = compute_deadlines(claim, 48.0, RULES, today=date(2026, 3, 10))

    assert deadlines == []


def test_late_intimation_is_shown_as_expired_with_the_arithmetic_spelled_out() -> None:
    claim = facts(("intimated", ist(2026, 3, 5)), admitted_on=date(2026, 3, 1))

    deadlines, _ = compute_deadlines(claim, 24.0, RULES, today=date(2026, 3, 10))

    deadline = only(deadlines, "claim_intimation")
    assert deadline.urgency == "expired" and deadline.days_remaining == -8
    assert deadline.due_at.date() == date(2026, 3, 2)
    assert "24 hours" in deadline.basis and "1 Mar 2026" in deadline.basis and "3 days later" in deadline.basis
    assert deadline.verified is False


def test_missing_intimation_hours_omits_the_deadline_with_a_reason_and_never_guesses() -> None:
    claim = facts(("intimated", ist(2026, 3, 20)), admitted_on=date(2026, 3, 1))

    deadlines, omitted = compute_deadlines(claim, None, RULES, today=date(2026, 3, 21))

    assert deadlines == []
    assert [o.id for o in omitted] == [f"deadline-claim_intimation-{CLAIM_ID}"]
    assert omitted[0].label == "Claim intimation window"
    assert "not found" in omitted[0].reason


def test_missing_admission_date_omits_the_deadline_with_a_reason() -> None:
    claim = facts(("intimated", ist(2026, 3, 20)), admitted_on=None)

    deadlines, omitted = compute_deadlines(claim, 24.0, RULES, today=date(2026, 3, 21))

    assert deadlines == []
    assert "admission date" in omitted[0].reason


# --- the rule file itself ---


def test_only_the_rules_ayush_checked_are_verified_and_every_rule_names_a_source() -> None:
    assert [rule.id for rule in RULES.rules] == ["claim_intimation", "insurer_decision", "ombudsman_opens", "ombudsman_filing"]
    verified = {rule.id for rule in RULES.rules if rule.verified}
    assert verified == {"ombudsman_opens", "ombudsman_filing"}, "Rule 14(3), checked by Ayush on 2026-10-23"
    for rule in RULES.rules:
        assert rule.source.document
        assert rule.description.endswith(".")


def test_an_unverified_rule_is_reported_as_unverified() -> None:
    """Flipping the flag in the file is all it takes; no code change."""
    data = RULES.model_dump()
    for rule in data["rules"]:
        if rule["id"] == "ombudsman_filing":
            rule["verified"] = False
    rules = DeadlineRules.model_validate(data)

    deadlines, _ = compute_deadlines(facts(*SENT), 24.0, rules, today=date(2026, 8, 25))

    assert only(deadlines, "ombudsman_filing").verified is False


def test_a_fallback_trigger_needs_an_event_trigger_and_a_fixed_length() -> None:
    from pydantic import ValidationError

    from app.rules.loader import Trigger

    with pytest.raises(ValidationError):
        Trigger.model_validate({"admission": True, "otherwise": {"event": "grievance_sent", "after": {"value": 1, "unit": "months"}}})
    with pytest.raises(ValidationError):
        Trigger.model_validate({"event": "insurer_replied", "otherwise": {"event": "grievance_sent", "after": {"policy_field": "intimation_deadline_hours"}}})
