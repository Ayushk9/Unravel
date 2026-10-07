"""Upload a PDF to a running API, wait for the parse, and print every extracted field.

A manual end-to-end check through real HTTP: POST /documents, poll
GET /jobs/{id} until the job finishes, then GET /policies/{id}.

Run from apps/api, with the server already running:
    ../../.venv/bin/python scripts/print_policy_table.py path/to/policy.pdf
    ../../.venv/bin/python scripts/print_policy_table.py path/to/policy.pdf --base-url http://localhost:8000

Prints one row per field (value, confidence, page, bbox) and then checks:
every bbox is within 0..1, every money value is an integer, and at least one
field has confidence "low" or "medium". Exits with status 1 if a check fails
or the job does not succeed.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

STUB_TOKEN = "mock-household-token"  # accepted only when the server runs with ENVIRONMENT=dev
POLL_SECONDS = 2.0


def upload(client: httpx.Client, pdf_path: Path) -> str:
    response = client.post(
        "/documents",
        files={"file": (pdf_path.name, pdf_path.read_bytes(), "application/pdf")},
        data={"claim_id": ""},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    print(f"POST /documents -> {response.status_code} {response.text}")
    if response.status_code != 202:
        raise SystemExit(1)
    return response.json()["job_id"]


def wait_for_job(client: httpx.Client, job_id: str) -> dict[str, Any]:
    started = time.monotonic()
    last_step = None
    while True:
        job = client.get(f"/jobs/{job_id}").json()
        step = (job.get("progress") or {}).get("step")
        if (job["status"], step) != last_step:
            print(f"  [{time.monotonic() - started:6.1f}s] status={job['status']} step={step}")
            last_step = (job["status"], step)
        if job["status"] in ("succeeded", "failed"):
            print(f"Job finished in {time.monotonic() - started:.1f}s: {job}")
            return job
        time.sleep(POLL_SECONDS)


def rows_for(profile: dict[str, Any]) -> list[tuple[str, dict[str, Any], bool]]:
    """(field name, Extracted object, is it money?) for every field in the profile."""
    rows = [
        ("sum_insured", profile["sum_insured"], True),
        ("co_pay_percent", profile["co_pay_percent"], False),
        ("intimation_deadline_hours", profile["intimation_deadline_hours"], False),
    ]
    for sub_limit in profile["sub_limits"]:
        name = f"sub_limit[{sub_limit['category']}] {sub_limit['label']} ({sub_limit['cap_basis']})"
        rows.append((name, sub_limit["cap_amount"], True))
    for period in profile["waiting_periods"]:
        applies_to = f" {period['applies_to']}" if period["applies_to"] else ""
        rows.append((f"waiting_period[{period['kind']}]{applies_to} months", period["months"], False))
    for index, exclusion in enumerate(profile["exclusions"]):
        rows.append((f"exclusion[{index}]", exclusion, False))
    return rows


def short(value: Any, width: int) -> str:
    text = "null" if value is None else str(value)
    return text if len(text) <= width else text[: width - 1] + "…"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--token", default=STUB_TOKEN)
    arguments = parser.parse_args()

    with httpx.Client(
        base_url=f"{arguments.base_url}/api/v1",
        headers={"Authorization": f"Bearer {arguments.token}"},
        timeout=120.0,
    ) as client:
        job = wait_for_job(client, upload(client, arguments.pdf))
        if job["status"] != "succeeded":
            raise SystemExit(1)

        policy_id = job["result"]["policy_id"]
        policy = client.get(f"/policies/{policy_id}").json()
        document = client.get(f"/documents/{job['result']['document_id']}").json()

    profile = policy["coverage_profile"]
    print(f"\nGET /policies/{policy_id}")
    print(f"  insurer={policy['insurer']} policy_number={policy['policy_number']} product_name={policy['product_name']}")
    print(f"  policy_type={policy['policy_type']} start_date={policy['start_date']} end_date={policy['end_date']}")
    print(f"  document: pages={document['page_count']} parse_status={document['parse_status']}")
    print(f"  extraction_completeness={profile['extraction_completeness']:.2f}\n")

    rows = rows_for(profile)
    print(f"{'field':<58} {'value':<28} {'conf':<6} {'page':>4}  bbox")
    print("-" * 132)
    for name, field, _ in rows:
        provenance = field["provenance"] or {}
        bbox = provenance.get("bbox")
        bbox_text = "null" if bbox is None else "[" + ", ".join(f"{c:.3f}" for c in bbox) + "]"
        print(
            f"{short(name, 58):<58} {short(field['value'], 28):<28} {field['confidence']:<6} "
            f"{str(provenance.get('page', '-')):>4}  {bbox_text}"
        )

    bboxes = [field["provenance"]["bbox"] for _, field, _ in rows if field["provenance"] and field["provenance"]["bbox"]]
    bbox_ok = all(0 <= coordinate <= 1 for bbox in bboxes for coordinate in bbox)
    money = [field["value"] for _, field, is_money in rows if is_money and field["value"] is not None]
    money_ok = all(type(value) is int for value in money)
    uncertain = [name for name, field, _ in rows if field["confidence"] in ("low", "medium")]

    print(f"\nChecks over {len(rows)} fields:")
    print(f"  {'PASS' if bbox_ok else 'FAIL'}  all {len(bboxes)} bboxes within 0..1")
    print(f"  {'PASS' if money_ok else 'FAIL'}  all {len(money)} money values are integers")
    print(f"  {'PASS' if uncertain else 'FAIL'}  {len(uncertain)} field(s) have confidence low or medium")
    if not (bbox_ok and money_ok and uncertain):
        sys.exit(1)


if __name__ == "__main__":
    main()
