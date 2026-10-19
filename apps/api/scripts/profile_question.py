"""Profile one policy question end to end: every stage, every database statement, every round trip.

Run from apps/api (needs the database, the Q&A models and Gemini):
    ../../.venv/bin/python scripts/profile_question.py [policy_id] ["question"]

Default policy: the dev household's newest real policy (app/qa/demo_policy.py),
never the synthetic test fixture. The question goes through the real job
code (run_answer_question), with a fresh cache, so nothing is skipped.

A "round trip" is one exchange with Postgres over the network. Each SQL
statement is one, and so is each BEGIN, COMMIT and ROLLBACK, which no
statement count shows. All are counted here from SQLAlchemy's own events.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import event, select, text  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.ids import new_id  # noqa: E402
from app.db.models import Job, Policy, PolicyQuestion  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.jobs.queue import ClaimedJob  # noqa: E402
from app.models_server.client import ModelServer  # noqa: E402
from app.qa.cache import QaCache  # noqa: E402
from app.qa.demo_policy import find_real_policy  # noqa: E402
from app.qa.llm import GeminiQaLlm  # noqa: E402
from app.qa.run_question import run_answer_question  # noqa: E402

DEFAULT_QUESTION = "What if I choose a ₹12,000/day room?"


def label(statement: str) -> str:
    words = " ".join(statement.split())
    for marker, name in [("<=>", "dense search"), ("to_tsquery", "keyword search"), ("ANY(", "fetch clauses"),
                         ("UPDATE job", "job progress/finish"), ("INSERT INTO policy_question", "question log"),
                         ("FROM policy ", "load policy"), ("FROM document ", "load document"), ("FROM job", "load job")]:
        if marker in words:
            return name
    return words[:50]


async def main(policy_arg: str | None, question: str) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)

    async with session_factory() as session:
        policy = await find_real_policy(session, UUID(policy_arg) if policy_arg else None)
        policy_id = policy.id
        rtt = []
        for _ in range(5):
            t = time.perf_counter()
            await session.execute(text("SELECT 1"))
            rtt.append(time.perf_counter() - t)
    print(f"policy {policy_id} (document {policy.source_document_id})")
    print(f"one database round trip (SELECT 1, best of 5): {min(rtt) * 1000:.0f} ms")

    server = ModelServer(embed_model=settings.embedding_model, rerank_model=settings.rerank_model, device=settings.model_device,
                         load_timeout_seconds=settings.model_load_timeout_seconds, request_timeout_seconds=settings.model_request_timeout_seconds)
    server.start()
    await server.embed(["warm up"])  # profile a warm question, not model loading
    llm = GeminiQaLlm(api_key=settings.gemini_api_key, model=settings.gemini_model, fallback_model=settings.gemini_fallback_model,
                      timeout_seconds=settings.qa_llm_timeout_seconds)

    job_id = new_id()
    async with session_factory() as session, session.begin():
        session.add(Job(id=job_id, household_id=policy.household_id, kind="answer_question", status="running",
                        payload={"policy_id": str(policy_id), "question": question}))

    statements: list[tuple[str, float]] = []
    transactions: Counter[str] = Counter()
    started_at: dict[int, float] = {}
    sync_engine = engine.sync_engine

    @event.listens_for(sync_engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        started_at[id(context)] = time.perf_counter()

    @event.listens_for(sync_engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append((label(statement), time.perf_counter() - started_at.pop(id(context), time.perf_counter())))

    for name in ("begin", "commit", "rollback"):
        event.listen(sync_engine, name, lambda conn, _n=name: transactions.update([_n]))

    t = time.perf_counter()
    await run_answer_question(
        ClaimedJob(id=job_id, household_id=policy.household_id, kind="answer_question", payload={"policy_id": str(policy_id), "question": question}),
        session_factory=session_factory, models=server, llm=llm, cache=QaCache(Path(tempfile.mkdtemp(prefix="qa-profile-"))),
        gemini_model=settings.gemini_model,
    )
    total = time.perf_counter() - t
    await server.stop()

    async with session_factory() as session:
        row = await session.scalar(select(PolicyQuestion).where(PolicyQuestion.job_id == job_id))
    await engine.dispose()

    print(f"\nquestion: {question!r}\nanswered by: {row.models}\nabstained: {row.result['abstained']}  verification: {row.result['verification']}")
    print(f"answer: {row.result['answer'][:300]}")
    print(f"\nwhole job: {total:.2f}s")
    print("stages (seconds):")
    for name, seconds in row.timings.items():
        print(f"  {name:32} {seconds}")
    print(f"\ndatabase statements: {len(statements)}")
    by_label: dict[str, list[float]] = {}
    for name, seconds in statements:
        by_label.setdefault(name, []).append(seconds)
    for name, values in by_label.items():
        print(f"  {name:28} x{len(values)}  {sum(values) * 1000:7.0f} ms")
    print(f"transactions: {dict(transactions)}")
    trips = len(statements) + sum(transactions.values())
    print(f"round trips in total (statements + BEGIN/COMMIT/ROLLBACK): {trips}")
    search = [s for s in statements if s[0] in ("dense search", "keyword search", "fetch clauses")]
    print(f"round trips in the search itself: {len(search)} statements + 1 BEGIN + 1 ROLLBACK = {len(search) + 2}, "
          f"{sum(s for _, s in search) * 1000:.0f} ms in statements")


SEARCH_QUESTIONS = [
    "What if I choose a 12,000/day room?", "How long is the waiting period for pre-existing diseases?",
    "Is cosmetic surgery covered?", "When must I inform the insurer after an emergency hospitalisation?",
    "Is there a co-payment?", "What is the free look period?",
]


async def search_only(policy_arg: str | None) -> None:
    """The search step alone, no Gemini: one cold search on a fresh connection, then warm ones."""
    from app.qa.retrieval import retrieve

    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        policy = await find_real_policy(session, UUID(policy_arg) if policy_arg else None)
        policy_id = policy.id
    server = ModelServer(embed_model=settings.embedding_model, rerank_model=settings.rerank_model, device=settings.model_device,
                         load_timeout_seconds=settings.model_load_timeout_seconds, request_timeout_seconds=settings.model_request_timeout_seconds)
    server.start()
    await server.embed(["warm up"])

    trips: list[int] = []
    current = {"n": 0}
    sync_engine = engine.sync_engine
    event.listen(sync_engine, "after_cursor_execute", lambda *a, **k: current.update(n=current["n"] + 1))
    for name in ("begin", "commit", "rollback"):
        event.listen(sync_engine, name, lambda conn: current.update(n=current["n"] + 1))

    rows = []
    for index, question in enumerate(SEARCH_QUESTIONS):
        current["n"] = 0
        t = time.perf_counter()
        async with session_factory() as session:
            result = await retrieve(session, server, household_id=policy.household_id, document_id=policy.source_document_id, query=question)
        rows.append((index, time.perf_counter() - t, current["n"], result.timings))
    await server.stop()
    await engine.dispose()

    db_keys = [k for k in rows[0][3] if k.startswith("db_")]
    print(f"policy {policy_id}: search only (embed + database + rerank), {len(SEARCH_QUESTIONS)} questions")
    for index, total, n, timings in rows:
        db = sum(timings[k] for k in db_keys)
        print(f"  {'cold' if index == 0 else 'warm'}  round trips {n}  database {db * 1000:5.0f} ms  "
              f"rerank {timings['rerank'] * 1000:5.0f} ms  total {total * 1000:5.0f} ms   "
              + "  ".join(f"{k}={timings[k] * 1000:.0f}ms" for k in db_keys))
    warm = rows[1:]
    print(f"warm median: database {sorted(sum(t[k] for k in db_keys) for *_, t in warm)[len(warm) // 2] * 1000:.0f} ms, "
          f"total {sorted(t for _, t, _, _ in warm)[len(warm) // 2] * 1000:.0f} ms")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--search-only"]
    if "--search-only" in sys.argv:
        asyncio.run(search_only(args[0] if args else None))
    else:
        asyncio.run(main(args[0] if args else None, args[1] if len(args) > 1 else DEFAULT_QUESTION))
