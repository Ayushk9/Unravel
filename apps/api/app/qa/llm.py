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
import logging
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field

logger = logging.getLogger("unravel.qa")
T = TypeVar("T")

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
    """The model call failed, timed out or broke its schema. str(error) is for the log.

    `code` and `retryable` go to the job row (job.error_code, job.retryable):
      overloaded     503 from Gemini after every retry and the fallback
      rate_limited   429 (quota) after every retry and the fallback
      timeout        no answer within the time limit
      bad_answer     the answer broke its schema; asking again may work
      failed         anything else (a bad key, a retired model): retrying won't help
    """

    def __init__(self, message: str, *, code: str = "failed", retryable: bool = False, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        # Seconds Gemini says to wait before asking again (its RetryInfo), when it says.
        self.retry_after = retry_after


@dataclass(frozen=True)
class Answered(Generic[T]):
    """A model's parsed reply and which model gave it (the primary, or the fallback)."""

    value: T
    model: str


class QaLlm(Protocol):
    async def rewrite(self, question: str) -> Answered[str]: ...

    async def answer(self, question: str, clauses: list[ClausePrompt]) -> Answered[GeneratedAnswer]: ...

    async def judge(self, pairs: list[tuple[str, ClausePrompt]]) -> Answered[list[bool]]: ...


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


# Gemini's "busy" (503) and "quota" (429) answers are often gone seconds later.
RETRYABLE_STATUS = {429: "rate_limited", 503: "overloaded"}
MAX_ATTEMPTS = 4
BACKOFF_BASE_SECONDS = 1.0
BACKOFF_CAP_SECONDS = 8.0
# A 429 for a used-up DAILY quota says "retry in 18h". Waiting seconds for
# that is pointless, so past this the primary is given up at once and the
# fallback is tried straight away.
GIVE_UP_IF_RETRY_AFTER_SECONDS = 60.0
_RETRY_DELAY = re.compile(r"retryDelay'?\"?:\s*'?\"?(\d+(?:\.\d+)?)s")


def retry_after_seconds(error: Exception) -> float | None:
    """Gemini's suggested wait, from the RetryInfo detail in its error, if present."""
    match = _RETRY_DELAY.search(str(error))
    return float(match.group(1)) if match else None


def backoff_seconds(attempt: int, rng: random.Random | None = None) -> float:
    """Exponential backoff with full jitter: a random wait in [0, min(cap, base * 2^attempt)].

    attempt 1 -> up to 2 s, 2 -> up to 4 s, 3 -> up to 8 s. The randomness
    stops several waiting requests from all retrying at the same instant.
    """
    ceiling = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * 2**attempt)
    return (rng or random).uniform(0, ceiling)


class GeminiQaLlm:
    """Gemini, with retries and a fallback model.

    For each call: up to MAX_ATTEMPTS tries on the primary model, waiting
    backoff_seconds() between them, but only after a 503 or 429. If they are
    all used up, the fallback model (GEMINI_FALLBACK_MODEL) gets one try. Any
    other failure (a broken schema, a bad key) is not retried here.

    The SDK's own retries are switched off (attempts=1), so this loop is the
    only one and the attempt count is exactly what is written here.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        fallback_model: str | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        client: Any = None,
    ) -> None:
        # Imported here so that importing this module (tests, type checks) does not need the SDK.
        from google import genai
        from google.genai import types

        self._types = types
        self._model = model
        self._fallback = fallback_model if fallback_model and fallback_model != model else None
        self._timeout = timeout_seconds
        self._sleep = sleep
        self._client = client or genai.Client(
            api_key=api_key, http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1))
        )

    async def _once(self, model: str, contents: list[str], schema: type[BaseModel]) -> BaseModel:
        config = self._types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.0,
            # No tools are ever offered; switch the SDK's tool-calling loop off explicitly.
            automatic_function_calling=self._types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = await asyncio.wait_for(
                self._client.aio.models.generate_content(model=model, contents=contents, config=config), self._timeout
            )
        except TimeoutError as exc:
            raise LlmError(f"{model} did not answer within {self._timeout}s", code="timeout", retryable=True) from exc
        except Exception as exc:  # noqa: BLE001 - classified below; every failure becomes an LlmError
            status = getattr(exc, "code", None)
            if status in RETRYABLE_STATUS:
                raise LlmError(
                    f"{model}: {status} {exc}", code=RETRYABLE_STATUS[status], retryable=True, retry_after=retry_after_seconds(exc)
                ) from exc
            raise LlmError(f"{model} call failed: {type(exc).__name__}: {exc}") from exc
        if response.parsed is None:
            raise LlmError(f"{model}'s answer did not match the required schema", code="bad_answer", retryable=True)
        return schema.model_validate(response.parsed)

    async def _generate(self, contents: list[str], schema: type[BaseModel]) -> tuple[BaseModel, str]:
        last: LlmError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return await self._once(self._model, contents, schema), self._model
            except LlmError as error:
                if error.code not in RETRYABLE_STATUS.values():
                    raise
                last = error
                if error.retry_after is not None and error.retry_after > GIVE_UP_IF_RETRY_AFTER_SECONDS:
                    logger.warning("Gemini quota used up for %ss; not retrying. model=%s", round(error.retry_after), self._model)
                    break
                if attempt < MAX_ATTEMPTS:
                    wait = backoff_seconds(attempt)
                    logger.warning("Gemini busy, retrying. model=%s attempt=%s wait=%.1fs code=%s", self._model, attempt, wait, error.code)
                    await self._sleep(wait)
        assert last is not None
        if self._fallback is None:
            raise last
        logger.warning("Gemini primary exhausted, trying fallback. primary=%s fallback=%s", self._model, self._fallback)
        return await self._once(self._fallback, contents, schema), self._fallback

    async def rewrite(self, question: str) -> Answered[str]:
        result, model = await self._generate([REWRITE_PROMPT, f"QUESTION: {question}"], SearchTerms)
        assert isinstance(result, SearchTerms)
        return Answered(result.search_terms, model)

    async def answer(self, question: str, clauses: list[ClausePrompt]) -> Answered[GeneratedAnswer]:
        listing = "\n\n".join(f"[{c.id}] (page {c.page})\n{c.text}" for c in clauses)
        result, model = await self._generate([ANSWER_PROMPT, f"CLAUSES:\n{listing}", f"QUESTION: {question}"], GeneratedAnswer)
        assert isinstance(result, GeneratedAnswer)
        return Answered(result, model)

    async def judge(self, pairs: list[tuple[str, ClausePrompt]]) -> Answered[list[bool]]:
        """One call for all pairs, one verdict per pair. A pair the model leaves out counts as unsupported."""
        if not pairs:
            return Answered([], self._model)
        listing = "\n\n".join(
            f"PAIR {i}\nSENTENCE: {sentence}\nCLAUSE (page {clause.page}): {clause.text}" for i, (sentence, clause) in enumerate(pairs)
        )
        result, model = await self._generate([JUDGE_PROMPT, listing], Verdicts)
        assert isinstance(result, Verdicts)
        supported = {v.pair for v in result.verdicts if v.verdict == "supported"}
        return Answered([i in supported for i in range(len(pairs))], model)
