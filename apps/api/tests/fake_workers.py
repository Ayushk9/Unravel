"""Stand-ins for Engine A's child process, so tests never start Docling.

Each function has the same signature as app.jobs.worker_process.run_extraction
and is run in a real child process by the code under test. They must live in
an importable module (not inside a test function) because a spawned process
finds its entry point by importing it.
"""

from __future__ import annotations

import os
import time
from multiprocessing.connection import Connection
from pathlib import Path
from uuid import uuid4

from contracts.models import (
    CoverageProfile,
    DocumentChunk,
    Extracted,
    ExtractionResult,
    Provenance,
    SubLimit,
    WaitingPeriod,
)


def build_policy_result() -> ExtractionResult:
    """What Engine A returns for a policy, placeholder ids included.

    Shaped to exercise the awkward cases: a low-confidence value, a field
    the parser could not find, and two sub-limits sharing one category.
    """
    placeholder_document_id = uuid4()
    placeholder_policy_id = uuid4()

    def found(value: object, confidence: str, page: int, snippet: str) -> Extracted:
        provenance = Provenance(
            document_id=placeholder_document_id, page=page, bbox=(0.1, 0.2, 0.5, 0.25), snippet=snippet
        )
        return Extracted(value=value, confidence=confidence, provenance=provenance)

    def sub_limit(category: str, label: str, amount: int, confidence: str, page: int) -> SubLimit:
        return SubLimit(
            category=category,
            label=label,
            cap_amount=found(amount, confidence, page, label),
            cap_basis="per_day" if category == "room_rent" else "per_claim",
            percent_value=None,
        )

    profile = CoverageProfile(
        policy_id=placeholder_policy_id,
        sum_insured=found(50_000_000, "high", 1, "Sum Insured: Rs. 5,00,000"),
        co_pay_percent=found(10.0, "medium", 2, "Co-payment of 10%"),
        sub_limits=[
            sub_limit("room_rent", "Room rent", 500_000, "low", 10),
            sub_limit("procedure", "Cataract", 4_000_000, "high", 11),
            sub_limit("procedure", "Hernia", 6_000_000, "high", 11),
        ],
        waiting_periods=[
            WaitingPeriod(
                kind="pre_existing",
                months=found(36.0, "high", 18, "36 months of continuous coverage"),
                applies_to=None,
                starts_on=None,
                expires_on=None,
            )
        ],
        exclusions=[found("Cosmetic surgery is excluded", "high", 20, "cosmetic surgery")],
        intimation_deadline_hours=Extracted(value=None, confidence="low", provenance=None),
        extraction_completeness=2 / 3,
    )
    return ExtractionResult(
        page_count=48,
        coverage_profile=profile,
        line_items=[],
        chunks=[
            DocumentChunk(id=uuid4(), document_id=placeholder_document_id, page=1, text="Schedule", bbox=None),
            DocumentChunk(
                id=uuid4(), document_id=placeholder_document_id, page=2, text="Co-pay", bbox=(0.0, 0.0, 1.0, 1.0)
            ),
        ],
        warnings=[
            f"PLACEHOLDER IDS: document_id={placeholder_document_id}, policy_id={placeholder_policy_id}",
            "sub-limit 'ICU' omitted: basis could not be determined",
        ],
    )


def succeed(connection: Connection, file_path: str, document_kind: str, api_key: str, timeout: float) -> None:
    # Proves the temporary file really was there for the child to read.
    assert Path(file_path).exists(), "the temporary file should exist while the child runs"
    connection.send({"ok": True, "result_json": build_policy_result().model_dump_json()})
    connection.close()


def report_failure(connection: Connection, file_path: str, document_kind: str, api_key: str, timeout: float) -> None:
    connection.send({"ok": False, "error_type": "ExtractionError", "detail": "Docling failed: secret internal path /tmp/x"})
    connection.close()


def return_garbage(connection: Connection, file_path: str, document_kind: str, api_key: str, timeout: float) -> None:
    connection.send({"ok": True, "result_json": '{"not": "an extraction result"}'})
    connection.close()


def hang(connection: Connection, file_path: str, document_kind: str, api_key: str, timeout: float) -> None:
    """A parse that never finishes."""
    time.sleep(600)


def crash(connection: Connection, file_path: str, document_kind: str, api_key: str, timeout: float) -> None:
    """Die at once without answering, as a process killed for using too much memory would."""
    os._exit(3)


# --- stand-ins for the claim-document classifier (app/classification/classifier.py) ---

_NAME_HINTS = (
    ("discharge", "discharge_summary"),
    ("bill", "itemised_bill"),
    ("receipt", "payment_receipt"),
    ("report", "investigation_report"),
    ("denial", "denial_letter"),
    ("aadhaar", "id_proof"),
)


def classify_by_file_name(connection: Connection, file_path: str, mime_type: str, api_key: str, timeout: float) -> None:
    """Label a file from its name, so a test controls the answer by naming the upload.

    A name containing "blurry" is answered with low confidence.
    """
    name = Path(file_path).name.lower()
    detected_type = next((label for hint, label in _NAME_HINTS if hint in name), "unknown")
    connection.send(
        {
            "ok": True,
            "detected_type": detected_type,
            "confidence": "low" if "blurry" in name else "high",
            "page_count": 3,
            "snippet": f"first words of {name}",
            "cached": False,
        }
    )
    connection.close()


def classify_fails(connection: Connection, file_path: str, mime_type: str, api_key: str, timeout: float) -> None:
    connection.send({"ok": False, "error_type": "ServerError", "detail": "503 from the model API, key=secret"})
    connection.close()


def classify_returns_an_invented_type(connection: Connection, file_path: str, mime_type: str, api_key: str, timeout: float) -> None:
    connection.send({"ok": True, "detected_type": "claim_form", "confidence": "high", "page_count": 1, "snippet": None})
    connection.close()

