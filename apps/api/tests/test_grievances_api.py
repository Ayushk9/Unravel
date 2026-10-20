"""Grievance drafting and Ombudsman awards through the API, against a real Postgres (temporary schema).

Fake models (word overlap) and a fake Gemini (FakeGrievanceLlm): no download, no API call.
The policy's clauses are inserted directly, as in test_questions_api.py.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.api.v1 import eligibility as eligibility_route
from app.api.v1 import grievances as grievances_route
from app.core.ids import new_id
from app.grievance.llm import GeneratedDraft, GeneratedParagraph
from app.grievance.run_draft import LLM_BUSY
from app.qa.indexing import index_document
from app.qa.llm import LlmError
from engines.rules.precedent import NOTE_MATCHED, load_awards
from tests.db import ApiTester, Database, run
from tests.fake_models import FakeGrievanceLlm, FakeModels

CLAUSES = [
    (9, "Room rent: up to Rs 5,000 per day.", (0.1, 0.20, 0.8, 0.24)),
    (31, "Pre-existing diseases: covered after 36 months of continuous coverage from the first policy.", (0.1, 0.30, 0.8, 0.33)),
    (31, "Pre-existing disease means any condition diagnosed within 48 months before the first policy.", (0.1, 0.40, 0.8, 0.43)),
]
DRAFT_KEYS = {
    "id", "claim_id", "rung", "subject", "addressee", "header_lines", "paragraphs", "citations", "evidence_checklist",
    "citation_precision", "closing", "disclaimer", "letter_text", "missing_context", "generated_at",
}
DENIAL_REASON = "Denied as a pre-existing disease within the waiting period"


def _index_policy(db: Database, household_id: UUID) -> tuple[str, UUID]:
    policy_id = db.create_policy(household_id)
    document_id = db.scalar("SELECT source_document_id FROM policy WHERE id = :p", p=policy_id)
    for position, (page, text, bbox) in enumerate(CLAUSES):
        db.execute(
            "INSERT INTO document_chunk (id, document_id, position, page, text, bbox) VALUES (:id, :d, :p, :page, :text, CAST(:bbox AS jsonb))",
            id=new_id(), d=document_id, p=position, page=page, text=text, bbox=f"[{', '.join(map(str, bbox))}]",
        )
    run(index_document(db.session_factory, FakeModels(), document_id))
    return str(policy_id), document_id


def _claim(world: SimpleNamespace, policy_id: str | None = None, path: tuple[str, ...] = ("documents_submitted", "under_review", "denied")) -> str:
    response = world.api.post("/claims", json={
        "policy_id": policy_id or world.policy_id, "member_id": world.member_id, "claim_type": "reimbursement",
        "admission_type": "planned", "hospital_name": "Navjeevan Multispeciality Hospital, Pune", "admitted_on": "2026-04-02",
        "discharged_on": "2026-04-06", "claimed_amount": 18_500_000,
    })
    assert response.status_code == 201, response.text
    claim_id = response.json()["id"]
    for day, state in enumerate(path, start=10):
        note = DENIAL_REASON if state == "denied" else None
        event = world.api.post(f"/claims/{claim_id}/events", json={"to_state": state, "occurred_at": f"2026-04-{day}T10:00:00+05:30", "note": note})
        assert event.status_code == 200, event.text
    return claim_id


@pytest.fixture(scope="module")
def household(database: Database) -> SimpleNamespace:
    """One household with an indexed policy for the module. Claims can't be deleted (append-only events);
    the temporary schema is dropped at the end of the session."""
    household_id = database.create_household()
    policy_id, document_id = _index_policy(database, household_id)
    member_id = str(database.create_member(household_id, "Lakshmi Rao"))
    return SimpleNamespace(household_id=household_id, policy_id=policy_id, document_id=document_id, member_id=member_id)


@pytest.fixture
def world(database: Database, household: SimpleNamespace) -> Iterator[SimpleNamespace]:
    """A fresh denied claim and a fresh fake Gemini for each test."""
    api = ApiTester(database, household.household_id)
    llm = FakeGrievanceLlm()
    api.use_worker(_succeed(), models=FakeModels(), grievance_llm=llm)
    world = SimpleNamespace(api=api, db=database, llm=llm, **vars(household))
    world.claim_id = _claim(world)
    yield world
    api.finish_jobs()


def _succeed():
    from tests import fake_workers

    return fake_workers.succeed


NEW_KEY = "new"


def _request(world: SimpleNamespace, rung: str = "insurer_grievance_cell", key: str | None = NEW_KEY, claim_id: str | None = None):
    # The household is shared by the module's tests, so each request gets its own key unless a test names one.
    key = f"key-{new_id()}" if key == NEW_KEY else key
    headers = {"Idempotency-Key": key} if key is not None else {}
    return world.api.post(f"/claims/{claim_id or world.claim_id}/grievance-drafts", json={"rung": rung}, headers=headers)


def _draft(world: SimpleNamespace, rung: str = "insurer_grievance_cell", key: str = NEW_KEY) -> dict:
    response = _request(world, rung, key)
    assert response.status_code == 202, response.text
    world.api.finish_jobs()
    return world.api.get(f"/jobs/{response.json()['job_id']}").json()


# --- rungs ---


def test_rungs_after_a_denial_are_all_offered_and_marked_unverified(world: SimpleNamespace) -> None:
    response = world.api.get(f"/claims/{world.claim_id}/grievance-rungs")

    assert response.status_code == 200
    options = response.json()
    assert [o["rung"] for o in options] == ["insurer_grievance_cell", "irdai_bima_bharosa", "insurance_ombudsman"]
    assert all(set(o) == {"rung", "label", "available", "reason", "rule_ids", "verified"} for o in options)
    assert all(o["available"] and o["verified"] is False for o in options)
    assert "12 Apr 2026" in options[2]["reason"], "denied on the third event's date"


# --- the job ---


def test_a_draft_is_a_job_whose_result_has_the_contract_shape_and_is_recorded(world: SimpleNamespace) -> None:
    job = _draft(world)

    assert job["status"] == "succeeded", job["error"]
    assert job["kind"] == "generate_grievance_draft" and job["progress"] == {"step": "done", "percent": 100}
    draft = job["result"]
    assert set(draft) == DRAFT_KEYS and draft["rung"] == "insurer_grievance_cell"
    header = {line["label"]: line["value"] for line in draft["header_lines"]}
    assert header["Insured person (patient)"] == "Lakshmi Rao" and header["Amount claimed"] == "₹1,85,000"
    assert header["Reason for denial, as recorded"] == f"“{DENIAL_REASON}”"
    assert draft["paragraphs"] and all(set(p) == {"text", "citation_ids", "verified"} for p in draft["paragraphs"])
    cited = {c["id"] for c in draft["citations"]}
    assert all(set(p["citation_ids"]) <= cited for p in draft["paragraphs"])
    assert all(c["kind"] == "policy_clause" and c["provenance"]["document_id"] == str(world.document_id) for c in draft["citations"])
    assert "not legal advice" in draft["disclaimer"] and draft["disclaimer"] in draft["letter_text"]

    row = world.db.execute("SELECT id, rung, prompt_version, models, verification FROM grievance_draft WHERE claim_id = :c", c=world.claim_id)
    assert len(row) == 1 and str(row[0].id) == draft["id"] and row[0].models == {"draft": "fake-model", "judge": "fake-model"}
    assert len(row[0].verification["paragraphs"]) == len(draft["paragraphs"])


def test_an_unsupported_paragraph_is_kept_with_verified_false(world: SimpleNamespace) -> None:
    def two_paragraphs(_rung: str, _facts: str, clauses: list) -> GeneratedDraft:
        ped = next(c.id for c in clauses if "36 months" in c.text)  # whichever short id retrieval gave it
        return GeneratedDraft(abstain=False, paragraphs=[
            GeneratedParagraph(text="My policy covers pre-existing diseases after 36 months of continuous coverage.", chunk_ids=[ped]),
            GeneratedParagraph(text="My policy says pre-existing diseases are never excluded.", chunk_ids=[ped]),
        ])

    world.llm._draft = two_paragraphs
    world.llm._judge = lambda pairs: ["never excluded" not in text for text, _ in pairs]

    draft = _draft(world)["result"]

    assert [p["verified"] for p in draft["paragraphs"]] == [True, False]
    assert draft["paragraphs"][1]["text"] == "My policy says pre-existing diseases are never excluded."
    assert draft["citation_precision"] == pytest.approx(0.5)


def test_drafts_are_never_cached(world: SimpleNamespace) -> None:
    first = _draft(world)["result"]
    second = _draft(world)["result"]
    assert world.llm.calls.count("draft") == 2 and first["id"] != second["id"]


def test_gemini_busy_fails_the_job_readably(world: SimpleNamespace) -> None:
    world.llm.fail_with = LlmError("503", code="overloaded", retryable=True)

    job = _draft(world)

    assert job["status"] == "failed" and job["error"] == LLM_BUSY
    row = world.db.execute("SELECT error_code, retryable FROM job WHERE id = :j", j=job["job_id"])[0]
    assert row.error_code == "llm_overloaded" and row.retryable is True


# --- idempotency and errors ---


def test_the_same_key_replays_and_a_different_rung_is_409(world: SimpleNamespace) -> None:
    world.api.hold_jobs()
    key = f"same-{new_id()}"
    first = _request(world, key=key)
    again = _request(world, key=key)
    other = _request(world, rung="insurance_ombudsman", key=key)

    assert first.status_code == again.status_code == 202 and first.json() == again.json()
    assert other.status_code == 409 and other.json()["error"]["code"] == "idempotency_key_reused"
    assert world.db.scalar("SELECT count(*) FROM job WHERE household_id = :h AND idempotency_key = :k", h=world.household_id, k=key) == 1


@pytest.mark.parametrize(("rung", "key", "field"), [("insurer_grievance_cell", None, "Idempotency-Key"), ("other", "k", "rung")])
def test_a_missing_key_or_a_bad_rung_is_422(world: SimpleNamespace, rung: str, key: str | None, field: str) -> None:
    response = _request(world, rung=rung, key=key)
    assert response.status_code == 422
    assert field in {f["field"].split(".")[-1] for f in response.json()["error"]["field_errors"]}


def test_a_rung_that_does_not_fit_the_claim_yet_is_409_listing_those_that_do(world: SimpleNamespace) -> None:
    under_review = _claim(world, path=("documents_submitted", "under_review"))

    response = _request(world, rung="insurance_ombudsman", claim_id=under_review)

    error = response.json()["error"]
    assert response.status_code == 409 and error["code"] == "rung_not_available"
    assert error["field_errors"] == [{"field": "rung", "message": "insurer_grievance_cell"}]


def test_an_unindexed_policy_is_409(world: SimpleNamespace) -> None:
    unindexed = str(world.db.create_policy(world.household_id))
    claim_id = _claim(world, policy_id=unindexed)

    response = _request(world, claim_id=claim_id)

    assert response.status_code == 409 and response.json()["error"]["code"] == "policy_not_indexed"


def test_another_households_claim_is_404_on_both_routes(world: SimpleNamespace) -> None:
    other = world.db.create_household()
    with world.api.acting_as(other):
        rungs = world.api.get(f"/claims/{world.claim_id}/grievance-rungs")
        drafts = _request(world)
    assert rungs.status_code == drafts.status_code == 404
    assert drafts.json()["error"]["code"] == "not_found"


# --- awards ---

AWARDS_YAML = """
version: 1
awards:
  - {case_reference: "C/1", insurer_name: "Insurer A", decided_on: 2025-03-01, denial_ground: ped_waiting_period,
     outcome: overturned, summary: "One.", external_url: null, checked_by_ayush: true}
  - {case_reference: "C/2", insurer_name: "Insurer B", decided_on: 2025-02-01, denial_ground: room_rent_sub_limit,
     outcome: upheld, summary: "Two.", external_url: null, checked_by_ayush: true}
  - {case_reference: "C/3", insurer_name: "Insurer C", decided_on: 2025-01-01, denial_ground: ped_waiting_period,
     outcome: partially_allowed, summary: "Three.", external_url: null, checked_by_ayush: true}
  - {case_reference: "UNCHECKED", insurer_name: "Insurer D", decided_on: 2025-04-01, denial_ground: ped_waiting_period,
     outcome: overturned, summary: "Not checked.", external_url: null, checked_by_ayush: false}
