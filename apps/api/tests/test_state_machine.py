"""The transition table, checked for every one of the 64 (from, to) pairs."""

from __future__ import annotations

import pytest

from app.claims.state_machine import INITIAL_STATE, STATES, TRANSITIONS, allowed_targets, is_allowed

# Written out independently of the code under test, from API_DECISIONS D-31.
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
    ("denied", "escalated"),
    ("denied", "resolved"),
    ("escalated", "resolved"),
}
ALL_PAIRS = [(from_state, to_state) for from_state in STATES for to_state in STATES]


def test_there_are_eight_states_and_sixty_four_pairs() -> None:
    assert len(STATES) == 8 and len(ALL_PAIRS) == 64
    assert INITIAL_STATE == "intimated"


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
