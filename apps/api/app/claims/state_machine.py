"""The claim state machine. This dict is the ONLY definition of what may follow what.

Every other piece of code that needs to know a legal transition asks this
module. Nothing else lists states or transitions, so the rules cannot drift
apart between the API, the database constraints and the tests.

The graph (ratified as API_DECISIONS D-31, amended by D-49):

    intimated           -> documents_submitted, queried
    documents_submitted -> under_review, queried
    under_review        -> queried, approved, denied
    queried             -> documents_submitted, under_review
    approved            -> resolved
    denied              -> grievance_sent, resolved
    grievance_sent      -> insurer_replied, escalated, resolved
    insurer_replied     -> escalated, resolved
    escalated           -> resolved
    resolved            -> (nothing: the claim is closed)

D-49 follows Rule 14(3)(a) of the Insurance Ombudsman Rules, 2017: a complaint
to the Ombudsman lies only after a written representation to the insurer
(`grievance_sent`) and its rejection or an unsatisfactory reply
(`insurer_replied`), or no reply within one month. `escalated` means a
complaint filed beyond the insurer. The one-month and one-year timings are
deadline rules (app/rules/deadline_rules.yaml), not transitions: the graph says
what may follow what, never when.
"""

from __future__ import annotations

INITIAL_STATE = "intimated"

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "intimated": ("documents_submitted", "queried"),
    "documents_submitted": ("under_review", "queried"),
    "under_review": ("queried", "approved", "denied"),
    "queried": ("documents_submitted", "under_review"),
    "approved": ("resolved",),
    "denied": ("grievance_sent", "resolved"),
    "grievance_sent": ("insurer_replied", "escalated", "resolved"),
    "insurer_replied": ("escalated", "resolved"),
    "escalated": ("resolved",),
    "resolved": (),
}

# Every state, in lifecycle order. Derived from the dict, never typed twice.
STATES: tuple[str, ...] = tuple(TRANSITIONS)


def allowed_targets(current_state: str) -> tuple[str, ...]:
    """The states a claim may move to from `current_state`."""
    return TRANSITIONS.get(current_state, ())


def is_allowed(current_state: str, to_state: str) -> bool:
    return to_state in allowed_targets(current_state)
