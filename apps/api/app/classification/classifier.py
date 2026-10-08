"""Decide what kind of document a claim upload is. Runs in a child process.

One Gemini call per document, and only when the answer is not already cached:

  1. Take the text of the first two pages (app/classification/pdf_text.py).
     If there is none (a scan), or the upload is a photo, send the image
     of the first page instead.
  2. Ask the model to pick one label from a fixed list.

The model is constrained to a JSON schema with exactly two fields, each
limited to a fixed set of values. It cannot answer in prose, and it cannot
invent a document type: anything it does not recognise must be "unknown".

This is perception only. The label decides nothing by itself: it feeds the
missing-document list, which the user can see and correct, and the
classifier's original answer is kept when they do.

CONFIDENCE comes from the model here, unlike Engine A, where confidence is
computed from how well a value matched the page. There is no such match to
measure for a whole-document label, so the model's own statement is the only
signal available. Treat it as a hint about when to ask the user to check.

Results are cached on disk by file content hash and prompt version (the same
scheme, and the same code, as Engine A). Uploading the same file again makes
no API call. Changing the prompt or the label list must bump PROMPT_VERSION.
"""

from __future__ import annotations

import signal
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from app.classification.pdf_text import read_first_pages, render_first_page_png

PROMPT_VERSION = "v1"
CACHE_DIR = Path(__file__).resolve().parents[2] / ".cache" / "classification"

# Below this, a PDF is treated as having no usable text layer.
MIN_TEXT_CHARACTERS = 40
# The first part of the text is enough to recognise a document; no need to
# send (or pay for) more.
MAX_TEXT_CHARACTERS = 6000
SNIPPET_CHARACTERS = 160
_SELF_DESTRUCT_MARGIN_SECONDS = 30

PDF_CONTENT_TYPE = "application/pdf"


class Classification(BaseModel):
    """The only shape the model is allowed to return."""

    detected_type: Literal[
        "policy_schedule",
        "policy_wording",
        "discharge_summary",
        "itemised_bill",
        "payment_receipt",
        "investigation_report",
        "denial_letter",
        "id_proof",
        "unknown",
    ]
    confidence: Literal["high", "medium", "low"]


PROMPT = """You are sorting documents that an Indian health-insurance policyholder has uploaded for a claim.
Decide which ONE of these types the document is:

- policy_schedule: the insurer's schedule or certificate for a policy (policy number, insured persons, sum insured, period).
- policy_wording: the terms and conditions booklet of a policy.
- discharge_summary: a hospital's summary of an admission (diagnosis, treatment, admission and discharge dates).
- itemised_bill: a hospital bill listing charges line by line.
- payment_receipt: a receipt showing that money was paid.
- investigation_report: a lab, pathology, radiology or other test report.
- denial_letter: a letter from an insurer or TPA rejecting or repudiating a claim.
- id_proof: a government identity document (Aadhaar, PAN, passport, driving licence, voter ID).
- unknown: none of the above, or you cannot tell.

Rules:
- Judge only from what is in the document. Do not guess from what a claim usually contains.
- If it does not clearly match one type, answer "unknown". "unknown" is a normal, expected answer.
- confidence is how sure you are of the type: "high" when the document plainly states what it is,
  "medium" when it fits one type but is not explicit, "low" when you are choosing between types or the
  content is hard to read.
"""


def run_classification(
    connection: Connection,
    file_path: str,
    mime_type: str,
    gemini_api_key: str,
    gemini_model: str,
    timeout_seconds: float,
) -> None:
    """Child entry point: classify one file and send back a small dict."""
    # Same self-destruct timer as the parse worker: if the server that
    # started this process is killed, the process still ends by itself.
    if hasattr(signal, "SIGALRM"):
        signal.alarm(int(timeout_seconds) + _SELF_DESTRUCT_MARGIN_SECONDS)
    try:
        connection.send({"ok": True, **classify(Path(file_path), mime_type, gemini_api_key, gemini_model)})
    except Exception as exc:  # noqa: BLE001 - every failure must be reported to the parent, not lost
        connection.send({"ok": False, "error_type": type(exc).__name__, "detail": str(exc)})
    finally:
        connection.close()


def classify(file_path: Path, mime_type: str, gemini_api_key: str, gemini_model: str) -> dict[str, object]:
    # Engine A's cache: one JSON file per key, standard library only.
    from engines.document.cache import DiskCache, build_cache_key

    if mime_type == PDF_CONTENT_TYPE:
        text, page_count = read_first_pages(file_path)
    else:
        text, page_count = "", 1  # a photo is a single page with no text layer
    has_text = len(text) >= MIN_TEXT_CHARACTERS
    snippet = " ".join(text.split())[:SNIPPET_CHARACTERS] if has_text else None

    cache = DiskCache(CACHE_DIR)
    # The model is part of the key: a different model may answer differently.
    cache_key = build_cache_key(file_path, "claim_document", f"{PROMPT_VERSION}:{gemini_model}")
    cached = cache.get(cache_key)
    if cached is not None:
        result = Classification.model_validate(cached)
        return {**result.model_dump(), "page_count": page_count, "snippet": snippet, "cached": True}

    # Imported only when a call is really needed.
    from google import genai
    from google.genai import types

    if has_text:
        contents: list[object] = [PROMPT, "DOCUMENT TEXT (first pages):\n" + text[:MAX_TEXT_CHARACTERS]]
    elif mime_type == PDF_CONTENT_TYPE:
        image = types.Part.from_bytes(data=render_first_page_png(file_path), mime_type="image/png")
        contents = [PROMPT, "The document is a scan. Its first page:", image]
    else:
        image = types.Part.from_bytes(data=file_path.read_bytes(), mime_type=mime_type)
        contents = [PROMPT, "The document is a photo:", image]

    client = genai.Client(
        api_key=gemini_api_key,
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=3)),
    )
    response = client.models.generate_content(
        model=gemini_model,
        contents=contents,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=Classification,
            temperature=0.0,
        ),
    )
    if response.parsed is None:
        raise ValueError("the model's answer did not match the required schema")
    result = Classification.model_validate(response.parsed)

    cache.set(cache_key, result.model_dump())
    return {**result.model_dump(), "page_count": page_count, "snippet": snippet, "cached": False}
