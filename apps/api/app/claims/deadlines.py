"""Work out a claim's deadlines from its event log. Pure functions only.

Deadlines are never stored (D-17). They are derived, every time a claim is
read, from three inputs: the claim's events, the policy's coverage profile,
and the rules in app/rules/deadline_rules.yaml.

Nothing in this file reads the clock. `today` is always passed in. That is
what makes the rules testable with fixed dates ("what does this claim look
like on 29 February 2028?") and guarantees the same inputs always give the
same answer.

All arithmetic is on calendar dates in India (Asia/Kolkata). An event's
`occurred_at` is an instant; it is first converted to the date it fell on in
India, and offsets are added to that date. Working in dates rather than
hours avoids the classic off-by-one where "30 days" lands a day early or
late depending on the time of day or the server's time zone.
"""

from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from app.rules.loader import DeadlineRule, DeadlineRules, Urgency
from app.schemas.claims import Deadline, OmittedDeadline, RuleSource

INDIA = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class EventFact:
    """The parts of an event the rules need."""

    seq: int
    to_state: str
    occurred_at: datetime


@dataclass(frozen=True)
class ClaimFacts:
    claim_id: UUID
    current_state: str
    admitted_on: date | None
    events: tuple[EventFact, ...]


def india_date(instant: datetime) -> date:
    """The calendar date of an instant, as seen in India."""
    return instant.astimezone(INDIA).date()


def add_months(start: date, months: int) -> date:
    """`months` calendar months after `start`, clamped to the month's last day.

    31 Jan + 1 month is 28 Feb (29 in a leap year), not 3 March: a "one
    month" window that starts on the 31st ends on the last day of the next
    month. 29 Feb 2028 + 12 months is 28 Feb 2029.
    """
    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(start.day, last_day))


def add_offset(start: date, value: int, unit: str) -> date:
    if unit == "days":
        return start + timedelta(days=value)
    if unit == "months":
        return add_months(start, value)
    if unit == "years":
        return add_months(start, value * 12)
    raise ValueError(f"unknown offset unit {unit!r}")


def hours_to_whole_days(hours: float) -> int:
    """A window in hours, as whole days, rounded up.

    Only the DATE of admission is known, not the time, so a window in hours
    cannot be placed to the hour. Rounding up gives the latest date the
    window could end on: 24 hours -> 1 day, 36 hours -> 2 days.
    """
    return math.ceil(hours / 24)


def urgency_for(days_remaining: int, thresholds: Urgency) -> str:
    """Due today (0 days) is still open, and critical. Past due is expired."""
    if days_remaining < 0:
        return "expired"
    if days_remaining <= thresholds.critical_within_days:
        return "critical"
    if days_remaining <= thresholds.soon_within_days:
        return "soon"
    return "normal"


def _format(day: date) -> str:
    return f"{day.day} {day:%b %Y}"


def _latest_event(facts: ClaimFacts, to_state: str) -> EventFact | None:
    matching = [event for event in facts.events if event.to_state == to_state]
    return max(matching, key=lambda event: event.seq) if matching else None


def _deadline(rule: DeadlineRule, facts: ClaimFacts, due: date, basis: str, today: date, thresholds: Urgency) -> Deadline:
    days_remaining = (due - today).days
    return Deadline(
        id=f"deadline-{rule.id}-{facts.claim_id}",
        label=rule.label,
        # The deadline runs to the end of the due date in India.
        due_at=datetime.combine(due, time(23, 59, 59), tzinfo=INDIA),
        days_remaining=days_remaining,
        basis=basis,
        urgency=urgency_for(days_remaining, thresholds),
        source=RuleSource(document=rule.source.document, section=rule.source.section, url=rule.source.url),
        verified=rule.verified,
    )


def _omitted(rule: DeadlineRule, facts: ClaimFacts, reason: str) -> OmittedDeadline:
    return OmittedDeadline(id=f"deadline-{rule.id}-{facts.claim_id}", label=rule.label, reason=reason)


