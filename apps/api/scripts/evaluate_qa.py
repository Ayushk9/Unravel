"""Evaluate policy Q&A on the Star Comprehensive wording: retrieval, citation precision, abstention.

Run from apps/api (needs the database, the Q&A models and the Gemini key):
    ../../.venv/bin/python scripts/evaluate_qa.py

Refuses to run until eval/qa_star_comprehensive.yaml has checked_by_ayush: true.

What it does:
  1. Makes sure an evaluation household exists (fixed id, no login), with the
     Star wording parsed into a policy (Engine A, in a child process, as an
     upload would) and indexed. Done once; later runs reuse it.
  2. Asks every question through the same pipeline as the API
     (app/qa/run_question.answer_question), with a fresh cache, so every
     answer is really generated.
  3. Reports, overall and split English vs Hindi/Marathi:
       recall@5            answerable questions whose 5 kept clauses include an expected page
       citation precision  supported (sentence, citation) pairs / all pairs the model produced
       abstention          unanswerable questions that abstained / unanswerable questions
       answered            answerable questions that did not abstain / answerable questions
  4. Writes every answer, citation and judgement to eval/results_<date>.json.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import tempfile
from datetime import date
from pathlib import Path
from uuid import UUID

import yaml

API_DIR = Path(__file__).resolve().parents[1]
REPO = API_DIR.parents[1]
sys.path.insert(0, str(API_DIR))

from sqlalchemy import or_, select  # noqa: E402

from app.db.models import Document, Household, Policy  # noqa: E402
from app.qa.demo_policy import EXCLUDED_FROM_EVALUATION  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import create_engine, create_session_factory  # noqa: E402
from app.jobs.worker_process import ChildResult, run_extraction, run_in_child_process  # noqa: E402
from app.models_server.client import ModelServer  # noqa: E402
from app.qa.cache import QaCache  # noqa: E402
from app.qa.indexing import index_counts, index_document  # noqa: E402
from app.qa.llm import GeminiQaLlm  # noqa: E402
from app.qa.run_question import answer_question  # noqa: E402
from app.services.policy_writer import store_extraction  # noqa: E402
from contracts.models import ExtractionResult  # noqa: E402

EVAL_SET = REPO / "eval" / "qa_star_comprehensive.yaml"
EVAL_HOUSEHOLD = UUID("01920000-0000-7000-8000-0000000000ea")
EVAL_AUTH_USER = UUID("01920000-0000-7000-8000-0000000000eb")  # no real login uses this
EVAL_DOCUMENT = UUID("01920000-0000-7000-8000-0000000000ec")


async def ensure_policy(session_factory, settings, server: ModelServer, pdf: Path) -> tuple[UUID, str]:
    sha256 = hashlib.sha256(pdf.read_bytes()).hexdigest()
    async with session_factory() as session, session.begin():
        if await session.get(Household, EVAL_HOUSEHOLD) is None:
            session.add(Household(id=EVAL_HOUSEHOLD, name="Evaluation household (Q&A)", auth_user_id=EVAL_AUTH_USER))
        document = await session.get(Document, EVAL_DOCUMENT)
        if document is None:
            session.add(Document(id=EVAL_DOCUMENT, household_id=EVAL_HOUSEHOLD, file_name=pdf.name, mime_type="application/pdf",
                                 sha256=sha256, size_bytes=pdf.stat().st_size, parse_status="queued"))
        # The demo copy SAMPLE-0002 shares a document with the Star policy; it never counts as the evaluated policy.
        policy_exists = await session.scalar(
            select(Policy.id).where(
                Policy.source_document_id == EVAL_DOCUMENT,
                or_(Policy.policy_number.is_(None), Policy.policy_number.not_in(EXCLUDED_FROM_EVALUATION)),
            )
        ) is not None

    if not policy_exists:
        print(f"Parsing {pdf.name} with Engine A (a few minutes the first time)...")
        outcome = await run_in_child_process(
            run_extraction, (str(pdf), "policy", settings.gemini_api_key, settings.gemini_model, 900), 900
        )
        if not isinstance(outcome, ChildResult) or not outcome.message.get("ok"):
            raise SystemExit(f"Engine A could not parse the policy: {outcome}")
        result = ExtractionResult.model_validate_json(outcome.message["result_json"])
        async with session_factory() as session, session.begin():
            document = await session.get(Document, EVAL_DOCUMENT)
            await store_extraction(session, document, result)
            document.parse_status = "parsed"

    embedded = await index_document(session_factory, server, EVAL_DOCUMENT)
    async with session_factory() as session:
        total, indexed = await index_counts(session, EVAL_DOCUMENT)
    print(f"Policy ready: {total} clauses, {indexed} indexed ({embedded} embedded now).")
    return EVAL_DOCUMENT, sha256


def score(rows: list[dict]) -> dict[str, object]:
    answerable = [r for r in rows if r["answerable"]]
    unanswerable = [r for r in rows if not r["answerable"]]
    pairs = sum(r["pairs"] for r in rows)
    supported = sum(r["supported_pairs"] for r in rows)

    def frac(hit: int, total: int) -> str:
        return f"{hit}/{total} ({hit / total:.0%})" if total else "n/a"

    return {
        "recall@5": frac(sum(r["retrieval_hit"] for r in answerable), len(answerable)),
        "citation precision": frac(supported, pairs),
        "abstention (unanswerable)": frac(sum(r["abstained"] for r in unanswerable), len(unanswerable)),
        "answered (answerable)": frac(sum(not r["abstained"] for r in answerable), len(answerable)),
    }


async def main() -> None:
    spec = yaml.safe_load(EVAL_SET.read_text(encoding="utf-8"))
    if not spec.get("checked_by_ayush"):
        raise SystemExit(f"{EVAL_SET.relative_to(REPO)} is still a draft: check the questions and pages, then set checked_by_ayush: true.")

    settings = get_settings()
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    server = ModelServer(embed_model=settings.embedding_model, rerank_model=settings.rerank_model, device=settings.model_device,
                         load_timeout_seconds=settings.model_load_timeout_seconds, request_timeout_seconds=settings.model_request_timeout_seconds)
    server.start()
    llm = GeminiQaLlm(api_key=settings.gemini_api_key, model=settings.gemini_model, fallback_model=settings.gemini_fallback_model,
                      timeout_seconds=settings.qa_llm_timeout_seconds)
    rows = []
    try:
        document_id, sha256 = await ensure_policy(session_factory, settings, server, REPO / spec["policy_pdf"])
        cache = QaCache(Path(tempfile.mkdtemp(prefix="qa-eval-")))  # fresh: every answer is generated now
        for item in spec["questions"]:
            outcome = await answer_question(
                session_factory=session_factory, models=server, llm=llm, cache=cache, gemini_model=settings.gemini_model,
                household_id=EVAL_HOUSEHOLD, document_id=document_id, document_hash=sha256, question=item["question"],
            )
            kept_pages = [r["page"] for r in (outcome.record["retrieved"] or []) if r["kept"]]
            generated = outcome.record["generated"] or {}
            pairs = sum(len(set(s["chunk_ids"])) for s in generated.get("sentences", []))
            judgements = (outcome.record["verification"] or {}).get("judgements", [])
            row = {
                "id": item["id"], "language": item["language"], "answerable": item["answerable"], "question": item["question"],
                "expected_pages": item.get("expected_pages", []), "kept_pages": kept_pages,
                "retrieval_hit": bool(set(kept_pages) & set(item.get("expected_pages", []))),
                "abstained": outcome.result["abstained"], "pairs": pairs,
                "supported_pairs": sum(j["supported"] for j in judgements),
                "answer": outcome.result["answer"], "missing_context": outcome.result["missing_context"],
                "cited_pages": [c["provenance"]["page"] for c in outcome.result["citations"]],
                "verification": outcome.result["verification"], "search_query": outcome.record["search_query"],
                "removed": (outcome.record["verification"] or {}).get("removed", []), "timings": outcome.timings,
            }
            rows.append(row)
            print(f"{row['id']} [{row['language']}] hit={row['retrieval_hit']} abstained={row['abstained']} "
                  f"pairs={row['supported_pairs']}/{row['pairs']} kept_pages={kept_pages}")
    finally:
        await server.stop()
        await engine.dispose()

    english = [r for r in rows if r["language"] == "en"]
    indic = [r for r in rows if r["language"] != "en"]
    table = {"all": score(rows), "English": score(english), "Hindi/Marathi": score(indic)}
    print()
    metrics = list(table["all"])
    print(f"{'metric':28} " + " ".join(f"{name:>18}" for name in table))
    for metric in metrics:
        print(f"{metric:28} " + " ".join(f"{str(table[name][metric]):>18}" for name in table))

    out = REPO / "eval" / f"results_{date.today().isoformat()}.json"
    out.write_text(json.dumps({"model": settings.gemini_model, "table": table, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {out.relative_to(REPO)}")


if __name__ == "__main__":
    asyncio.run(main())