"""


@pytest.fixture
def awards_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "awards.yaml"
    path.write_text(AWARDS_YAML, encoding="utf-8")
    for module in (grievances_route, eligibility_route):
        monkeypatch.setattr(module, "load_awards", lambda: load_awards(path))


def test_awards_with_no_checked_entries_is_an_empty_page(world: SimpleNamespace) -> None:
    assert world.api.get("/ombudsman-awards").json() == {"items": [], "next_cursor": None, "total": 0}


def test_awards_are_paginated_newest_first_and_unchecked_ones_never_served(world: SimpleNamespace, awards_file: None) -> None:
    first = world.api.get("/ombudsman-awards", params={"limit": 2}).json()
    second = world.api.get("/ombudsman-awards", params={"limit": 2, "cursor": first["next_cursor"]}).json()

    assert [a["case_reference"] for a in first["items"]] == ["C/1", "C/2"] and first["total"] == 3
    assert [a["case_reference"] for a in second["items"]] == ["C/3"] and second["next_cursor"] is None
    assert first["items"][0]["denial_ground"] == "Pre-existing disease waiting period"
    assert "UNCHECKED" not in str(first) + str(second)
    assert world.api.get("/ombudsman-awards", params={"cursor": str(new_id())}).status_code == 422


def test_eligibility_precedent_matches_failed_checks_by_tag(world: SimpleNamespace, awards_file: None) -> None:
    world.db.execute("UPDATE policy SET start_date = '2026-01-01', end_date = '2026-12-31' WHERE id = :p", p=world.policy_id)
    world.api.request("PUT", f"/claims/{world.claim_id}/facts", json={
        "diagnosis": None, "condition_is_pre_existing": True, "first_diagnosed_on": "2023-11-05",
        "matched_waiting_periods": None, "matched_exclusions": None, "planned_room_rent_per_day": None,
    })

    assessment = world.api.post(f"/claims/{world.claim_id}/eligibility").json()

    ped = next(c for c in assessment["checks"] if c["id"] == "ped_waiting_period")
    assert ped["status"] in ("failed", "at_risk")
    assert [a["case_reference"] for a in assessment["ombudsman_precedent"]] == ["C/1", "C/3"]
    assert assessment["ombudsman_precedent_note"] == NOTE_MATCHED
