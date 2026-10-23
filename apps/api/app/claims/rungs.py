"""Which escalation rungs a grievance letter can be drafted for, and why. Pure functions only.

Inputs: the claim's current state, its event log, the deadlines already
computed for it (app/claims/deadlines.py, from deadline_rules.yaml) and the
rung descriptions in app/rules/grievance_rungs.yaml. No clock is read: the
deadlines were computed for a `today` the caller chose.

A rung is offered when the claim is in one of the rung's `when` states. The
dates in its reason come from a deadline rule, never from this file.

D-49 gates (Rule 14(3) of the Insurance Ombudsman Rules): a condition may open
only from a deadline's date (`opens_with`) and close after one (`closes_with`).
A VERIFIED gate is enforced: before it opens, or once it has closed, the rung
is not offered. An unverified rule only changes the sentence, and the rung is
still offered and marked, so the user can decide rather than be told "no" by a
rule nobody has checked.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.claims.deadlines import EventFact, india_date
from app.rules.loader import GrievanceRungs, RungCondition
from app.schemas.claims import Deadline
from app.schemas.grievances import GrievanceRungOption
from engines.rules.dates import format_date

UNVERIFIED_NOTE = "This is based on a rule that has not yet been checked against its source."


@dataclass(frozen=True)
class RungContext:
    current_state: str
    events: tuple[EventFact, ...]
    deadlines: tuple[Deadline, ...]


def _deadline(context: RungContext, rule_id: str) -> Deadline | None:
    # Deadline ids are "deadline-<rule id>-<claim id>" (deadlines._deadline).
    prefix = f"deadline-{rule_id}-"
    return next((d for d in context.deadlines if d.id.startswith(prefix)), None)


def _entered_on(context: RungContext, state: str) -> str | None:
    matching = [e for e in context.events if e.to_state == state]
    return format_date(india_date(max(matching, key=lambda e: e.seq).occurred_at)) if matching else None


def _date(deadline: Deadline | None) -> str:
    return format_date(deadline.due_at.date()) if deadline else ""


def _option(name: str, rungs: GrievanceRungs, condition: RungCondition | None, context: RungContext) -> GrievanceRungOption:
    rung = rungs.rungs[name]
    if condition is None:
        reason = rung.not_offered.get(context.current_state, rung.unavailable)
        return GrievanceRungOption(rung=name, label=rung.label, available=False, reason=reason, rule_ids=[], verified=rung.verified)

    used = {rule_id: _deadline(context, rule_id) for rule_id in condition.deadline_ids()}
    missing = [rule_id for rule_id, deadline in used.items() if deadline is None]
    if missing:
        # The rule applies in this state but has nothing to count from (its event is missing).
        # Offer the rung without a date rather than invent one.
        return GrievanceRungOption(
            rung=name, label=rung.label, available=True,
            reason=f"{rung.label} may be open to you, but the date it depends on could not be worked out from this claim's events.",
            rule_ids=list(used), verified=False,
        )

    due, opens, closes = (used.get(rule_id) if rule_id else None for rule_id in (condition.deadline, condition.opens_with, condition.closes_with))
    template, available = condition.reason, True
    if due is not None and due.days_remaining < 0 and condition.reason_after_due:
        template = condition.reason_after_due
    # D-49 gates. A verified rule is enforced: before it opens, or after it closes, the rung is
    # not offered. An unverified one only changes the sentence and the rung stays offered, marked.
    if opens is not None and opens.days_remaining > 0:
        template, available = condition.reason_before_open or template, not opens.verified
    elif closes is not None and closes.days_remaining < 0:
        template, available = condition.reason_after_close or template, not closes.verified

    values = {
        "event_date": _entered_on(context, condition.state) or "an unrecorded date",
        "due": _date(due), "opens": _date(opens), "closes": _date(closes),
    }
    verified = rung.verified and all(deadline.verified for deadline in used.values() if deadline is not None)
    reason = template.format(**values)
    if not verified:
        reason = f"{reason} {UNVERIFIED_NOTE}"
    return GrievanceRungOption(rung=name, label=rung.label, available=available, reason=reason, rule_ids=list(used), verified=verified)


def rung_options(
    context: RungContext, rungs: GrievanceRungs, ombudsman_limit: str | None = None, ombudsman_award_time: str | None = None
) -> list[GrievanceRungOption]:
    """One option per rung, in ladder order.

    Verified Ombudsman information (app/rules/ombudsman_rules.yaml), None to show nothing:
      ombudsman_limit       the award ceiling, added to the Ombudsman rung when it is offered
      ombudsman_award_time  Rule 17(4)'s award period, added once a complaint has been filed (escalated)
    """
    options = []
    for name, rung in rungs.rungs.items():
        condition = next((c for c in rung.when if c.state == context.current_state), None)
        option = _option(name, rungs, condition, context)
        if name == "insurance_ombudsman":
            extra = ombudsman_limit if option.available else ombudsman_award_time if context.current_state == "escalated" else None
            if extra:
                option = option.model_copy(update={"reason": f"{option.reason} {extra}"})
        options.append(option)
    return options
