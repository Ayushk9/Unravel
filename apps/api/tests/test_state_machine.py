"""The transition table, checked for every one of the 100 (from, to) pairs."""

from __future__ import annotations

import pytest

from app.claims.state_machine import INITIAL_STATE, STATES, TRANSITIONS, allowed_targets, is_allowed

# Written out independently of the code under test, from API_DECISIONS D-31 as amended by D-49.
EXPECTED = {
    ("intimated", "documents_submitted"),
    ("intimated", "queried"),
    ("documents_submitted", "under_review"),
    ("documents_submitted", "queried"),
    ("under_review", "queried"),
    ("under_review", "approved"),
    ("under_review", "denied"),
    ("queried", "documents_submitted"),
    ("queried", "under_review"),
    ("approved", "resolved"),
    ("denied", "grievance_sent"),
    ("denied", "resolved"),
    ("grievance_sent", "insurer_replied"),
    ("grievance_sent", "escalated"),
    ("grievance_sent", "resolved"),
    ("insurer_replied", "escalated"),
    ("insurer_replied", "resolved"),
    ("escalated", "resolved"),
}
ALL_PAIRS = [(from_state, to_state) for from_state in STATES for to_state in STATES]


def test_there_are_ten_states_and_a_hundred_pairs() -> None:
    assert len(STATES) == 10 and len(ALL_PAIRS) == 100
    assert INITIAL_STATE == "intimated"


def test_a_denial_cannot_go_straight_to_the_ombudsman() -> None:
    """Rule 14(3)(a): a complaint lies only after a written grievance to the insurer (D-49)."""
    assert not is_allowed("denied", "escalated")
    assert is_allowed("denied", "grievance_sent") and is_allowed("grievance_sent", "escalated")


def test_the_wire_enum_lists_exactly_the_machines_states_in_order() -> None:
    from typing import get_args

    from app.schemas.claims import ClaimState

    assert get_args(ClaimState) == STATES


@pytest.mark.parametrize(("from_state", "to_state"), ALL_PAIRS)
def test_every_pair_is_allowed_exactly_when_the_ratified_graph_says_so(from_state: str, to_state: str) -> None:
    assert is_allowed(from_state, to_state) is ((from_state, to_state) in EXPECTED)


def test_no_state_may_transition_to_itself_or_back_to_intimated() -> None:
    for state in STATES:
        assert not is_allowed(state, state)
        assert not is_allowed(state, "intimated")


def test_resolved_is_the_only_terminal_state_and_every_state_can_reach_it() -> None:
    assert [state for state in STATES if not TRANSITIONS[state]] == ["resolved"]

    def reaches_resolved(state: str, seen: frozenset[str] = frozenset()) -> bool:
        if state == "resolved":
            return True
        return any(reaches_resolved(nxt, seen | {state}) for nxt in TRANSITIONS[state] if nxt not in seen)

    assert all(reaches_resolved(state) for state in STATES)


def test_every_target_is_itself_a_known_state() -> None:
    assert {target for targets in TRANSITIONS.values() for target in targets} <= set(STATES)


def test_unknown_states_have_no_targets() -> None:
    assert allowed_targets("unknown") == ()
    assert not is_allowed("intimated", "unknown")
