"""The three Gemini calls a question can need, each under a strict JSON schema.

    rewrite   a Hindi or Marathi question -> English search terms (retrieval only)
    answer    the question + 5 clauses   -> sentences, each citing clause ids, or an abstention
    judge     (sentence, clause) pairs   -> supported / unsupported, one verdict per pair

The model does language only. It never decides what the user is shown: the
answer's sentences pass through the number check and the judge's verdicts
(engines/retrieval/verify.py) before anything is sent.

`response_schema` constrains the model's output to the shape below, so it
cannot answer in free prose. The parsed result is then validated again with
Pydantic: an answer citing a clause id it was never given is rejected, not
trusted.

QaLlm is the interface the pipeline uses. Tests pass a fake that records
every call; that is how "a cache hit makes no Gemini call" is proved.
"""

from __future__ import annotations

import asyncio
from typing import Literal, Protocol

from pydantic import BaseModel, Field

# Bump when any prompt or schema below changes. It is part of every cache key,
# so old cached answers are not served for a new prompt.
PROMPT_VERSION = "qa-v1"


class SearchTerms(BaseModel):
    search_terms: str = Field(min_length=1, max_length=300)


class AnswerSentence(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    chunk_ids: list[str] = Field(min_length=1, max_length=5)


class GeneratedAnswer(BaseModel):
    # One object with an `abstain` flag rather than a union of two shapes:
    # Gemini's schema support for "one of these objects" is unreliable, and
    # the two cases are checked in code (generated_answer_problems).
    abstain: bool
    reason: str | None = None
    sentences: list[AnswerSentence] = Field(default_factory=list, max_length=8)


class Verdict(BaseModel):
    pair: int
    verdict: Literal["supported", "unsupported"]


class Verdicts(BaseModel):
    verdicts: list[Verdict]


class ClausePrompt(BaseModel):
    """A clause as the model sees it: a short id (never a UUID), its page and its text."""

    id: str
    page: int
    text: str


class LlmError(Exception):
    """The model call failed, timed out or broke its schema. The message is for the log."""


class QaLlm(Protocol):
    async def rewrite(self, question: str) -> str: ...

    async def answer(self, question: str, clauses: list[ClausePrompt]) -> GeneratedAnswer: ...

    async def judge(self, pairs: list[tuple[str, ClausePrompt]]) -> list[bool]: ...


REWRITE_PROMPT = """The question below is about an Indian health-insurance policy and is written in Hindi or Marathi.
Rewrite it as short English search terms that would find the relevant clause in an English policy document.
Keep every number exactly as written. Do not answer the question. Do not add facts.
"""

ANSWER_PROMPT = """You answer a policyholder's question using ONLY the policy clauses given below.

Rules:
- Every sentence must be supported by the clause(s) it cites. Cite clauses by their id (c1, c2, ...).
- State nothing that is not written in the cited clauses. Do not use general knowledge about insurance.
- Do not do arithmetic. Do not compute differences, totals or proportions. You may repeat a number from the question.
- Write numbers as digits, exactly as they appear in the clause (for example "Rs 5,000", "48 months").
- One claim per sentence. At most 5 sentences. Plain English, even if the question is in another language.
- Do not give legal advice and do not promise an outcome.
- If the clauses do not answer the question, set "abstain" to true, give a short reason, and return no sentences.
"""

JUDGE_PROMPT = """You check an answer about an insurance policy against the policy's own text.
For each numbered pair, decide whether the CLAUSE, on its own, supports the SENTENCE.
"supported" means everything the sentence states is stated in the clause, including every number.
"unsupported" means the clause does not say it, says something different, or only partly supports it.
Judge each pair independently. Do not use outside knowledge.
"""


def generated_answer_problems(answer: GeneratedAnswer, clause_ids: set[str]) -> str | None:
    """Why a parsed answer can't be used, or None if it is well formed."""
    if answer.abstain:
        return "abstained but also gave sentences" if answer.sentences else None
    if not answer.sentences:
        return "did not abstain but gave no sentences"
    unknown = {cid for s in answer.sentences for cid in s.chunk_ids} - clause_ids
    if unknown:
        return f"cited clause ids it was not given: {sorted(unknown)}"
    return None


class GeminiQaLlm:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: float) -> None:
        # Imported here so that importing this module (tests, type checks) does not need the SDK.
        from google import genai
        from google.genai import types

        self._types = types
        self._model = model
        self._timeout = timeout_seconds
        self._client = genai.Client(
            api_key=api_key, http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=3))
        )

    async def _generate(self, contents: list[str], schema: type[BaseModel]) -> BaseModel:
        config = self._types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema, temperature=0.0)
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(model=self._model, contents=contents, config=config), self._timeout
            )
        except TimeoutError as exc:
            raise LlmError(f"Gemini did not answer within {self._timeout}s") from exc
        except Exception as exc:  # noqa: BLE001 - network, quota and API errors all become one readable failure
            raise LlmError(f"Gemini call failed: {type(exc).__name__}: {exc}") from exc
        if response.parsed is None:
            raise LlmError("Gemini's answer did not match the required schema")
        return schema.model_validate(response.parsed)

    async def rewrite(self, question: str) -> str:
        result = await self._generate([REWRITE_PROMPT, f"QUESTION: {question}"], SearchTerms)
        assert isinstance(result, SearchTerms)
        return result.search_terms

    async def answer(self, question: str, clauses: list[ClausePrompt]) -> GeneratedAnswer:
        listing = "\n\n".join(f"[{c.id}] (page {c.page})\n{c.text}" for c in clauses)
        result = await self._generate([ANSWER_PROMPT, f"CLAUSES:\n{listing}", f"QUESTION: {question}"], GeneratedAnswer)
        assert isinstance(result, GeneratedAnswer)
        return result

    async def judge(self, pairs: list[tuple[str, ClausePrompt]]) -> list[bool]:
        """One call for all pairs, one verdict per pair. A pair the model leaves out counts as unsupported."""
        if not pairs:
            return []
        listing = "\n\n".join(f"PAIR {i}\nSENTENCE: {sentence}\nCLAUSE (page {clause.page}): {clause.text}" for i, (sentence, clause) in enumerate(pairs))
        result = await self._generate([JUDGE_PROMPT, listing], Verdicts)
        assert isinstance(result, Verdicts)
        supported = {v.pair for v in result.verdicts if v.verdict == "supported"}
        return [i in supported for i in range(len(pairs))]
