"""Cold, warm and cache-hit latency of one policy question, per stage.

Run from apps/api, after seed_demo_claims.py and index_chunks.py (needs the
database, the Q&A models and the Gemini key):
    ../../.venv/bin/python scripts/measure_qa_latency.py

  cold       the model server is started now; the first question waits for the
             models to load (from disk, after the first-ever download)
  warm       the next questions, models already loaded; median per stage
  cache hit  the first question asked again: no model call at all

Uses a real policy: by default the dev household's newest policy that is not
the synthetic test fixture (KHA/FAM/2024/DEMO-0001), i.e. the uploaded Star
policy. Pass a policy id to choose another. A fresh cache is used, so every
question except the repeat is really answered.
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import tempfile
import time
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.db.models import Document  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.models_server.client import ModelServer  # noqa: E402
from app.qa.cache import QaCache  # noqa: E402
from app.qa.llm import GeminiQaLlm  # noqa: E402
from app.qa.run_question import answer_question  # noqa: E402

from app.qa.demo_policy import find_real_policy  # noqa: E402
QUESTIONS = [
    "What if I choose a ₹12,000/day room?",
    "How long is the waiting period for pre-existing diseases?",
    "Is cosmetic treatment covered?",
    "When must I tell the insurer about a hospitalisation?",
    "Is cataract surgery covered straight away?",
    "What is my sum insured?",
]


async def main(policy_arg: str | None) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        policy = await find_real_policy(session, UUID(policy_arg) if policy_arg else None)
        document = await session.get(Document, policy.source_document_id)
        household_id, document_id = policy.household_id, document.id
        document_hash = document.sha256 or f"document:{document.id}"
    server = ModelServer(embed_model=settings.embedding_model, rerank_model=settings.rerank_model, device=settings.model_device,
                         load_timeout_seconds=settings.model_load_timeout_seconds, request_timeout_seconds=settings.model_request_timeout_seconds)
    llm = GeminiQaLlm(api_key=settings.gemini_api_key, model=settings.gemini_model, fallback_model=settings.gemini_fallback_model,
                      timeout_seconds=settings.qa_llm_timeout_seconds)
    cache = QaCache(Path(tempfile.mkdtemp(prefix="qa-latency-")))

    async def ask(question: str) -> tuple[float, dict]:
        started = time.perf_counter()
        outcome = await answer_question(session_factory=session_factory, models=server, llm=llm, cache=cache,
                                        gemini_model=settings.gemini_model, household_id=household_id, document_id=document_id,
                                        document_hash=document_hash, question=question)
        return time.perf_counter() - started, {**outcome.timings, "abstained": outcome.result["abstained"], "cache_hit": outcome.cache_hit}

    try:
        server.start()
        cold, cold_detail = await ask(QUESTIONS[0])
        warm = [await ask(q) for q in QUESTIONS[1:]]
        hit, hit_detail = await ask(QUESTIONS[0])
    finally:
        await server.stop()
        await engine.dispose()

    print(f"policy {policy.id} ({policy.product_name or 'no product name'})")
    print(f"device={settings.model_device} model={settings.gemini_model} fallback={settings.gemini_fallback_model}")
    print(f"model load inside the server: {server.load_seconds}s")
    print(f"cold  (start + first question): {cold:.2f}s   stages: {cold_detail}")
    stages = sorted({k for _, d in warm for k in d if isinstance(d[k], float)})
    print(f"warm  (median of {len(warm)} questions):  {statistics.median(t for t, _ in warm):.2f}s")
    for stage in stages:
        values = [d[stage] for _, d in warm if stage in d]
        print(f"        {stage:22} median {statistics.median(values):.2f}s  max {max(values):.2f}s")
    print(f"cache hit (first question again): {hit * 1000:.0f} ms   {hit_detail}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else None))
