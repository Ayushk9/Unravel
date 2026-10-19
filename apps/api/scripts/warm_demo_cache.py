"""Ask every demo question once, so the answers are cached before demo day.

Run from apps/api (needs the database, the Q&A models and Gemini):
    ../../.venv/bin/python scripts/warm_demo_cache.py [policy_id]          ask and cache
    ../../.venv/bin/python scripts/warm_demo_cache.py --check [policy_id]  prove the cache answers

The policy is the dev household's newest real policy (app/qa/demo_policy.py),
never the synthetic test fixture. Answers go into the same cache the API
uses (apps/api/.cache/qa), under the same key the API computes, so asking one
of these questions in the web app is answered from the cache, with no model
call. Entries last 24 hours (D-42): run this on the morning of the demo.

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

DEMO_QUESTIONS = [
    "What if I choose a ₹12,000/day room?",
    "अगर मैं ₹१२,००० प्रति दिन का कमरा लूँ तो क्या होगा?",
    "How long is the waiting period for pre-existing diseases?",
    "Is cosmetic surgery covered?",
    "How soon must I inform the insurer after an emergency hospitalisation?",
]


class NoCallsAllowed:
    """Stands in for Gemini and the model server in --check: any call is a failure."""

    def __getattr__(self, name: str):
        async def refuse(*_args, **_kwargs):
            raise AssertionError(f"{name} was called, so this question was NOT answered from the cache")

        return refuse


async def main(policy_arg: str | None, check: bool) -> None:
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
                      timeout_seconds=settings.qa_llm_timeout_seconds)
    try:
        for question in DEMO_QUESTIONS:
            key = answer_key(str(document.id), document_hash, normalise_question(question), PROMPT_VERSION, settings.gemini_model)
            if cache.get(key) is not None:
                print(f"  already cached: {question}")
                continue
            try:
                outcome = await answer_question(
                    session_factory=session_factory, models=server, llm=llm, cache=cache, gemini_model=settings.gemini_model,
                    household_id=policy.household_id, document_id=document.id, document_hash=document_hash, question=question,
                )
            except (LlmError, ModelServerError) as error:
                # Not cached; run the script again later to fill it in.
                print(f"  NOT cached ({getattr(error, 'code', 'models')}): {question}")
                continue
            result = outcome.result
            print(f"  cached ({outcome.timings['total']:.1f}s, by {outcome.record['models']}): {question}")
            print(f"      abstained={result['abstained']} verification={result['verification']}")
            print(f"      {result['answer'] or result['missing_context']}")
            print(f"      citations: {[c['label'] for c in result['citations']]}")
    finally:
        await server.stop()
        await engine.dispose()


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--check"]
    asyncio.run(main(args[0] if args else None, "--check" in sys.argv))
