"""Claims through the API, against a real Postgres (temporary schema)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from app.claims.deadlines import INDIA, add_months, india_date
from app.claims.events import append_event
from app.claims.state_machine import STATES, TRANSITIONS, allowed_targets
from app.core.errors import ApiError
from app.core.ids import new_id
from app.db.models import Claim, ClaimEvent
from app.schemas.claims import ClaimEventRequest
from tests.db import ApiTester, Database, run

ENVELOPE_KEYS = {"code", "message", "field_errors", "request_id", "retryable"}
CLAIM_KEYS = {
    "id", "policy_id", "member_id", "claim_type", "admission_type", "hospital_name", "admitted_on", "discharged_on",
    "claimed_amount", "settled_amount", "current_state", "events", "deadlines", "omitted_deadlines", "facts",
}


def _now_iso() -> str:
    return datetime.now(INDIA).replace(microsecond=0).isoformat()


@pytest.fixture(scope="module")
def world(database: Database) -> SimpleNamespace:
    """One household with a member and a parsed policy, shared by this module."""
    household_id = database.create_household()
    api = ApiTester(database, household_id)
    return SimpleNamespace(
        api=api,
        db=database,
        household_id=household_id,
        member_id=str(database.create_member(household_id)),
        policy_id=str(database.create_policy(household_id)),
    )


def _body(world: SimpleNamespace, **overrides) -> dict:
    body = {
        "policy_id": world.policy_id,
        "member_id": world.member_id,
        "claim_type": "reimbursement",
        "admission_type": "emergency",
        "hospital_name": "  Sahyadri Hospital  ",
        "admitted_on": "2026-03-01",
        "discharged_on": "2026-03-04",
        "claimed_amount": 18_500_000,
    }
    body.update(overrides)
    return body


def _create(world: SimpleNamespace, **overrides) -> dict:
    response = world.api.post("/claims", json=_body(world, **overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _move(world: SimpleNamespace, claim_id: str, to_state: str, occurred_at: str | None = None, note: str | None = None):
    return world.api.post(
        f"/claims/{claim_id}/events", json={"to_state": to_state, "occurred_at": occurred_at or _now_iso(), "note": note}
    )


def _walk(world: SimpleNamespace, claim_id: str, *states: str) -> dict:
    claim = None
    for state in states:
        response = _move(world, claim_id, state)
        assert response.status_code == 200, f"-> {state}: {response.text}"
        claim = response.json()
    return claim


# --- creating a claim ---


def test_create_claim_returns_201_with_its_first_event_and_no_guessed_deadline(world: SimpleNamespace) -> None:
    claim = _create(world)

    assert set(claim) == CLAIM_KEYS
    assert UUID(claim["id"]).version == 7
    assert claim["hospital_name"] == "Sahyadri Hospital"
    assert claim["claimed_amount"] == 18_500_000 and type(claim["claimed_amount"]) is int
    assert claim["settled_amount"] is None
    assert claim["current_state"] == "intimated"

    (event,) = claim["events"]
    assert set(event) == {"id", "claim_id", "from_state", "to_state", "occurred_at", "note", "source"}
    assert (event["from_state"], event["to_state"], event["source"]) == (None, "intimated", "user")
    assert event["claim_id"] == claim["id"]

    # The fixture policy has no intimation deadline extracted: omitted, with a reason.
    assert claim["deadlines"] == []
    (omitted,) = claim["omitted_deadlines"]
    assert set(omitted) == {"id", "label", "reason"}
    assert omitted["label"] == "Claim intimation window" and "not found" in omitted["reason"]


def test_claim_and_first_event_are_stored_together_and_state_is_not_a_column(world: SimpleNamespace) -> None:
    claim = _create(world)
    db = world.db

    row = db.execute("SELECT seq, from_state, to_state, source, created_by, recorded_at FROM claim_event WHERE claim_id = :c", c=claim["id"])
    assert len(row) == 1 and (row[0].seq, row[0].from_state, row[0].to_state) == (1, None, "intimated")
    assert row[0].created_by is not None and row[0].recorded_at is not None

    columns = {r[0] for r in db.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = 'claim'"
    )}
    assert not columns & {"status", "state", "current_state"}, "state must be derived from the log, never stored"
    assert db.scalar("SELECT current_state FROM claim_current_state WHERE claim_id = :c", c=claim["id"]) == "intimated"


def test_nullable_claim_fields_are_emitted_as_null(world: SimpleNamespace) -> None:
    claim = _create(world, admitted_on=None, discharged_on=None, claimed_amount=None)

    assert (claim["admitted_on"], claim["discharged_on"], claim["claimed_amount"]) == (None, None, None)
    assert "admission date" in claim["omitted_deadlines"][0]["reason"] or "not found" in claim["omitted_deadlines"][0]["reason"]


def test_invalid_create_requests_are_422_and_create_nothing(world: SimpleNamespace) -> None:
    other_household = world.db.create_household()
    foreign_policy = str(world.db.create_policy(other_household))
    foreign_member = str(world.db.create_member(other_household))
    before = world.db.scalar("SELECT count(*) FROM claim WHERE household_id = :h", h=world.household_id)

    cases = {
        "policy_id": _body(world, policy_id=str(new_id())),  # does not exist
        "policy_id ": _body(world, policy_id=foreign_policy),  # exists, but in another household
        "member_id": _body(world, member_id=foreign_member),
        "claim_type": _body(world, claim_type="barter"),
        "admission_type": _body(world, admission_type="walk_in"),
        "hospital_name": _body(world, hospital_name="   "),
        "claimed_amount": _body(world, claimed_amount=18500.5),  # fractional paise
        "claimed_amount ": _body(world, claimed_amount=-1),
        "admitted_on": _body(world, admitted_on="01-03-2026"),
    }
    for field, body in cases.items():
        response = world.api.post("/claims", json=body)
        assert response.status_code == 422, f"{field}: {response.text}"
        error = response.json()["error"]
        assert set(error) == ENVELOPE_KEYS and error["code"] == "validation_error"
        assert field.strip() in {e["field"] for e in error["field_errors"]}, (field, error)

    backwards = world.api.post("/claims", json=_body(world, admitted_on="2026-03-04", discharged_on="2026-03-01"))
    assert backwards.status_code == 422

    assert world.db.scalar("SELECT count(*) FROM claim WHERE household_id = :h", h=world.household_id) == before


# --- the state machine through the API ---


@pytest.fixture(scope="module")
def walked(world: SimpleNamespace) -> SimpleNamespace:
    """Claims driven along paths that together use every allowed transition (D-31 as amended by D-49)."""
    paths = [
        ("documents_submitted", "under_review", "queried", "documents_submitted", "queried", "under_review", "approved", "resolved"),
        ("queried", "under_review", "denied", "grievance_sent", "insurer_replied", "escalated", "resolved"),
        ("documents_submitted", "under_review", "denied", "resolved"),
        ("documents_submitted", "under_review", "denied", "grievance_sent", "escalated", "resolved"),
        ("documents_submitted", "under_review", "denied", "grievance_sent", "resolved"),
        ("documents_submitted", "under_review", "denied", "grievance_sent", "insurer_replied", "resolved"),
    ]
    claims = []
    for path in paths:
        created = _create(world)
        claims.append(_walk(world, created["id"], *path))
    return SimpleNamespace(paths=paths, claims=claims)


def test_every_allowed_transition_succeeds(walked: SimpleNamespace) -> None:
    traversed = set()
    for claim in walked.claims:
        for event in claim["events"][1:]:
            traversed.add((event["from_state"], event["to_state"]))

    every_allowed_edge = {(state, target) for state, targets in TRANSITIONS.items() for target in targets}
    assert traversed == every_allowed_edge
    assert len(every_allowed_edge) == 18  # D-31 amended by D-49


def test_the_log_is_ordered_and_each_event_starts_where_the_last_ended(walked: SimpleNamespace, world: SimpleNamespace) -> None:
    claim, path = walked.claims[0], walked.paths[0]

    assert [e["to_state"] for e in claim["events"]] == ["intimated", *path]
    assert [e["from_state"] for e in claim["events"]] == [None, "intimated", *path[:-1]]
    assert claim["current_state"] == "resolved"
    seqs = [r.seq for r in world.db.execute("SELECT seq FROM claim_event WHERE claim_id = :c ORDER BY seq", c=claim["id"])]
    assert seqs == list(range(1, len(path) + 2))


def test_get_claim_and_list_claims_agree_with_the_log(walked: SimpleNamespace, world: SimpleNamespace) -> None:
    fetched = world.api.get(f"/claims/{walked.claims[1]['id']}")
    listed = world.api.get("/claims")

    assert fetched.status_code == 200 and fetched.json() == walked.claims[1] | {"deadlines": fetched.json()["deadlines"]}
    assert isinstance(listed.json(), list), "CONTRACTS.md row 13: a flat array; the client does the grouping"
    by_id = {claim["id"]: claim for claim in listed.json()}
    assert by_id[walked.claims[0]["id"]]["current_state"] == "resolved"
    assert all(set(claim) == CLAIM_KEYS for claim in listed.json())


def _assert_illegal(response, from_state: str) -> None:
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert set(error) == ENVELOPE_KEYS
    assert error["code"] == "illegal_transition" and error["retryable"] is False
    # One entry per allowed state, each {field: "to_state", message: <state>} (D-04).
    assert all(entry["field"] == "to_state" for entry in error["field_errors"])
    assert [entry["message"] for entry in error["field_errors"]] == list(allowed_targets(from_state))


def test_every_illegal_transition_from_a_new_claim_is_409_with_the_allowed_targets(world: SimpleNamespace) -> None:
    claim = _create(world)
    illegal = [state for state in STATES if state not in allowed_targets("intimated")] + ["unknown", "banana"]

    for to_state in illegal:
        _assert_illegal(_move(world, claim["id"], to_state), "intimated")

    assert len(illegal) == 10
    after = world.api.get(f"/claims/{claim['id']}").json()
    assert after["current_state"] == "intimated" and len(after["events"]) == 1, "a refused transition writes nothing"


def test_a_resolved_claim_accepts_nothing_and_says_so_with_an_empty_list(walked: SimpleNamespace, world: SimpleNamespace) -> None:
    resolved = walked.claims[0]

    for to_state in STATES:
        response = _move(world, resolved["id"], to_state)
        _assert_illegal(response, "resolved")
        assert response.json()["error"]["field_errors"] == []


def test_illegal_transitions_from_a_mid_state_list_that_states_targets(world: SimpleNamespace) -> None:
    claim = _create(world)
    _walk(world, claim["id"], "documents_submitted", "under_review")

    for to_state in ("resolved", "escalated", "intimated", "under_review"):
        _assert_illegal(_move(world, claim["id"], to_state), "under_review")


def test_event_time_must_have_a_zone_and_must_not_be_in_the_future(world: SimpleNamespace) -> None:
    claim = _create(world)
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

    naive = _move(world, claim["id"], "documents_submitted", occurred_at="2026-03-05T10:00:00")
    future = _move(world, claim["id"], "documents_submitted", occurred_at=tomorrow)

    assert naive.status_code == 422 and future.status_code == 422
    assert future.json()["error"]["field_errors"][0]["field"] == "occurred_at"
    assert len(world.api.get(f"/claims/{claim['id']}").json()["events"]) == 1


def test_an_event_can_be_dated_in_the_past_and_keeps_both_times(world: SimpleNamespace) -> None:
    claim = _create(world)

    response = _move(world, claim["id"], "documents_submitted", occurred_at="2026-03-06T16:30:00+05:30", note="  Posted the file  ")

    event = response.json()["events"][-1]
    assert event["note"] == "Posted the file"
    assert datetime.fromisoformat(event["occurred_at"]) == datetime(2026, 3, 6, 16, 30, tzinfo=INDIA)
    row = world.db.execute("SELECT occurred_at, recorded_at FROM claim_event WHERE id = :e", e=event["id"])[0]
    assert row.recorded_at > row.occurred_at, "recorded_at is when it was logged, set by the database"


# --- append-only, enforced by the database ---


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE claim_event SET to_state = 'approved' WHERE claim_id = :c",
        "UPDATE claim_event SET note = 'rewritten' WHERE claim_id = :c",
        "DELETE FROM claim_event WHERE claim_id = :c",
    ],
)
def test_raw_sql_cannot_update_or_delete_an_event(world: SimpleNamespace, statement: str) -> None:
    claim = _create(world)

    with pytest.raises(DBAPIError, match="claim_event is append-only"):
        world.db.execute(statement, c=claim["id"])

    assert world.db.scalar("SELECT to_state FROM claim_event WHERE claim_id = :c", c=claim["id"]) == "intimated"


def test_raw_sql_cannot_truncate_the_log(world: SimpleNamespace) -> None:
    before = world.db.scalar("SELECT count(*) FROM claim_event")

    with pytest.raises(DBAPIError, match="claim_event is append-only"):
        world.db.execute("TRUNCATE claim_event")

    assert world.db.scalar("SELECT count(*) FROM claim_event") == before > 0


def test_a_claim_with_history_cannot_be_deleted_either(world: SimpleNamespace) -> None:
    claim = _create(world)

    with pytest.raises(DBAPIError):
        world.db.execute("DELETE FROM claim WHERE id = :c", c=claim["id"])


def test_inserting_is_still_allowed_and_the_view_follows_the_latest_event(world: SimpleNamespace) -> None:
    claim = _create(world)

    world.db.execute(
        "INSERT INTO claim_event (id, claim_id, seq, from_state, to_state, occurred_at, source) "
        "VALUES (:id, :c, 2, 'intimated', 'queried', now(), 'system')",
        id=new_id(), c=claim["id"],
    )

    view = world.db.execute("SELECT current_state, latest_seq FROM claim_current_state WHERE claim_id = :c", c=claim["id"])[0]
    assert (view.current_state, view.latest_seq) == ("queried", 2)
    assert world.api.get(f"/claims/{claim['id']}").json()["current_state"] == "queried"


def test_the_database_rejects_a_state_that_is_not_in_the_machine(world: SimpleNamespace) -> None:
    claim = _create(world)

    with pytest.raises(DBAPIError):
        world.db.execute(
            "INSERT INTO claim_event (id, claim_id, seq, from_state, to_state, occurred_at, source) "
            "VALUES (:id, :c, 2, 'intimated', 'paid_in_full', now(), 'user')",
            id=new_id(), c=claim["id"],
        )


# --- two transitions at once ---


def _under_review_claim(world: SimpleNamespace) -> str:
    claim = _create(world)
    _walk(world, claim["id"], "documents_submitted", "under_review")
    return claim["id"]


def test_two_simultaneous_transitions_from_one_state_exactly_one_succeeds(world: SimpleNamespace) -> None:
    claim_id = _under_review_claim(world)

    async def both() -> list:
        async def send(to_state: str):
            async with world.api.client() as client:
                return await client.post(
                    f"/api/v1/claims/{claim_id}/events", json={"to_state": to_state, "occurred_at": _now_iso(), "note": None}
                )
        return await asyncio.gather(send("approved"), send("denied"))

    approved, denied = run(both())

    assert sorted([approved.status_code, denied.status_code]) == [200, 409]
    loser = approved if approved.status_code == 409 else denied
    assert loser.json()["error"]["code"] in {"claim_changed", "illegal_transition"}

    events = world.db.execute("SELECT seq, to_state FROM claim_event WHERE claim_id = :c ORDER BY seq", c=claim_id)
    assert [e.seq for e in events] == [1, 2, 3, 4], "exactly one new event, no gap and no duplicate seq"
    assert events[-1].to_state in {"approved", "denied"}


def test_an_event_slipped_in_between_read_and_write_is_caught_by_the_unique_constraint(world: SimpleNamespace) -> None:
    """Deterministic version of the race: the competing insert happens exactly between our read and our commit."""
    claim_id = UUID(_under_review_claim(world))
    now = datetime.now(timezone.utc)

    async def scenario() -> ApiError:
        async with world.db.session_factory() as ours, world.db.session_factory() as theirs:
            claim = await ours.get(Claim, claim_id)
            real_commit = ours.commit

            async def commit_after_a_rival_gets_in_first() -> None:
                theirs.add(
                    ClaimEvent(id=new_id(), claim_id=claim_id, seq=4, from_state="under_review", to_state="denied",
                               occurred_at=now, source="user", created_by=uuid4())
                )
                await theirs.commit()
                await real_commit()

            ours.commit = commit_after_a_rival_gets_in_first  # type: ignore[method-assign]
            try:
                await append_event(ours, claim, uuid4(), ClaimEventRequest(to_state="approved", occurred_at=now, note=None), now)
            except ApiError as error:
                return error
        raise AssertionError("the second writer should have been refused")

    error = run(scenario())

    assert (error.status_code, error.code, error.retryable) == (409, "claim_changed", True)
    events = world.db.execute("SELECT seq, to_state FROM claim_event WHERE claim_id = :c ORDER BY seq", c=claim_id)
    assert [(e.seq, e.to_state) for e in events][-1] == (4, "denied"), "the rival's event stands; ours wrote nothing"
    assert len(events) == 4


# --- deadlines through the API ---


def test_the_ombudsman_clock_starts_with_the_written_grievance_not_the_denial(world: SimpleNamespace) -> None:
    """Rule 14(3) of the Insurance Ombudsman Rules, verified by Ayush on 2026-10-23 (D-49)."""
    claim = _create(world)
    _walk(world, claim["id"], "documents_submitted", "under_review")
    today = india_date(datetime.now(timezone.utc))

    def on(day: date) -> str:
        return datetime.combine(day, datetime.min.time(), tzinfo=INDIA).replace(hour=11).isoformat()

    denied = _move(world, claim["id"], "denied", occurred_at=on(today - timedelta(days=20)), note="Denied as pre-existing").json()
    assert not [d for d in denied["deadlines"] if "Ombudsman" in d["label"]], "a denial alone starts no Ombudsman clock"
    assert not [d for d in denied["deadlines"] if d["label"] == "Insurer should decide by"], "a decision exists"

    sent_on = today - timedelta(days=10)
    sent = _move(world, claim["id"], "grievance_sent", occurred_at=on(sent_on), note="Wrote to the grievance cell").json()

    by_label = {d["label"]: d for d in sent["deadlines"]}
    opens, filing = by_label["You may approach the Ombudsman from"], by_label["Ombudsman filing window"]
    assert set(filing) == {"id", "label", "due_at", "days_remaining", "basis", "urgency", "source", "verified"}
    assert opens["verified"] is True and filing["verified"] is True
    assert filing["source"] == {
        "document": "Insurance Ombudsman Rules, 2017 (as amended till 09.11.2023)",
        "section": "Rule 14(3)(a) and (b)",
        "url": "https://www.cioins.co.in/notification/Insurance%20Ombudsman%20Rules,%202017(%20as%20amended%20till%2009.11.2023).pdf",
    }
    one_month = add_months(sent_on, 1)
    assert datetime.fromisoformat(opens["due_at"]).astimezone(INDIA).date() == one_month
    assert datetime.fromisoformat(filing["due_at"]).astimezone(INDIA).date() == add_months(one_month, 12)
    assert filing["due_at"].endswith("+05:30"), "an instant with an explicit offset (D-12)"


def test_deadlines_are_recomputed_on_every_read_not_stored(world: SimpleNamespace) -> None:
    claim = _create(world)
    _walk(world, claim["id"], "documents_submitted")

    first = world.api.get(f"/claims/{claim['id']}").json()["deadlines"]
    second = world.api.get(f"/claims/{claim['id']}").json()["deadlines"]

    assert [d["label"] for d in first] == ["Insurer should decide by"] and first == second
    tables = {r[0] for r in world.db.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")}
    assert not any("deadline" in table for table in tables)


def test_late_intimation_shows_an_expired_card_once_the_policy_states_a_window(world: SimpleNamespace) -> None:
    # A policy whose intimation deadline WAS extracted: 24 hours.
    policy_id = str(world.db.create_policy(world.household_id))
    world.db.execute("UPDATE coverage_profile SET intimation_deadline_hours_value = 24 WHERE policy_id = :p", p=policy_id)
    long_ago = (india_date(datetime.now(timezone.utc)) - timedelta(days=20)).isoformat()

    claim = _create(world, policy_id=policy_id, admitted_on=long_ago, discharged_on=None)

    (deadline,) = claim["deadlines"]
    assert deadline["label"] == "Claim intimation window"
    assert deadline["urgency"] == "expired" and deadline["days_remaining"] == -19
    assert "24 hours" in deadline["basis"] and "19 days later" in deadline["basis"]
    assert claim["omitted_deadlines"] == []


# --- other households ---


def test_another_households_claim_is_404_everywhere(world: SimpleNamespace) -> None:
    claim = _create(world)
    stranger = world.db.create_household()

    with world.api.acting_as(stranger):
        responses = {
            "get": world.api.get(f"/claims/{claim['id']}"),
            "event": _move(world, claim["id"], "documents_submitted"),
            "completeness": world.api.post(f"/claims/{claim['id']}/completeness"),
        }
        listed = world.api.get("/claims")
        upload = world.api.upload(claim_id=claim["id"], key=f"stranger-{uuid4()}")
        documents = world.api.get(f"/documents?claim_id={claim['id']}")

    for name, response in responses.items():
        assert response.status_code == 404, f"{name}: 404, never 403 (D-10)"
        assert response.json()["error"]["code"] == "not_found" and set(response.json()["error"]) == ENVELOPE_KEYS
    assert listed.json() == []
    assert upload.status_code == 422 and upload.json()["error"]["field_errors"][0]["field"] == "claim_id"
    assert documents.json() == {"items": [], "next_cursor": None, "total": 0}
    assert len(world.api.get(f"/claims/{claim['id']}").json()["events"]) == 1, "the stranger's event was not written"


def test_unknown_and_malformed_claim_ids_use_the_envelope(world: SimpleNamespace) -> None:
    missing = world.api.get(f"/claims/{new_id()}")
    malformed = world.api.get("/claims/not-a-uuid")

    assert missing.status_code == 404 and malformed.status_code == 422
    assert set(missing.json()["error"]) == set(malformed.json()["error"]) == ENVELOPE_KEYS
