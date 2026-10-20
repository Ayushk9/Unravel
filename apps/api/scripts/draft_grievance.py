"""Draft one grievance letter for one claim with the real models, and print it.

Run from apps/api (needs the database, the Q&A models and the Gemini key):
    ../../.venv/bin/python scripts/draft_grievance.py <claim_id> [rung]

rung defaults to insurer_grievance_cell. Costs 2 Gemini calls (draft and
judge), or none if nothing relevant is found in the policy. Drafts are never
cached. The draft is stored in grievance_draft (job_id null), like one made
through the API, because it is evaluation data.

Prints the rung options, the full plain-text letter, each paragraph's
verification outcome and the evidence checklist. Starts its own model
process and stops it afterwards; it does not touch a running API server.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.v1.grievances import claim_rung_options  # noqa: E402
from app.claims.deadlines import india_date  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.models import Claim  # noqa: E402
from app.db.models import GrievanceDraft as GrievanceDraftRow  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.grievance.llm import GRIEVANCE_PROMPT_VERSION, GeminiGrievanceLlm  # noqa: E402
from app.grievance.run_draft import draft_letter, load_context  # noqa: E402
from app.models_server.client import ModelServer  # noqa: E402


async def main(claim_id: UUID, rung: str) -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        claim = await session.get(Claim, claim_id)
        if claim is None:
            raise SystemExit(f"No claim {claim_id}")
        options = await claim_rung_options(session, claim)
    print("RUNG OPTIONS")
    for option in options:
        print(f"  {option.rung:24} available={option.available} verified={option.verified}\n      {option.reason}")
    if not next(o for o in options if o.rung == rung).available:
        raise SystemExit(f"{rung} is not available for this claim.")

    context = await load_context(session_factory, claim.household_id, claim.id, rung, india_date(now))
    server = ModelServer(embed_model=settings.embedding_model, rerank_model=settings.rerank_model, device=settings.model_device,
                         load_timeout_seconds=settings.model_load_timeout_seconds, request_timeout_seconds=settings.model_request_timeout_seconds)
    llm = GeminiGrievanceLlm(api_key=settings.gemini_api_key, model=settings.gemini_model, fallback_model=settings.gemini_fallback_model,
                             timeout_seconds=settings.grievance_llm_timeout_seconds)
    try:
        server.start()
        outcome = await draft_letter(session_factory=session_factory, models=server, llm=llm, context=context, now=now)
        async with session_factory() as session, session.begin():
            session.add(GrievanceDraftRow(
                id=outcome.result.id, household_id=context.household_id, claim_id=context.claim_id, job_id=None, rung=rung,
                result=outcome.result.model_dump(mode="json"), timings=outcome.timings, prompt_version=GRIEVANCE_PROMPT_VERSION,
                **outcome.record,
            ))
    finally:
        await server.stop()
        await engine.dispose()

    draft = outcome.result
    print("\nLETTER\n" + "=" * 72 + f"\n{draft.letter_text}\n" + "=" * 72)
    print("\nPARAGRAPHS")
    # An abstained draft (no clauses, or no honest ground) has no verification record and no paragraphs.
    checks = (outcome.record["verification"] or {}).get("paragraphs", [])
    for index, (paragraph, check) in enumerate(zip(draft.paragraphs, checks, strict=True), 1):
        pages = sorted({c.provenance.page for c in draft.citations if c.id in paragraph.citation_ids and c.provenance})
        print(f"  {index}. verified={paragraph.verified} pages={pages} reason={check['reason']} {check['detail'] or ''}")
    print(f"  citation_precision={draft.citation_precision:.2f} missing_context={draft.missing_context}")
    print("\nEVIDENCE CHECKLIST")
    for item in draft.evidence_checklist:
        print(f"  [{'x' if item.satisfied else ' '}] {item.item}")
    print(f"\nmodels={json.dumps(outcome.record['models'])} timings={json.dumps(outcome.timings)} draft_id={draft.id}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    asyncio.run(main(UUID(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "insurer_grievance_cell"))
