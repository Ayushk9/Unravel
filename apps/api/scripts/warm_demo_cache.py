"""Ask every demo question once, so the answers are cached before demo day.

Run from apps/api (needs the database, the Q&A models and Gemini):
    ../../.venv/bin/python scripts/warm_demo_cache.py [policy_id]          ask and cache
    ../../.venv/bin/python scripts/warm_demo_cache.py --check [policy_id]  prove the cache answers
    ../../.venv/bin/python scripts/warm_demo_cache.py --force "<question>" [policy_id]
                                          ask that question again (only it); its cached answer is replaced
                                          only if the new one may be cached

The policy is the dev household's newest real policy (app/qa/demo_policy.py),
never the synthetic test fixture. Answers go into the same cache the API
uses (apps/api/.cache/qa), under the same key the API computes, so asking one
of these questions in the web app is answered from the cache, with no model
call. Entries last 24 hours (D-42): run this on the morning of the demo.

Only an answer written entirely by the PRIMARY model (GEMINI_MODEL) is cached,
and never an abstention. A demo answer is pinned for 24 hours, so it must be
the one the primary model gives; an answer from the fallback model, or an
abstention, is reported and left out (run the script again later). An entry
already in the cache that breaks either rule is reported and removed, then the
question is asked again.

Each question gets up to QUESTION_TIMEOUT_SECONDS (300 s), and so does each
Gemini call within it: Gemini is slow when overloaded, and a warm-up can wait.
The live app keeps its own, shorter limit (QA_LLM_TIMEOUT_SECONDS).

For every answer, the sentences verification removed are printed with the
reason: the number check (a number not in the cited clause) or the judge (no
cited clause supports it). They are never cached or shown to a user.

--check runs each question through the real job code (run_answer_question)
with a Gemini stand-in and a model-server stand-in that FAIL if called. A
question passes only if its job succeeds from the cache alone.

A question matches its cached answer after normalisation (case, spacing,
Devanagari digits), so type them as written here, give or take spacing.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.ids import new_id  # noqa: E402
from app.db.models import Document, Job, PolicyQuestion  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.jobs.queue import ClaimedJob  # noqa: E402
from app.models_server.client import ModelServer, ModelServerError  # noqa: E402
from app.qa.cache import QaCache, answer_key  # noqa: E402
from app.qa.demo_policy import find_real_policy  # noqa: E402
from app.qa.llm import PROMPT_VERSION, GeminiQaLlm, LlmError  # noqa: E402
from app.qa.run_question import answer_question, run_answer_question  # noqa: E402
from engines.retrieval.language import normalise_question  # noqa: E402
from engines.retrieval.verify import NUMBER_REASON, SUPPORT_REASON  # noqa: E402

# The warm-up's own limits; the live app's come from settings and are not changed here.
QUESTION_TIMEOUT_SECONDS = 300
REASON_NAMES = {NUMBER_REASON: "number check", SUPPORT_REASON: "judge"}

DEMO_QUESTIONS = [
    "What if I choose a ₹12,000/day room?",
    "अगर मैं ₹१२,००० प्रति दिन का कमरा लूँ तो क्या होगा?",
    "How long is the waiting period for pre-existing diseases?",
    "Is cosmetic surgery covered?",
    "How soon must I inform the insurer after an emergency hospitalisation?",
]


class HeldCache:
    """The API cache for reading; writes are held until the script decides to keep them.

    answer_question writes its answer (and a Hindi question's English rewrite)
    to the cache itself. The script needs to see who answered first, so the
    writes are held here and only committed by keep(). With --force, the
    question's own answer is hidden from reads (`hide`), so it is asked again.
    """

    def __init__(self, cache: QaCache, hide: str | None = None) -> None:
        self._cache = cache
        self._hide = hide
        self._held: list[tuple[str, object]] = []

    def get(self, key: str):
        return None if key == self._hide else self._cache.get(key)

    def set(self, key: str, value: object) -> None:
        self._held.append((key, value))

    def keep(self) -> None:
        for key, value in self._held:
            self._cache.set(key, value)
        self._held.clear()


def not_cacheable(result: dict, models: dict[str, str], primary: str) -> str | None:
    """Why an answer must not be cached for the demo, or None if it may be."""
    others = sorted({model for model in models.values() if model != primary})
    if others:
        return f"answered by {', '.join(others)}, not the primary {primary}"
    if result["abstained"]:
        return "abstained"
    return None


def print_removed(record: dict) -> None:
    """The sentences verification removed from this answer, each with why."""
    removed = (record.get("verification") or {}).get("removed") or []
    if not removed:
        print("      removed by verification: none")
        return
    print(f"      removed by verification: {len(removed)}")
    for item in removed:
        detail = f" (missing: {item['detail']})" if item.get("detail") else ""
        print(f"        - [{REASON_NAMES.get(item['reason'], item['reason'])}{detail}] {item['text']}")


class NoCallsAllowed:
    """Stands in for Gemini and the model server in --check: any call is a failure."""

    def __getattr__(self, name: str):
        async def refuse(*_args, **_kwargs):
            raise AssertionError(f"{name} was called, so this question was NOT answered from the cache")

        return refuse


async def main(policy_arg: str | None, check: bool, force: str | None) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    cache = QaCache()  # the API's own cache directory
    async with session_factory() as session:
        policy = await find_real_policy(session, UUID(policy_arg) if policy_arg else None)
        document = await session.get(Document, policy.source_document_id)
    document_hash = document.sha256 or f"document:{document.id}"
    print(f"policy {policy.id}, document {document.id} ({document.file_name})")

    if check:
        refuse = NoCallsAllowed()
        failures = 0
        for question in DEMO_QUESTIONS:
            job_id = new_id()
            async with session_factory() as session, session.begin():
                session.add(Job(id=job_id, household_id=policy.household_id, kind="answer_question", status="running",
                                payload={"policy_id": str(policy.id), "question": question}))
            try:
                await run_answer_question(
                    ClaimedJob(id=job_id, household_id=policy.household_id, kind="answer_question",
                               payload={"policy_id": str(policy.id), "question": question}),
                    session_factory=session_factory, models=refuse, llm=refuse, cache=cache, gemini_model=settings.gemini_model,
                )
                async with session_factory() as session:
                    row = await session.scalar(select(PolicyQuestion).where(PolicyQuestion.job_id == job_id))
                    job = await session.get(Job, job_id)
                print(f"  OK   job {job.status}, cache_hit={row.cache_hit}, total {row.timings['total'] * 1000:.0f} ms, "
                      f"answered earlier by {row.models}: {question}")
            except AssertionError as error:
                failures += 1
                print(f"  FAIL {error}: {question}")
        await engine.dispose()
        raise SystemExit(1 if failures else 0)

    server = ModelServer(embed_model=settings.embedding_model, rerank_model=settings.rerank_model, device=settings.model_device,
                         load_timeout_seconds=settings.model_load_timeout_seconds, request_timeout_seconds=settings.model_request_timeout_seconds)
    server.start()
    llm = GeminiQaLlm(api_key=settings.gemini_api_key, model=settings.gemini_model, fallback_model=settings.gemini_fallback_model,
                      timeout_seconds=QUESTION_TIMEOUT_SECONDS)
    primary = settings.gemini_model
    abstained = []
    try:
        for question in [force] if force else DEMO_QUESTIONS:
            key = answer_key(str(document.id), document_hash, normalise_question(question), PROMPT_VERSION, primary)
            # --force ignores the cached answer and asks again. The old entry is replaced only
            # by a new one that may be cached, so a timeout the night before never leaves a gap.
            existing = None if force else cache.get(key)
            if isinstance(existing, dict) and "result" in existing:
                reason = not_cacheable(existing["result"], existing.get("models") or {}, primary)
                if reason is None:
                    print(f"  already cached: {question}")
                    continue
                print(f"  REMOVED cached entry ({reason}): {question}")
                cache.delete(key)
            held = HeldCache(cache, hide=key if force else None)
            kept_note = " The earlier cached answer, if any, is kept." if force else ""
            try:
                outcome = await asyncio.wait_for(
                    answer_question(
                        session_factory=session_factory, models=server, llm=llm, cache=held, gemini_model=primary,
                        household_id=policy.household_id, document_id=document.id, document_hash=document_hash, question=question,
                    ),
                    QUESTION_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                print(f"  NOT cached (no answer within {QUESTION_TIMEOUT_SECONDS}s): {question}.{kept_note}")
                continue
            except (LlmError, ModelServerError) as error:
                # Not cached; run the script again later to fill it in.
                print(f"  NOT cached ({getattr(error, 'code', 'models')}): {question}.{kept_note}")
                continue
            result = outcome.result
            reason = not_cacheable(result, outcome.record["models"], primary)
            if reason is None:
                held.keep()
                print(f"  cached ({outcome.timings['total']:.1f}s, by {outcome.record['models']}): {question}")
            else:
                print(f"  NOT cached ({reason}): {question}.{kept_note}")
                if result["abstained"]:
                    abstained.append(question)
            print(f"      abstained={result['abstained']} verification={result['verification']}")
            print(f"      {result['answer'] or result['missing_context']}")
            print(f"      citations: {[c['label'] for c in result['citations']]}")
            print_removed(outcome.record)
        if abstained:
            print(f"\n{len(abstained)} demo question(s) ABSTAINED and were not cached:")
            for question in abstained:
                print(f"  - {question}")
    finally:
        await server.stop()
        await engine.dispose()


if __name__ == "__main__":
    args = sys.argv[1:]
    force = None
    if "--force" in args:
        at = args.index("--force")
        if at + 1 >= len(args):
            raise SystemExit('--force needs the question, in quotes: --force "Is cosmetic surgery covered?"')
        force = args[at + 1]
        del args[at:at + 2]
    check = "--check" in args
    args = [a for a in args if a != "--check"]
    if check and force:
        raise SystemExit("--check and --force do not go together.")
    asyncio.run(main(args[0] if args else None, check, force))
