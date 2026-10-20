"""An answer is cached only under the model that wrote it (the open Phase 6 bug).

The cache key names the primary model (GEMINI_MODEL). An answer for which any
call fell back to GEMINI_FALLBACK_MODEL must not be stored under that key, or
a later asking would be served the fallback's answer as if the primary wrote
it. Retrieval is replaced by a stub, so no database is needed.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from app.core.ids import new_id
from app.qa import run_question
from app.qa.cache import QaCache, answer_key, rewrite_key
from app.qa.llm import PROMPT_VERSION, Answered
from app.qa.retrieval import Clause, Retrieved
from engines.retrieval.language import normalise_question
from tests.fake_models import FakeQaLlm

PRIMARY = "primary-model"
FALLBACK = "fallback-model"
QUESTION = "What is the room rent limit?"
HINDI = "कमरे का किराया कितना है?"


class FallsBackOn(FakeQaLlm):
    """The fake Gemini, except the named calls report that the fallback model answered."""

    def __init__(self, *calls: str) -> None:
        super().__init__()
        self.model = PRIMARY
        self._fallback_calls = set(calls)

    async def rewrite(self, question: str) -> Answered[str]:
        return self._as(await super().rewrite(question), "rewrite")

    async def answer(self, question, clauses):  # type: ignore[no-untyped-def]
        return self._as(await super().answer(question, clauses), "answer")

    async def judge(self, pairs):  # type: ignore[no-untyped-def]
        return self._as(await super().judge(pairs), "judge")

    def _as(self, answered: Answered[Any], call: str) -> Answered[Any]:
        return Answered(answered.value, FALLBACK) if call in self._fallback_calls else answered


@pytest.fixture(autouse=True)
def stub_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    clause = Clause(id=new_id(), page=2, position=0, text="Room rent is limited to Rs 5,000 per day.", bbox=[0.1, 0.2, 0.6, 0.25])

    async def retrieve(*_: Any, **__: Any) -> Retrieved:
        return Retrieved(clauses=[clause])

    monkeypatch.setattr(run_question, "retrieve", retrieve)


@asynccontextmanager
async def no_session():  # type: ignore[no-untyped-def]
    yield None


def _ask(cache: QaCache, llm: FakeQaLlm, document_id: UUID, question: str = QUESTION) -> run_question.AnswerOutcome:
    return asyncio.run(
        run_question.answer_question(
            session_factory=no_session, models=None, llm=llm, cache=cache, gemini_model=PRIMARY,  # type: ignore[arg-type]
            household_id=new_id(), document_id=document_id, document_hash="sha", question=question,
        )
    )


def _key(document_id: UUID, question: str = QUESTION) -> str:
    return answer_key(str(document_id), "sha", normalise_question(question), PROMPT_VERSION, PRIMARY)


def test_a_primary_answer_is_cached_under_the_primary_key(tmp_path: Path) -> None:
    cache, document_id = QaCache(tmp_path), new_id()

    outcome = _ask(cache, FallsBackOn(), document_id)

    assert outcome.result["abstained"] is False
    assert cache.get(_key(document_id))["models"] == {"answer": PRIMARY, "judge": PRIMARY}


@pytest.mark.parametrize("fell_back", ["answer", "judge"])
def test_an_answer_that_used_the_fallback_is_not_cached(tmp_path: Path, fell_back: str) -> None:
    cache, document_id = QaCache(tmp_path), new_id()

    first = _ask(cache, FallsBackOn(fell_back), document_id)

    assert first.record["models"][fell_back] == FALLBACK
    assert cache.get(_key(document_id)) is None
    assert list(tmp_path.iterdir()) == [], "not stored under any key"
    # The next asking is a miss, so the primary gets to answer it.
    again = FallsBackOn()
    second = _ask(cache, again, document_id)
    assert second.cache_hit is False and "answer" in again.calls


def test_a_rewrite_by_the_fallback_is_not_cached(tmp_path: Path) -> None:
    cache = QaCache(tmp_path)

    _ask(cache, FallsBackOn("rewrite"), new_id(), HINDI)

    assert cache.get(rewrite_key(normalise_question(HINDI), PROMPT_VERSION, PRIMARY)) is None
