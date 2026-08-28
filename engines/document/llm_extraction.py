"""Schema-constrained Gemini Flash extraction over Docling's parsed output.

The model never returns prose: `response_schema` is set to one of the
pydantic models in llm_schema.py, and Gemini is constrained to emit exactly
that JSON shape (google-genai validates it against the schema and raises a
pydantic ValidationError internally if it doesn't match, which surfaces
here as `response.parsed is None` — see the `_from_response` handling in
google.genai.types for how that swallowing works).

PROMPT_VERSION is part of the disk-cache key (cache.py) — bump it whenever
this file's prompt text or llm_schema.py's shape changes, so a cached
response from an old prompt is never silently reused as if it came from the
current one.
"""

from __future__ import annotations

import os
from collections import defaultdict
from pathlib import Path
from typing import Literal

from google import genai
from google.genai import types

import _bootstrap  # noqa: F401 — loads engines/document/.env before GEMINI_MODEL/GEMINI_API_KEY are read below
from cache import DiskCache, build_cache_key
from docling_wrapper import ParsedDocument, TableRecord
from errors import ExtractionError
from llm_schema import LLMBillExtraction, LLMPolicyExtraction

PROMPT_VERSION = "v1"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_SHARED_PREAMBLE = """You are extracting structured facts from an Indian health-insurance \
document that has already been parsed to text and tables. Follow these rules strictly:

- Extract ONLY facts that are actually stated in the document below. Never estimate, infer \
industry-standard defaults, or fill in a plausible-looking number that isn't written down.
- If a field is not stated in the document, set it (and its *_source_text sibling) to null. \
A null is a normal, expected answer — do not guess to avoid it.
- Every non-null value must be accompanied by its `source_text`: the verbatim quote (a cell's \
text, or a sentence) you read it from. Copy it exactly, do not paraphrase it.
- Money fields are raw text (e.g. "5,00,000/-", "1% of Sum Insured"), not numbers you compute — \
copy the amount exactly as written, do not do arithmetic on it.
- Table cells marked [H] are column or row headers, not data. Header TEXT (e.g. "Room Rent \
Limit (per day)") is often the only place a basis like "per day" vs "per claim" is stated — use \
it as context, but do not assume a header's position tells you which column is which; some \
headers in this document repeat the same text across multiple columns because of a merged cell \
in the original PDF.
"""

_POLICY_INSTRUCTIONS = """
Extract, for this policy document: sum insured; co-payment percentage; sub-limits for room \
rent, ICU, procedures, and ambulance (each with its cap amount and basis — per day, per claim, \
per policy year, or percent of sum insured); waiting periods (initial, disease-specific, \
pre-existing-disease, maternity) in months; permanent exclusions; and the claim intimation \
deadline, converted to hours.

Waiting periods are usually stated in prose (glossary and/or exclusions sections), not in a \
table, and the same fact is often repeated in different wording in more than one place — pick \
the clearest statement and quote that one.
"""

_BILL_INSTRUCTIONS = """
Extract every line item from this hospital/medical bill: its description, quantity, per-unit \
rate, and line amount, exactly as billed.
"""


def render_table_for_prompt(table: TableRecord, index: int) -> str:
    """Render one table's cells as a plain-text grid, marking header cells [H].

    Reconstructed from `table_cells` (not the markdown table export) so the
    [H] marker can reflect Docling's own `column_header`/`row_header` flags
    per cell — see SPIKE_NOTES.md finding 4: header text is only reliable as
    *context*, never as a positional column name, and a merged header in the
    source PDF comes back as identical text duplicated across every column
    it spans. Cells are grouped by `start_row_offset_idx` because a
    row-spanning cell only appears once, at its starting row.
    """
    rows: dict[int, list] = defaultdict(list)
    for cell in table.cells:
        rows[cell.start_row_offset_idx].append(cell)

    lines = [f"[Table {index}, page {table.page_no}]"]
    for row_idx in sorted(rows):
        cells_in_row = sorted(rows[row_idx], key=lambda c: c.start_col_offset_idx)
        rendered = []
        for cell in cells_in_row:
            text = " ".join(cell.text.split())
            rendered.append(f"[H]{text}" if (cell.column_header or cell.row_header) else text)
        lines.append(" | ".join(rendered))
    return "\n".join(lines)


def build_prompt(parsed: ParsedDocument, document_kind: Literal["policy", "bill"]) -> str:
    """Markdown (full reading-order text, including Docling's own table
    rendering) plus a per-table cell dump with header cells marked — see
    render_table_for_prompt. The task brief calls for both: markdown alone
    loses the column_header signal, and the table dump alone loses the
    surrounding prose a sub-limit table's row-key ("Sum Insured") often
    needs for context.
    """
    instructions = _POLICY_INSTRUCTIONS if document_kind == "policy" else _BILL_INSTRUCTIONS
    table_dump = "\n\n".join(render_table_for_prompt(table, i) for i, table in enumerate(parsed.tables, start=1))

    sections = [_SHARED_PREAMBLE, instructions, "\n=== DOCUMENT (markdown) ===\n", parsed.markdown]
    if table_dump:
        sections.append("\n=== TABLES (header cells marked [H]) ===\n")
        sections.append(table_dump)
    return "\n".join(sections)


def extract_with_llm(
    file_path: Path,
    document_kind: Literal["policy", "bill"],
    parsed: ParsedDocument,
    cache: DiskCache | None = None,
) -> LLMPolicyExtraction | LLMBillExtraction:
    """Call Gemini Flash with a strict JSON schema, or return a cached result.

    A cache hit makes zero network calls — checked before anything else,
    including before the API key is required, so a fully-cached re-run
    works even without GEMINI_API_KEY set.
    """
    cache = cache if cache is not None else DiskCache()
    schema_cls = LLMPolicyExtraction if document_kind == "policy" else LLMBillExtraction

    cache_key = build_cache_key(file_path, document_kind, PROMPT_VERSION)
    cached = cache.get(cache_key)
    if cached is not None:
        return schema_cls.model_validate(cached)

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ExtractionError("GEMINI_API_KEY is not set in the environment")

    prompt = build_prompt(parsed, document_kind)
    # google-genai wraps its HTTP layer in tenacity internally (already a
    # project dependency via that SDK), but retries are OFF by default
    # (retry_options=None -> a single attempt, no retry loop at all) —
    # not "retries everything indiscriminately". Passing HttpRetryOptions
    # here turns retries on using the SDK's own default status-code
    # allowlist (408, 429, 500, 502, 503, 504 — see google.genai._api_client
    # ._RETRY_HTTP_STATUS_CODES), which already excludes 404 and every
    # other non-retryable 4xx: a retired/mistyped model id fails once and
    # surfaces immediately, exactly as it should, while a rate limit or a
    # transient 5xx gets a few attempts with exponential backoff.
    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=3)),
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema_cls,
                temperature=0.0,
            ),
        )
    except Exception as exc:  # noqa: BLE001 — any transport/API failure becomes a domain error
        raise ExtractionError(f"Gemini extraction call failed: {exc}") from exc

    if response.parsed is None:
        raise ExtractionError(
            f"Gemini response did not match the required schema. Raw response text: {response.text!r}"
        )

    result: LLMPolicyExtraction | LLMBillExtraction = response.parsed  # type: ignore[assignment]
    cache.set(cache_key, result.model_dump(mode="json"))
    return result
