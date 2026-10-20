"""Which escalation rungs a grievance letter can be drafted for, and why. Pure functions only.

Inputs: the claim's current state, its event log, the deadlines already
computed for it (app/claims/deadlines.py, from deadline_rules.yaml) and the
rung descriptions in app/rules/grievance_rungs.yaml. No clock is read: the
deadlines were computed for a `today` the caller chose.

A rung is offered when the claim is in one of the rung's `when` states. The
dates in its reason come from a deadline rule, never from this file. When a
rule behind the rung is unverified the rung is still offered, and marked, so
the user can decide; that is also why an expired window is reported as
"may have passed" rather than hidden.
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


def _option(name: str, rungs: GrievanceRungs, condition: RungCondition | None, context: RungContext) -> GrievanceRungOption:
    rung = rungs.rungs[name]
    if condition is None:
        return GrievanceRungOption(rung=name, label=rung.label, available=False, reason=rung.unavailable, rule_ids=[], verified=rung.verified)

    deadline = _deadline(context, condition.deadline) if condition.deadline else None
    if condition.deadline and deadline is None:
        # The rule applies in this state but has nothing to count from (its event is missing).
        # Offer the rung without a date rather than invent one.
        return GrievanceRungOption(
            rung=name, label=rung.label, available=True,
            reason=f"{rung.label} may be open to you, but the date it depends on could not be worked out from this claim's events.",
            rule_ids=[condition.deadline], verified=False,
        )

    template = condition.reason
    if deadline is not None and deadline.days_remaining < 0 and condition.reason_after_due:
        template = condition.reason_after_due
    values = {
        "event_date": _entered_on(context, condition.state) or "an unrecorded date",
        "due": format_date(deadline.due_at.date()) if deadline else "",
    }
    verified = rung.verified and (deadline.verified if deadline else True)
    reason = template.format(**values)
    if not verified:
        reason = f"{reason} {UNVERIFIED_NOTE}"
    return GrievanceRungOption(
        rung=name, label=rung.label, available=True, reason=reason,
        rule_ids=[condition.deadline] if condition.deadline else [], verified=verified,
    )


def rung_options(context: RungContext, rungs: GrievanceRungs) -> list[GrievanceRungOption]:
    """One option per rung, in ladder order."""
    options = []
    for name, rung in rungs.rungs.items():
        condition = next((c for c in rung.when if c.state == context.current_state), None)
        options.append(_option(name, rungs, condition, context))
    return options
