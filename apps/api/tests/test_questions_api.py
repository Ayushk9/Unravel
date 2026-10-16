"""Policy Q&A through the API, against a real Postgres (temporary schema). Fake models and a fake Gemini.

The policy's clauses are inserted directly: the realistic text these tests
need is not in tests/fake_workers.build_policy_result.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.core.ids import new_id
from app.qa.cache import QaCache
from app.qa.indexing import index_document
from app.qa.llm import AnswerSentence, GeneratedAnswer
from app.qa.retrieval import retrieve
from app.qa.run_question import LLM_UNAVAILABLE, MODELS_UNAVAILABLE, NOT_ANSWERED, NOT_CONFIRMED
from tests.db import ApiTester, Database, run
from tests.fake_models import FakeModels, FakeQaLlm

CLAUSES = [
    (1, "Sum Insured: Rs. 5,00,000 for the family floater", (0.1, 0.10, 0.6, 0.12)),
    (2, "Room rent: up to Rs 5,000 per day. Associated medical expenses are paid in proportion if a higher room is chosen.", (0.1, 0.20, 0.8, 0.24)),
    (2, "Pre-existing diseases: covered after 48 months of continuous coverage", (0.1, 0.30, 0.8, 0.33)),
    (3, "Cosmetic or aesthetic treatment is excluded", (0.1, 0.40, 0.7, 0.42)),
    (3, "Claim intimation: within 24 hours of admission", (0.1, 0.50, 0.7, 0.52)),
]
RESULT_KEYS = {"answer", "citations", "abstained", "missing_context", "verification"}
ROOM_QUESTION = "What if I choose a ₹12,000/day room?"


def _add_clauses(db: Database, document_id: UUID, clauses=CLAUSES) -> None:
    db.execute("DELETE FROM document_chunk WHERE document_id = :d", d=document_id)
    for position, (page, text, bbox) in enumerate(clauses):
        db.execute(
            "INSERT INTO document_chunk (id, document_id, position, page, text, bbox) VALUES (:id, :d, :p, :page, :text, CAST(:bbox AS jsonb))",
            id=new_id(), d=document_id, p=position, page=page, text=text, bbox=f"[{', '.join(map(str, bbox))}]",
        )


def _make_policy(db: Database, household_id: UUID, *, indexed: bool = True) -> tuple[str, UUID]:
    policy_id = db.create_policy(household_id)
    document_id = db.scalar("SELECT source_document_id FROM policy WHERE id = :p", p=policy_id)
    _add_clauses(db, document_id)
    if indexed:
        run(index_document(db.session_factory, FakeModels(), document_id))
    return str(policy_id), document_id


@pytest.fixture
def world(database: Database, tmp_path: Path) -> SimpleNamespace:
    household_id = database.create_household()
    api = ApiTester(database, household_id)
    policy_id, document_id = _make_policy(database, household_id)
    models, llm, cache = FakeModels(), FakeQaLlm(), QaCache(tmp_path / "qa")
    api.use_worker(fake_workers_succeed(), models=models, qa_llm=llm, qa_cache=cache)
    return SimpleNamespace(api=api, db=database, household_id=household_id, policy_id=policy_id, document_id=document_id,
                           models=models, llm=llm, cache=cache)


def fake_workers_succeed():
    from tests import fake_workers

    return fake_workers.succeed


def _ask(world: SimpleNamespace, question: str = "What is the room rent limit?") -> dict:
    response = world.api.post(f"/policies/{world.policy_id}/questions", json={"question": question})
    assert response.status_code == 202, response.text
    world.api.finish_jobs()
    job = world.api.get(f"/jobs/{response.json()['job_id']}").json()
    return job


def test_a_question_is_a_job_whose_result_has_the_contract_shape(world: SimpleNamespace) -> None:
    response = world.api.post(f"/policies/{world.policy_id}/questions", json={"question": "What is the room rent limit?"})

    assert response.status_code == 202
    assert set(response.json()) == {"job_id", "kind", "status"}
    assert response.json()["kind"] == "answer_question" and response.json()["status"] == "queued"

    world.api.finish_jobs()
    job = world.api.get(f"/jobs/{response.json()['job_id']}").json()
    assert job["status"] == "succeeded" and job["progress"] == {"step": "done", "percent": 100}
    result = job["result"]
    assert set(result) == RESULT_KEYS
    assert result["abstained"] is False and result["missing_context"] is None
    assert result["verification"] == {"sentences_checked": 1, "sentences_removed": 0}
    assert result["answer"].endswith("[[1]]")
    (citation,) = result["citations"]
    assert set(citation) == {"id", "kind", "label", "provenance", "external_url"}
    assert citation["kind"] == "policy_clause" and citation["label"] == "Page 2" and citation["external_url"] is None
    assert citation["provenance"]["document_id"] == str(world.document_id)
    assert citation["provenance"]["page"] == 2 and citation["provenance"]["bbox"] == [0.1, 0.2, 0.8, 0.24]
    assert "Rs 5,000 per day" in citation["provenance"]["snippet"]


def test_the_panel_question_keeps_the_users_own_number(world: SimpleNamespace) -> None:
    def answer(question, clauses):
        room = next(c for c in clauses if "Room rent" in c.text)
        return GeneratedAnswer(abstain=False, sentences=[
            AnswerSentence(text="A ₹12,000/day room is above your room rent limit of Rs 5,000 per day.", chunk_ids=[room.id]),
            AnswerSentence(text="You would pay ₹7,000 a day yourself.", chunk_ids=[room.id]),  # arithmetic: not in the clause
        ])

    world.llm._answer = answer
    world.llm._judge = lambda pairs: [True] * len(pairs)
    result = _ask(world, ROOM_QUESTION)["result"]

    assert "₹12,000/day room is above your room rent limit" in result["answer"]
    assert "7,000" not in result["answer"], "a computed number is removed even though the judge said yes"
    assert result["verification"] == {"sentences_checked": 2, "sentences_removed": 1}


def test_a_sentence_with_a_number_not_in_its_clause_is_removed(world: SimpleNamespace) -> None:
    def answer(question, clauses):
        room = next(c for c in clauses if "Room rent" in c.text)
        return GeneratedAnswer(abstain=False, sentences=[
            AnswerSentence(text="Room rent is covered up to ₹10,000 per day.", chunk_ids=[room.id]),
            AnswerSentence(text="Room rent is covered up to Rs 5,000 per day.", chunk_ids=[room.id]),
        ])

    world.llm._answer = answer
    world.llm._judge = lambda pairs: [True] * len(pairs)
    result = _ask(world)["result"]

    assert "10,000" not in result["answer"] and "Rs 5,000" in result["answer"]
    assert result["verification"]["sentences_removed"] == 1
    removed = world.db.scalar("SELECT verification FROM policy_question WHERE policy_id = :p ORDER BY created_at DESC LIMIT 1", p=world.policy_id)["removed"]
    assert removed[0]["text"].startswith("Room rent is covered up to ₹10,000") and "number" in removed[0]["reason"]
    assert world.llm.calls.count("judge") == 1, "one judge call for all pairs"


def test_nothing_supported_is_an_abstention_with_our_own_words(world: SimpleNamespace) -> None:
    world.llm._judge = lambda pairs: [False] * len(pairs)

    result = _ask(world)["result"]

    assert result["abstained"] is True and result["answer"] == "" and result["citations"] == []
    assert result["missing_context"] == NOT_CONFIRMED
    assert result["verification"] == {"sentences_checked": 1, "sentences_removed": 1}


def test_a_model_abstention_never_shows_the_models_reason(world: SimpleNamespace) -> None:
    world.llm._answer = lambda q, c: GeneratedAnswer(abstain=True, reason="I think maybe it is covered")

    result = _ask(world, "Is space travel covered?")["result"]

    assert result["abstained"] is True and result["missing_context"] == NOT_ANSWERED
    assert "maybe" not in str(result)


def test_a_cache_hit_makes_no_model_call_of_any_kind(world: SimpleNamespace) -> None:
    first = _ask(world, "What is the room rent limit?")["result"]
    world.llm.forbid_calls = True
    world.models.calls.clear()

    second = _ask(world, "  what is the ROOM rent   limit?")  # same question, normalised

    assert second["status"] == "succeeded", second["error"]
    assert second["result"] == first
    assert world.models.calls == [], "no embedding or reranking either"
    hits = world.db.execute("SELECT cache_hit FROM policy_question WHERE policy_id = :p ORDER BY created_at", p=world.policy_id)
    assert [row.cache_hit for row in hits] == [False, True]


def test_hindi_question_is_rewritten_for_search_only_and_stored_as_asked(world: SimpleNamespace) -> None:
    question = "अगर मैं ₹१२,००० प्रति दिन का कमरा लूँ तो क्या होगा?"

    job = _ask(world, question)

    assert job["status"] == "succeeded"
    row = world.db.execute("SELECT question, script, search_query FROM policy_question WHERE policy_id = :p ORDER BY created_at DESC LIMIT 1", p=world.policy_id)[0]
    assert row.question == question and row.script == "devanagari"
    assert row.search_query == "room rent limit per day"
    assert world.llm.calls.count("rewrite") == 1
    assert "12,000" in (world.llm.last_answer_question or ""), "the answer model sees the original question, digits made ASCII"


def test_retrieval_never_returns_another_households_clauses(world: SimpleNamespace) -> None:
    other_household = world.db.create_household()
    _, other_document = _make_policy(world.db, other_household)

    async def search(household_id, document_id):
        async with world.db.session_factory() as session:
            return await retrieve(session, FakeModels(), household_id=household_id, document_id=document_id, query="room rent")

    mine = run(search(world.household_id, world.document_id))
    crossed = run(search(world.household_id, other_document))

    assert mine.clauses and all(isinstance(c.id, UUID) for c in mine.clauses)
    assert crossed.clauses == [], "a document of another household returns nothing, even with its id"


def test_another_households_policy_is_404(world: SimpleNamespace) -> None:
    with world.api.acting_as(world.db.create_household()):
        response = world.api.post(f"/policies/{world.policy_id}/questions", json={"question": "Room rent?"})

    assert response.status_code == 404 and set(response.json()) == {"error"}


def test_an_unindexed_policy_is_409(world: SimpleNamespace) -> None:
    policy_id, _ = _make_policy(world.db, world.household_id, indexed=False)

    response = world.api.post(f"/policies/{policy_id}/questions", json={"question": "Room rent?"})

    assert response.status_code == 409 and response.json()["error"]["code"] == "policy_not_indexed"


@pytest.mark.parametrize("question", ["", "   ", "x" * 501])
def test_a_bad_question_is_422(world: SimpleNamespace, question: str) -> None:
    response = world.api.post(f"/policies/{world.policy_id}/questions", json={"question": question})

    assert response.status_code == 422 and response.json()["error"]["field_errors"][0]["field"].endswith("question")


def test_model_server_down_fails_the_job_readably(world: SimpleNamespace) -> None:
    world.models.fail = True

    job = _ask(world)

    assert job["status"] == "failed" and job["error"] == MODELS_UNAVAILABLE


def test_gemini_failure_fails_the_job_readably(world: SimpleNamespace) -> None:
    from app.qa.llm import LlmError

    def broken(question, clauses):
        raise LlmError("quota")

    world.llm._answer = broken
    job = _ask(world)

    assert job["status"] == "failed" and job["error"] == LLM_UNAVAILABLE


def test_an_answer_citing_an_unknown_clause_fails_rather_than_being_trusted(world: SimpleNamespace) -> None:
    world.llm._answer = lambda q, c: GeneratedAnswer(abstain=False, sentences=[AnswerSentence(text="Covered.", chunk_ids=["c99"])])

    job = _ask(world)

    assert job["status"] == "failed" and job["error"] == LLM_UNAVAILABLE


def test_parse_job_indexes_the_new_policy(world: SimpleNamespace) -> None:
    from tests import fake_workers

    world.api.use_worker(fake_workers.succeed, models=FakeModels(), qa_llm=world.llm, qa_cache=world.cache)
    parsed = world.api.upload_and_parse()

    counts = world.db.execute(
        "SELECT count(*) AS total, count(embedding) AS indexed FROM document_chunk WHERE document_id = :d", d=parsed["result"]["document_id"]
    )[0]
    assert counts.total > 0 and counts.indexed == counts.total


def test_parse_without_models_still_succeeds_and_questions_wait_for_indexing(world: SimpleNamespace) -> None:
    from tests import fake_workers

    world.api.use_worker(fake_workers.succeed)
    parsed = world.api.upload_and_parse()

    assert parsed["status"] == "succeeded"
    response = world.api.post(f"/policies/{parsed["result"]["policy_id"]}/questions", json={"question": "Room rent?"})
    assert response.status_code == 409


def test_indexing_failure_does_not_fail_the_parse_and_is_recorded(world: SimpleNamespace) -> None:
    from tests import fake_workers

    world.api.use_worker(fake_workers.succeed, models=FakeModels(fail=True), qa_llm=world.llm, qa_cache=world.cache)
    parsed = world.api.upload_and_parse()

    assert parsed["status"] == "succeeded"
    warnings = world.db.scalar("SELECT warnings FROM document WHERE id = :d", d=parsed["result"]["document_id"])
    assert any("Not indexed for questions yet" in w for w in warnings)
