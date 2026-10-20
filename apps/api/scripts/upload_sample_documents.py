"""Attach the fictional sample documents to the four demo claims through the normal upload flow.

Run from apps/api, with the server already running (started by you, with ENVIRONMENT=dev):
    ../../.venv/bin/python scripts/make_sample_documents.py      (once; no network)
    ../../.venv/bin/python scripts/upload_sample_documents.py [--base-url http://localhost:8000]

For each file in sample_documents/<member>/: POST /documents with the claim's
id, then poll GET /jobs/{id} until classification finishes. This is the same
path the claim wizard uses, so the classifier really runs: ONE Gemini call per
document that is not already in the classification cache (15 documents).

Safe to run again: a file already attached to its claim (same file name, not
deleted) is skipped, and each upload's Idempotency-Key is fixed per file.

Afterwards it prints, per claim, the documents' detected types, the
completeness report (GET from the server) and the grievance evidence
checklist (built by app/grievance/evidence.py from the database; no model call).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_sample_documents import OUT_DIR  # noqa: E402
from seed_demo_claims import CLAIMS  # noqa: E402

STUB_TOKEN = "mock-household-token"  # accepted only when the server runs with ENVIRONMENT=dev
POLL_SECONDS = 2.0
JOB_TIMEOUT_SECONDS = 180


def attached_names(client: httpx.Client, claim_id: str) -> set[str]:
    names: set[str] = set()
    cursor = None
    while True:
        params = {"claim_id": claim_id, "limit": 100, **({"cursor": cursor} if cursor else {})}
        page = client.get("/documents", params=params).json()
        names |= {document["file_name"] for document in page["items"]}
        cursor = page["next_cursor"]
        if not cursor:
            return names


def upload(client: httpx.Client, claim_id: str, member: str, path: Path) -> dict[str, Any]:
    file_name = f"sample_{member}_{path.name}"
    response = client.post(
        "/documents",
        files={"file": (file_name, path.read_bytes(), "application/pdf")},
        data={"claim_id": claim_id},
        headers={"Idempotency-Key": f"sample-document-{claim_id}-{path.stem}"},
    )
    if response.status_code != 202:
        raise SystemExit(f"POST /documents for {file_name} -> {response.status_code} {response.text}")
    job_id = response.json()["job_id"]
    started = time.monotonic()
    while True:
        job = client.get(f"/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            print(f"  {file_name:44} {job['status']} in {time.monotonic() - started:.1f}s {job['error'] or ''}")
            return job
        if time.monotonic() - started > JOB_TIMEOUT_SECONDS:
            raise SystemExit(f"{file_name}: job {job_id} still {job['status']} after {JOB_TIMEOUT_SECONDS}s")
        time.sleep(POLL_SECONDS)


async def evidence_checklists() -> dict[str, list[tuple[str, bool]]]:
    """Each claim's grievance evidence checklist, from the database, as a draft would build it."""
    from app.claims.deadlines import india_date
    from app.core.config import get_settings
    from app.db.models import Claim
    from app.db.session import create_engine, create_session_factory
    from app.grievance.run_draft import load_context

    engine = create_engine(get_settings().database_url)
    factory = create_session_factory(engine)
    today = india_date(datetime.now(timezone.utc))
    result = {}
    try:
        for demo in CLAIMS:
            async with factory() as session:
                claim = await session.get(Claim, demo.id)
            context = await load_context(factory, claim.household_id, claim.id, "insurer_grievance_cell", today)
            result[demo.member] = [(item.item, item.satisfied) for item in context.evidence]
    finally:
        await engine.dispose()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    calls = 0
    with httpx.Client(base_url=f"{args.base_url}/api/v1", headers={"Authorization": f"Bearer {STUB_TOKEN}"}, timeout=60) as client:
        for demo in CLAIMS:
            claim_id = str(demo.id)
            folder = OUT_DIR / demo.member.lower()
            already = attached_names(client, claim_id)
            print(f"{demo.member} ({claim_id})")
            for path in sorted(folder.glob("*.pdf")):
                if f"sample_{demo.member}_{path.name}" in already:
                    print(f"  {path.name:44} already attached; skipped")
                    continue
                upload(client, claim_id, demo.member, path)
                calls += 1

        print(f"\nUploaded {calls} document(s) (at most {calls} Gemini classification call(s); cached files make none).\n")
        checklists = asyncio.run(evidence_checklists())
        for demo in CLAIMS:
            claim_id = str(demo.id)
            documents = client.get("/documents", params={"claim_id": claim_id, "limit": 100}).json()["items"]
            report = client.post(f"/claims/{claim_id}/completeness").json()
            print(f"{demo.member}")
            for document in documents:
                detected = document["detected_type"]
                print(f"  {document['file_name']:44} -> {detected['value']} ({detected['confidence']})")
            print(f"  missing: {report['missing'] or 'nothing'}")
            for item, satisfied in checklists[demo.member]:
                print(f"  [{'x' if satisfied else ' '}] {item}")


if __name__ == "__main__":
    main()
