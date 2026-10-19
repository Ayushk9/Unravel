"""Stand-ins for the warm model server and for Gemini, so Q&A tests download nothing and call no API.

FakeModels      embed/rerank by word overlap: deterministic, and good enough that
                the clause about "room rent" is found for a question about room rent.
FakeQaLlm       answers, judges and rewrites with functions a test can replace,
                and records every call. A test that must prove "no model call
                happened" sets forbid_calls=True; any call then fails the test.
"""

from __future__ import annotations

import math
import re
import zlib
from collections.abc import Callable

from app.models_server.client import ModelServerError
from app.qa.llm import Answered, AnswerSentence, ClausePrompt, GeneratedAnswer
from engines.retrieval.quantities import missing_numbers

DIMENSIONS = 1024


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2]


class FakeModels:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append("embed")
        if self.fail:
            raise ModelServerError("fake model server is down")
        vectors = []
        for text in texts:
            vector = [0.0] * DIMENSIONS
            for word in words(text) or ["empty"]:
                vector[zlib.crc32(word.encode()) % DIMENSIONS] += 1.0
            norm = math.sqrt(sum(v * v for v in vector))
            vectors.append([v / norm for v in vector])
        return vectors

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        self.calls.append("rerank")
        if self.fail:
            raise ModelServerError("fake model server is down")
        asked = set(words(query))
        return [len(asked & set(words(p))) / (len(asked) or 1) for p in passages]


def answer_from_best_clause(question: str, clauses: list[ClausePrompt]) -> GeneratedAnswer:
    """The default fake answer: quote the clause sharing most words with the question."""
    asked = set(words(question))
    best = max(clauses, key=lambda c: len(asked & set(words(c.text))))
    return GeneratedAnswer(abstain=False, sentences=[AnswerSentence(text=f"Your policy says: {best.text}.", chunk_ids=[best.id])])


def judge_by_numbers_and_words(pairs: list[tuple[str, ClausePrompt]]) -> list[bool]:
    """The default fake judge: supported when the clause has the sentence's numbers and most of its words."""
    verdicts = []
    for sentence, clause in pairs:
        said, written = set(words(sentence)), set(words(clause.text))
        verdicts.append(not missing_numbers(sentence, [clause.text]) and len(said & written) >= len(said) // 2)
    return verdicts


class FakeQaLlm:
    def __init__(
        self,
        *,
        answer: Callable[[str, list[ClausePrompt]], GeneratedAnswer] = answer_from_best_clause,
        judge: Callable[[list[tuple[str, ClausePrompt]]], list[bool]] = judge_by_numbers_and_words,
        rewrite: Callable[[str], str] = lambda question: "room rent limit per day",
        forbid_calls: bool = False,
    ) -> None:
        self._answer, self._judge, self._rewrite = answer, judge, rewrite
        self.forbid_calls = forbid_calls
        self.calls: list[str] = []
        self.last_answer_question: str | None = None

    def _record(self, name: str) -> None:
        if self.forbid_calls:
            raise AssertionError(f"a Gemini call ({name}) was made when none was allowed")
        self.calls.append(name)

    model = "fake-model"

    async def rewrite(self, question: str) -> Answered[str]:
        self._record("rewrite")
        return Answered(self._rewrite(question), self.model)

    async def answer(self, question: str, clauses: list[ClausePrompt]) -> Answered[GeneratedAnswer]:
        self._record("answer")
        self.last_answer_question = question
        return Answered(self._answer(question, clauses), self.model)

    async def judge(self, pairs: list[tuple[str, ClausePrompt]]) -> Answered[list[bool]]:
        self._record("judge")
        return Answered(self._judge(pairs), self.model)
