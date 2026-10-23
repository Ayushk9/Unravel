"""Rebuild the grievance drafts for the demo claims, the day before the panel, and count the Gemini calls.

Run from apps/api (needs the database, the Q&A models and the Gemini key; the
API server does NOT need to be running, and this script never starts or stops it):
    ../../.venv/bin/python scripts/regenerate_demo_drafts.py [--rung insurer_grievance_cell]

For each demo claim below, it creates a real `generate_grievance_draft` job row
and runs the job function the server's runner uses (run_generate_grievance_draft),
so the draft is stored exactly as one requested through POST /grievance-drafts:
in the job (its `result`) and in grievance_draft. It then prints the screen
link /claims/<id>/grievance?job=<job id>.

  Lakshmi (…0f3)  a denial our rules agree with: template requests and the assessment note
  Rajan   (…0f5)  a wrongful denial: the rules-built opening and "Before you send"

Cost: 2 Gemini calls per draft (draft and judge), plus any retries after a
503, or a fallback after a used-up quota. Every attempt is counted and printed,
by model. Drafts are never cached, so every run costs these calls.

The job rows are kept for 24 hours after they finish, then deleted at the next
server start (app/jobs/queue.JOB_RETENTION). Run it less than 24 hours before the
panel, or the screen links stop working. The grievance_draft rows are kept.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.core.ids import new_id  # noqa: E402
from app.db.models import Claim, Job  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.grievance.llm import GeminiGrievanceLlm  # noqa: E402
from app.grievance.run_draft import run_generate_grievance_draft  # noqa: E402
from app.jobs.parse_document import JobFailure  # noqa: E402
from app.jobs.queue import ClaimedJob, mark_failed  # noqa: E402
from app.models_server.client import ModelServer  # noqa: E402

DEMO_CLAIMS = {
    "Lakshmi": UUID("01920000-0000-7000-8000-0000000000f3"),
    "Rajan": UUID("01920000-0000-7000-8000-0000000000f5"),
}


class CountingGrievanceLlm(GeminiGrievanceLlm):
    """The real Gemini client, counting every attempt by model (retries and the fallback included)."""

    def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(**kwargs)
        self.attempts: Counter[str] = Counter()

    async def _once(self, model, contents, schema, options=None):  # type: ignore[no-untyped-def]
        self.attempts[model] += 1
        return await super()._once(model, contents, schema, options)


async def regenerate(rung: str) -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    factory = create_session_factory(engine)
    server = ModelServer(embed_model=settings.embedding_model, rerank_model=settings.rerank_model, device=settings.model_device,
                         load_timeout_seconds=settings.model_load_timeout_seconds, request_timeout_seconds=settings.model_request_timeout_seconds)
    llm = CountingGrievanceLlm(api_key=settings.gemini_api_key, model=settings.gemini_model, fallback_model=settings.gemini_fallback_model,
                               timeout_seconds=settings.grievance_llm_timeout_seconds)
    failures = 0
    try:
        server.start()
        for name, claim_id in DEMO_CLAIMS.items():
            async with factory() as session, session.begin():
                claim = await session.get(Claim, claim_id)
                if claim is None:
                    raise SystemExit(f"{name}'s claim {claim_id} is missing: run scripts/seed_demo_claims.py first.")
                job = Job(id=new_id(), household_id=claim.household_id, kind="generate_grievance_draft", status="running",
                          progress={"step": "queued", "percent": 0}, payload={"claim_id": str(claim_id), "rung": rung})
                session.add(job)
            before = sum(llm.attempts.values())
            claimed = ClaimedJob(id=job.id, household_id=job.household_id, kind=job.kind, payload=job.payload)
            try:
                await run_generate_grievance_draft(claimed, session_factory=factory, models=server, llm=llm)
            except JobFailure as failure:
                # The same ending the runner gives a failed job: a readable sentence, never left running.
                await mark_failed(factory, job.id, code=failure.code, message=failure.message, retryable=failure.retryable)
                failures += 1
                print(f"{name}: FAILED ({failure.code}): {failure.message}  [{sum(llm.attempts.values()) - before} Gemini attempt(s)]")
                continue
            except Exception:
                # A job must never stay running (CLAUDE.md), whatever went wrong.
                await mark_failed(factory, job.id, code="internal_error",
                                  message="Something went wrong on our side while drafting this letter. Please try again.", retryable=True)
                raise
            async with factory() as session:
                result = (await session.get(Job, job.id)).result
            sources = Counter(p["source"] for p in result["paragraphs"])
            print(f"{name}: drafted. paragraphs {dict(sources)}, before-you-send notes {len(result['before_you_send'])}, "
                  f"assessment note {'yes' if result['assessment_note'] else 'no'}  [{sum(llm.attempts.values()) - before} Gemini attempt(s)]")
            print(f"  screen: /claims/{claim_id}/grievance?job={job.id}   (the job row lasts 24 h)")
    finally:
        await server.stop()
        await engine.dispose()

    total = sum(llm.attempts.values())
    print(f"\nGemini attempts: {total} in total, by model: {dict(llm.attempts) or 'none'} (key ending {settings.gemini_api_key[-4:]})")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rung", default="insurer_grievance_cell", choices=["insurer_grievance_cell", "irdai_bima_bharosa", "insurance_ombudsman"])
    args = parser.parse_args()
    raise SystemExit(1 if asyncio.run(regenerate(args.rung)) else 0)


if __name__ == "__main__":
    main()
