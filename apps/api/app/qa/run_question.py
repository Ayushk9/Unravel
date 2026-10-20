"""The `answer_question` job: one question about one policy, from text to verified answer.

Stages, each written to job.progress (D-42):

    retrieving   (rewrite a Hindi/Marathi question into English search terms,)
                 embed, dense + keyword search, fuse, rerank, keep 5 clauses
    generating   Gemini writes sentences, each citing clause ids, or abstains
    verifying    the number check, then the support judge, then assembly
    done

What the user receives is built only from sentences that passed
verification (engines/retrieval/verify.py). Nothing the model wrote reaches
them otherwise: not its abstention reason, not a removed sentence.

The original question is stored as asked (policy_question). The English
rewrite is used for retrieval only; the answer model sees the original.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from app.db.models import Document, Job, Policy, PolicyQuestion
from app.jobs.parse_document import JobFailure
from app.jobs.queue import ClaimedJob, SessionFactory, set_progress
from app.models_server.client import Models, ModelServerError
from app.qa.cache import QaCache, answer_key, rewrite_key
from app.qa.llm import PROMPT_VERSION, ClausePrompt, LlmError, QaLlm, generated_answer_problems
from app.qa.retrieval import Clause, retrieve
from engines.retrieval.language import ascii_digits, has_devanagari, normalise_question
from engines.retrieval.verify import Sentence, assemble, decide, precheck

logger = logging.getLogger("unravel.qa")

RETRIEVING = ("retrieving", 20)
GENERATING = ("generating", 50)
VERIFYING = ("verifying", 80)

SNIPPET_CHARACTERS = 200

# Fixed sentences, never model text: an abstention is the system's statement, not the model's.
NOTHING_FOUND = "We couldn't find anything in your policy's text about this. The clause may be in a document you haven't uploaded."
NOT_ANSWERED = "Your policy's text that we searched doesn't answer this. The clause may be in a document you haven't uploaded."
NOT_CONFIRMED = "We couldn't confirm an answer to this in your policy's text, so we aren't showing one."

MODELS_UNAVAILABLE = "The search models aren't available right now. Please try again in a moment."
LLM_UNAVAILABLE = "We couldn't get an answer right now. Please try again in a moment."
LLM_BUSY = "The answering service is busy right now. Please try again in a minute."


def _abstention(missing_context: str, checked: int = 0, removed: int = 0) -> dict[str, Any]:
    return {
        "answer": "",
        "citations": [],
        "abstained": True,
        "missing_context": missing_context,
        "verification": {"sentences_checked": checked, "sentences_removed": removed},
    }


def _citation(clause: Clause, document_id: UUID) -> dict[str, Any]:
    return {
        "id": str(clause.id),
        "kind": "policy_clause",
        "label": f"Page {clause.page}",
        "provenance": {
            "document_id": str(document_id),
            "page": clause.page,
            "bbox": clause.bbox,
            "snippet": " ".join(clause.text.split())[:SNIPPET_CHARACTERS],
        },
        "external_url": None,
    }


@dataclass
class AnswerOutcome:
    result: dict[str, Any]
    cache_hit: bool
    timings: dict[str, float]
    # For policy_question: script, search_query, retrieved, generated, verification.
    record: dict[str, Any]


def written_only_by(models: dict[str, str], primary: str) -> bool:
    """True when every model call behind an answer was made by `primary` (or no call was made)."""
    return all(model == primary for model in models.values())


Progress = Callable[[tuple[str, int]], Awaitable[None]]


async def _no_progress(_: tuple[str, int]) -> None:
    return None


async def answer_question(
    *,
    session_factory: SessionFactory,
    models: Models,
    llm: QaLlm,
    cache: QaCache,
    gemini_model: str,
    household_id: UUID,
    document_id: UUID,
    document_hash: str,
    question: str,
    progress: Progress = _no_progress,
) -> AnswerOutcome:
    """The whole pipeline for one question, with no job attached. The job below and scripts/evaluate_qa.py both call it.

    Raises ModelServerError or LlmError when a model can't answer.
    """
    started = time.perf_counter()
    timings: dict[str, float] = {}
    script = "devanagari" if has_devanagari(question) else "latin"
    normalised = normalise_question(question)
    key = answer_key(str(document_id), document_hash, normalised, PROMPT_VERSION, gemini_model)
    record: dict[str, Any] = {
        "script": script, "search_query": None, "retrieved": None, "generated": None, "verification": None,
        # Which model actually answered each call: the primary, or the fallback (app/qa/llm.py).
        "models": {},
    }

    cached = cache.get(key)
    # A cache entry is {"result": ..., "models": ...}. Anything else is an older format: a miss.
    if isinstance(cached, dict) and "result" in cached:
        record["models"] = cached.get("models") or {}
        timings["total"] = round(time.perf_counter() - started, 3)
        return AnswerOutcome(result=cached["result"], cache_hit=True, timings=timings, record=record)

    result = await _answer(
        session_factory, models, llm, cache, gemini_model, household_id, question, normalised, script, document_id, timings, record, progress
    )
    # The key names the primary model, so only an answer the primary wrote may be stored under it.
    # An answer that needed the fallback for any call is not cached: the next asking tries the primary again.
    if written_only_by(record["models"], gemini_model):
        # The models that answered are stored with the answer, so a cache hit still says who wrote it.
        cache.set(key, {"result": result, "models": record["models"]})
    timings["total"] = round(time.perf_counter() - started, 3)
    return AnswerOutcome(result=result, cache_hit=False, timings=timings, record=record)


async def run_answer_question(
    job: ClaimedJob,
    *,
    session_factory: SessionFactory,
    models: Models,
    llm: QaLlm,
    cache: QaCache,
    gemini_model: str,
) -> None:
    policy_id = UUID(job.payload["policy_id"])
    question: str = job.payload["question"]

    async with session_factory() as session:
        policy = await session.scalar(select(Policy).where(Policy.id == policy_id, Policy.household_id == job.household_id))
        document = await session.get(Document, policy.source_document_id) if policy else None
        if policy is None or document is None or document.deleted_at is not None:
            raise JobFailure("policy_missing", "This policy is no longer available.", retryable=False)
        document_id = document.id
        # The file's hash identifies its contents; the id is a fallback for rows made without one (seeded demo data).
        document_hash = document.sha256 or f"document:{document.id}"

    async def progress(step: tuple[str, int]) -> None:
        await set_progress(session_factory, job.id, *step)

    try:
        outcome = await answer_question(
            session_factory=session_factory,
            models=models,
            llm=llm,
            cache=cache,
            gemini_model=gemini_model,
            household_id=job.household_id,
            document_id=document_id,
            document_hash=document_hash,
            question=question,
            progress=progress,
        )
    except ModelServerError as exc:
        raise JobFailure("models_unavailable", MODELS_UNAVAILABLE, retryable=True, detail=str(exc)) from exc
    except LlmError as exc:
        message = LLM_BUSY if exc.code in ("overloaded", "rate_limited", "timeout") else LLM_UNAVAILABLE
        raise JobFailure(f"llm_{exc.code}", message, retryable=exc.retryable, detail=str(exc)) from exc

    await _finish(session_factory, job, policy_id, question, outcome)


async def _answer(
    session_factory: SessionFactory,
    models: Models,
    llm: QaLlm,
    cache: QaCache,
    gemini_model: str,
    household_id: UUID,
    question: str,
    normalised: str,
    script: str,
    document_id: UUID,
    timings: dict[str, float],
    record: dict[str, Any],
    progress: Progress,
) -> dict[str, Any]:
    # Devanagari digits as ASCII everywhere below, so "₹१२,०००" is the number 12,000.
    asked = ascii_digits(question)

    # --- retrieving ---
    await progress(RETRIEVING)
    t = time.perf_counter()
    search_query = asked
    if script == "devanagari":
        rewrite_cache_key = rewrite_key(normalised, PROMPT_VERSION, gemini_model)
        search_query = cache.get(rewrite_cache_key)
        if not isinstance(search_query, str):
            rewritten = await llm.rewrite(asked)
            search_query = rewritten.value
            record["models"]["rewrite"] = rewritten.model
            if rewritten.model == gemini_model:  # same rule as the answer cache: primary-model output only
                cache.set(rewrite_cache_key, search_query)
        timings["rewrite"] = round(time.perf_counter() - t, 3)
    record["search_query"] = search_query

    t = time.perf_counter()
    async with session_factory() as session:
        retrieved = await retrieve(session, models, household_id=household_id, document_id=document_id, query=search_query)
    timings["retrieve_and_rerank"] = round(time.perf_counter() - t, 3)
    timings.update({f"retrieve.{name}": seconds for name, seconds in retrieved.timings.items()})
    record["retrieved"] = retrieved.trace
    if not retrieved.clauses:
        return _abstention(NOTHING_FOUND)

    # Short ids for the model; it never sees (or can invent) a database id.
    by_short_id = {f"c{i}": clause for i, clause in enumerate(retrieved.clauses, start=1)}
    prompts = [ClausePrompt(id=short, page=c.page, text=c.text) for short, c in by_short_id.items()]

    # --- generating ---
    await progress(GENERATING)
    t = time.perf_counter()
    answered = await llm.answer(asked, prompts)
    generated = answered.value
    record["models"]["answer"] = answered.model
    timings["generate"] = round(time.perf_counter() - t, 3)
    record["generated"] = generated.model_dump()
    problem = generated_answer_problems(generated, set(by_short_id))
    if problem:
        raise LlmError(f"unusable answer: {problem}", code="bad_answer", retryable=True)
    if generated.abstain:
        return _abstention(NOT_ANSWERED)

    # --- verifying ---
    await progress(VERIFYING)
    t = time.perf_counter()
    chunk_text = {short: c.text for short, c in by_short_id.items()}
    sentences = [Sentence(s.text, tuple(dict.fromkeys(s.chunk_ids))) for s in generated.sentences]
    candidates, removed_early = precheck(sentences, chunk_text, asked)
    timings["verify.number_check"] = round(time.perf_counter() - t, 4)

    pairs = [(index, chunk_id) for index, s in enumerate(candidates) for chunk_id in s.chunk_ids]
    prompt_by_id = {p.id: p for p in prompts}
    t_judge = time.perf_counter()
    judged_answer = await llm.judge([(candidates[index].text, prompt_by_id[chunk_id]) for index, chunk_id in pairs])
    timings["verify.support_judge"] = round(time.perf_counter() - t_judge, 3)
    if pairs:
        record["models"]["judge"] = judged_answer.model
    verdicts = dict(zip(pairs, judged_answer.value, strict=True))
    t_decide = time.perf_counter()
    outcome = decide(candidates, verdicts, chunk_text, asked, removed_early)
    timings["verify.decide"] = round(time.perf_counter() - t_decide, 4)
    timings["verify"] = round(time.perf_counter() - t, 3)

    record["verification"] = {
        "kept": [{"text": s.text, "chunk_ids": list(s.chunk_ids)} for s in outcome.kept],
        "removed": [{"text": r.sentence.text, "chunk_ids": list(r.sentence.chunk_ids), "reason": r.reason, "detail": r.detail} for r in outcome.removed],
        "judgements": [{"sentence": index, "chunk_id": chunk_id, "supported": ok} for (index, chunk_id), ok in verdicts.items()],
    }
    if not outcome.kept:
        return _abstention(NOT_CONFIRMED, outcome.checked, len(outcome.removed))

    answer_text, order = assemble(outcome.kept)
    return {
        "answer": answer_text,
        "citations": [_citation(by_short_id[short], document_id) for short in order],
        "abstained": False,
        "missing_context": None,
        "verification": {"sentences_checked": outcome.checked, "sentences_removed": len(outcome.removed)},
    }


async def _finish(session_factory: SessionFactory, job: ClaimedJob, policy_id: UUID, question: str, outcome: AnswerOutcome) -> None:
    """The question log row and the job's success, in one transaction."""
    async with session_factory() as session, session.begin():
        job_row = await session.get(Job, job.id, with_for_update=True)
        if job_row is None:
            raise JobFailure("job_missing", "This question is no longer available.", retryable=False)
        session.add(
            PolicyQuestion(
                household_id=job.household_id,
                policy_id=policy_id,
                job_id=job.id,
                question=question,
                cache_hit=outcome.cache_hit,
                result=outcome.result,
                timings=outcome.timings,
                **outcome.record,
            )
        )
        job_row.status = "succeeded"
        job_row.progress = {"step": "done", "percent": 100}
        job_row.result = outcome.result
        job_row.finished_at = func.now()
    result = outcome.result
    logger.info(
        "Answered question. job_id=%s cache_hit=%s abstained=%s checked=%s removed=%s timings=%s",
        job.id,
        outcome.cache_hit,
        result["abstained"],
        result["verification"]["sentences_checked"],
        result["verification"]["sentences_removed"],
        outcome.timings,
    )
