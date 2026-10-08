"""The claim state machine. This dict is the ONLY definition of what may follow what.

Every other piece of code that needs to know a legal transition asks this
module. Nothing else lists states or transitions, so the rules cannot drift
apart between the API, the database constraints and the tests.

The graph (ratified as API_DECISIONS D-31):

    intimated           -> documents_submitted, queried
    documents_submitted -> under_review, queried
    under_review        -> queried, approved, denied
    queried             -> documents_submitted, under_review
    approved            -> resolved
    denied              -> escalated, resolved
    escalated           -> resolved
    resolved            -> (nothing: the claim is closed)
"""

from __future__ import annotations

INITIAL_STATE = "intimated"

TRANSITIONS: dict[str, tuple[str, ...]] = {
    "intimated": ("documents_submitted", "queried"),
    "documents_submitted": ("under_review", "queried"),
    "under_review": ("queried", "approved", "denied"),
    "queried": ("documents_submitted", "under_review"),
    "approved": ("resolved",),
    "denied": ("escalated", "resolved"),
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