def compute_deadlines(
    facts: ClaimFacts,
    intimation_deadline_hours: float | None,
    rules: DeadlineRules,
    today: date,
) -> tuple[list[Deadline], list[OmittedDeadline]]:
    """Every deadline that applies to this claim today, and any that could not be computed.

    `intimation_deadline_hours` is the value from the policy's coverage
    profile, or None if the parser did not find one. A missing input never
    produces a guessed deadline: the rule is reported as omitted, with the reason.
    """
    deadlines: list[Deadline] = []
    omitted: list[OmittedDeadline] = []

    for rule in rules.rules:
        if facts.current_state not in rule.active_in:
            continue

        if rule.trigger.admission:
            _apply_intimation_rule(rule, facts, intimation_deadline_hours, today, rules.urgency, deadlines, omitted)
            continue

        start = _counting_start(rule, facts)
        if start is None:
            # The claim is in a state the rule covers but never passed
            # through the rule's trigger (or its fallback). Nothing to count from.
            continue
        counted_from, how = start
        # The loader guarantees a fixed offset when the trigger is an event.
        assert rule.offset.value is not None and rule.offset.unit is not None
        due = add_offset(counted_from, rule.offset.value, rule.offset.unit)
        basis = f"{rule.description} Counted from {_format(counted_from)}{how}."
        deadlines.append(_deadline(rule, facts, due, basis, today, rules.urgency))

    return deadlines, omitted


# How an event is named in a basis sentence ("because no reply from the insurer is recorded").
_EVENT_NAMES = {"insurer_replied": "reply from the insurer", "grievance_sent": "written grievance"}


def _counting_start(rule: DeadlineRule, facts: ClaimFacts) -> tuple[date, str] | None:
    """The date an event rule counts from, and how it was reached (for the basis sentence).

    The latest event entering the trigger state; otherwise (D-49) the fallback's
    offset past the latest event entering the fallback state; otherwise None.
    """
    event = _latest_event(facts, rule.trigger.event or "")
    if event is not None:
        return india_date(event.occurred_at), ""
    fallback = rule.trigger.otherwise
    if fallback is None:
        return None
    earlier = _latest_event(facts, fallback.event)
    if earlier is None:
        return None
    assert fallback.after.value is not None and fallback.after.unit is not None
    sent = india_date(earlier.occurred_at)
    unit = fallback.after.unit if fallback.after.value != 1 else fallback.after.unit.rstrip("s")
    missing = _EVENT_NAMES.get(rule.trigger.event or "", (rule.trigger.event or "").replace("_", " "))
    how = f", {fallback.after.value} {unit} after {_format(sent)}, because no {missing} is recorded"
    return add_offset(sent, fallback.after.value, fallback.after.unit), how


def _apply_intimation_rule(
    rule: DeadlineRule,
    facts: ClaimFacts,
    intimation_deadline_hours: float | None,
    today: date,
    thresholds: Urgency,
    deadlines: list[Deadline],
    omitted: list[OmittedDeadline],
) -> None:
    """The claim-intimation window: admission date + the policy's own number of hours.

    A claim exists in this system only once it has been intimated, so the
    window is either already met or already missed. A met window needs no
    card. A missed one is shown, as expired, because late intimation is a
    ground insurers use to reduce or refuse a claim and the user should know.
    """
    if intimation_deadline_hours is None:
        omitted.append(
            _omitted(
                rule,
                facts,
                "Your policy's claim intimation deadline was not found in the uploaded document, so this "
                "deadline cannot be worked out. Check the policy wording, or add the figure on the policy page.",
            )
        )
        return
    if facts.admitted_on is None:
        omitted.append(
            _omitted(rule, facts, "The admission date has not been entered for this claim, so this deadline cannot be worked out.")
        )
        return

    intimated = _latest_event(facts, "intimated")
    if intimated is None:
        return
    due = facts.admitted_on + timedelta(days=hours_to_whole_days(intimation_deadline_hours))
    intimated_on = india_date(intimated.occurred_at)
    if intimated_on <= due:
        return

    days_late = (intimated_on - due).days
    basis = (
        f"{rule.description} Your policy states {intimation_deadline_hours:g} hours. Counted from admission on "
        f"{_format(facts.admitted_on)}, that ended on {_format(due)}; this claim was intimated on "
        f"{_format(intimated_on)}, {days_late} day{'' if days_late == 1 else 's'} later."
    )
    deadlines.append(_deadline(rule, facts, due, basis, today, thresholds))
