"""Time ONE grievance draft call to Gemini and show where the time goes.

Run from apps/api (needs the database, the Q&A models and the Gemini key):
    ../../.venv/bin/python scripts/diagnose_draft_call.py default   the call as it was (model's own thinking, no cap)
    ../../.venv/bin/python scripts/diagnose_draft_call.py limited   the job's options (DRAFT_OPTIONS)
    ../../.venv/bin/python scripts/diagnose_draft_call.py limited gemini-3.7-flash   another model (default GEMINI_MODEL)

Builds the exact prompt the job sends for Lakshmi's claim (…0f3) at the
insurer_grievance_cell rung: the same retrieval, facts block and clauses
(app/grievance/llm.draft_contents). Then:

  prompt size   from count_tokens (not a generate call)
  1 generate call, streamed, so the time to the first byte is visible
  total time, finish reason, and usage: prompt, thinking and output tokens

Exactly one generate call per run, with no retry and no fallback, and a 240 s
limit. Nothing is stored. The draft text itself is not printed, only its size.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.claims.deadlines import india_date  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models import Claim  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.grievance.llm import DRAFT_OPTIONS, RUNG_DESCRIPTIONS, GeminiGrievanceLlm, GeneratedDraft, draft_contents  # noqa: E402
from app.grievance.run_draft import facts_block, load_context, merge_clauses, search_queries  # noqa: E402
from app.models_server.client import ModelServer  # noqa: E402
from app.qa.llm import CallOptions, ClausePrompt  # noqa: E402
from app.qa.retrieval import retrieve  # noqa: E402

LAKSHMI = UUID("01920000-0000-7000-8000-0000000000f3")
RUNG = "insurer_grievance_cell"
LIMIT_SECONDS = 240


async def build_contents() -> list[str]:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    server = ModelServer(embed_model=settings.embedding_model, rerank_model=settings.rerank_model, device=settings.model_device,
                         load_timeout_seconds=settings.model_load_timeout_seconds, request_timeout_seconds=settings.model_request_timeout_seconds)
    try:
        async with factory() as session:
            claim = await session.get(Claim, LAKSHMI)
        context = await load_context(factory, claim.household_id, claim.id, RUNG, india_date(datetime.now(timezone.utc)))
        server.start()
        per_query = []
        async with factory() as session:
            for query in search_queries(context.letter.denial_reason, context.checks):
                found = await retrieve(session, server, household_id=context.household_id, document_id=context.document_id, query=query)
                per_query.append(found.clauses)
        clauses = merge_clauses(per_query)
        prompts = [ClausePrompt(id=f"c{i}", page=c.page, text=c.text) for i, c in enumerate(clauses, start=1)]
        print(f"retrieved {len(prompts)} clauses (pages {[p.page for p in prompts]})")
        return draft_contents(RUNG_DESCRIPTIONS[RUNG], facts_block(context), prompts)
    finally:
        await server.stop()
        await engine.dispose()


async def one_call(contents: list[str], options: CallOptions, model: str) -> None:
    settings = get_settings()
    llm = GeminiGrievanceLlm(api_key=settings.gemini_api_key, model=model, timeout_seconds=LIMIT_SECONDS)
    client = llm._client.aio.models
    counted = await client.count_tokens(model=model, contents=contents)
    print(f"model={model} options={options}")
    print(f"prompt: {sum(len(c) for c in contents)} characters, {counted.total_tokens} tokens (count_tokens)")

    started = time.perf_counter()
    first_byte: float | None = None
    text, usage, finish = "", None, None

    async def stream() -> None:
        nonlocal first_byte, text, usage, finish
        async for chunk in await client.generate_content_stream(model=model, contents=contents, config=llm.config(GeneratedDraft, options)):
            if first_byte is None:
                first_byte = time.perf_counter() - started
            text += chunk.text or ""
            usage = chunk.usage_metadata or usage
            if chunk.candidates and chunk.candidates[0].finish_reason:
                finish = chunk.candidates[0].finish_reason

    try:
        await asyncio.wait_for(stream(), LIMIT_SECONDS)
        outcome = "answered"
    except TimeoutError:
        outcome = f"NO ANSWER within {LIMIT_SECONDS}s"
    except Exception as exc:  # noqa: BLE001 - reported, not hidden
        outcome = f"failed: {type(exc).__name__}: {str(exc)[:300]}"
    total = time.perf_counter() - started

    print(f"outcome: {outcome}")
    print(f"time to first byte: {f'{first_byte:.1f}s' if first_byte is not None else 'none'}   total: {total:.1f}s   finish: {finish}")
    if usage:
        print(f"tokens: prompt={usage.prompt_token_count} thinking={usage.thoughts_token_count} output={usage.candidates_token_count} total={usage.total_token_count}")
    print(f"output: {len(text)} characters; valid draft JSON: {_valid(text)}")
    if _valid(text):
        parsed = GeneratedDraft.model_validate_json(text)
        print(f"abstained: {parsed.abstain}; paragraphs: {len(parsed.paragraphs)}")


def _valid(text: str) -> bool:
    try:
        GeneratedDraft.model_validate_json(text)
        return True
    except Exception:  # noqa: BLE001
        return False


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    options = {"default": CallOptions(), "limited": DRAFT_OPTIONS}.get(mode)
    if options is None:
        raise SystemExit(__doc__)
    model = sys.argv[2] if len(sys.argv) > 2 else get_settings().gemini_model
    contents = asyncio.run(build_contents())
    asyncio.run(one_call(contents, options, model))


if __name__ == "__main__":
    main()
