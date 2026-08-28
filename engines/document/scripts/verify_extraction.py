"""Run Engine A on a PDF and print a field-by-field table for eye-checking
against the open document.

Deliberately does NOT just call pipeline.parse_and_extract() and inspect the
result: contracts.models.Provenance (by design — it's the wire contract, not
a debugging structure) doesn't retain *how* a value was matched (table cell
vs text item vs no match at all), only where it ended up. This script calls
convert_document / extract_with_llm / find_best_match / deduplicate_by_location
directly — the same functions parse_and_extract itself calls, in the same
order (match every field first, THEN deduplicate across all of them) — so
this table matches what the real pipeline produces, not just a per-field
sketch of it. Showing per-field results without the dedup pass would hide
exactly the failure mode Fix 1 exists to catch: two fields quietly sharing
one bbox looks fine field-by-field and only shows up once they're compared
against each other.

Usage:
    .venv/bin/python scripts/verify_extraction.py <pdf_path> <policy|bill>
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tabulate import tabulate  # noqa: E402

from docling_wrapper import convert_document  # noqa: E402
from llm_extraction import extract_with_llm  # noqa: E402
from llm_schema import LLMBillExtraction, LLMPolicyExtraction  # noqa: E402
from provenance import Match, compute_confidence, deduplicate_by_location, find_best_match  # noqa: E402


def _numeric_value_text(value: float | None) -> str | None:
    return None if value is None else f"{value:g}"


@dataclass
class _Row:
    field: str
    value: object
    source_text: str | None
    value_text: str | None


def _fmt_bbox(match: Match) -> str:
    if match.bbox is None or match.page_no is None:
        return "-"
    # Raw (unnormalised) Docling bbox — enough to sanity-check by eye
    # against the source PDF's own point coordinates without needing a
    # second normalisation step in this display script.
    b = match.bbox
    return f"l={b.l:.0f},t={b.t:.0f},r={b.r:.0f},b={b.b:.0f} [{b.coord_origin.value}]"


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[2] not in ("policy", "bill"):
        print("usage: verify_extraction.py <pdf_path> <policy|bill>")
        raise SystemExit(1)

    file_path = Path(sys.argv[1])
    document_kind = sys.argv[2]

    print(f"Converting {file_path.name} with Docling...")
    parsed = convert_document(file_path)
    print(
        f"  {parsed.page_count} pages, {len(parsed.text_items)} text items, "
        f"{len(parsed.tables)} tables, ocr_used={parsed.ocr_used}"
    )
    for warning in parsed.warnings:
        print(f"  [docling warning] {warning}")

    print(f"\nCalling Gemini ({document_kind} extraction) — cached if this exact file was seen before...")
    llm_result = extract_with_llm(file_path, document_kind, parsed)

    pending: list[_Row] = []
    if document_kind == "policy":
        assert isinstance(llm_result, LLMPolicyExtraction)
        pending.append(_Row("sum_insured", llm_result.sum_insured_raw, llm_result.sum_insured_source_text, llm_result.sum_insured_raw))
        pending.append(
            _Row(
                "co_pay_percent",
                llm_result.co_pay_percent,
                llm_result.co_pay_percent_source_text,
                _numeric_value_text(llm_result.co_pay_percent),
            )
        )
        pending.append(
            _Row(
                "intimation_deadline_hours",
                llm_result.intimation_deadline_hours,
                llm_result.intimation_deadline_hours_source_text,
                _numeric_value_text(llm_result.intimation_deadline_hours),
            )
        )
        for i, sub_limit in enumerate(llm_result.sub_limits):
            pending.append(
                _Row(
                    f"sub_limit[{i}:{sub_limit.category}:{sub_limit.label}].cap_amount ({sub_limit.cap_basis})",
                    sub_limit.cap_amount_raw,
                    sub_limit.source_text,
                    sub_limit.cap_amount_raw,
                )
            )
        for i, waiting_period in enumerate(llm_result.waiting_periods):
            pending.append(
                _Row(
                    f"waiting_period[{i}:{waiting_period.kind}].months",
                    waiting_period.months,
                    waiting_period.source_text,
                    _numeric_value_text(waiting_period.months),
                )
            )
        for i, exclusion in enumerate(llm_result.exclusions):
            pending.append(_Row(f"exclusion[{i}]", exclusion.text, exclusion.source_text, None))
    else:
        assert isinstance(llm_result, LLMBillExtraction)
        for i, line in enumerate(llm_result.line_items):
            pending.append(_Row(f"line_item[{i}:{line.description}].amount", line.amount_raw, line.source_text, line.amount_raw or line.rate_raw))
            pending.append(_Row(f"line_item[{i}:{line.description}].rate", line.rate_raw, line.source_text, line.amount_raw or line.rate_raw))

    # Match every field first, then deduplicate across the whole set —
    # mirrors pipeline._build_coverage_profile's phases exactly.
    matches = {row.field: find_best_match(row.source_text, parsed, value_text=row.value_text) for row in pending}
    matches, dedup_warnings = deduplicate_by_location(matches)

    rows: list[list[str]] = []
    for row in pending:
        match = matches[row.field]
        confidence = compute_confidence(match=match, value_is_present=row.value is not None, value_parsed_cleanly=True)
        rows.append(
            [
                row.field,
                "-" if row.value is None else str(row.value)[:40],
                confidence,
                match.matched_via,
                str(match.page_no) if match.page_no is not None else "-",
                _fmt_bbox(match),
                (match.snippet or "")[:50],
            ]
        )

    print()
    print(tabulate(rows, headers=["field", "value", "confidence", "matched-via", "page", "bbox (raw)", "snippet"]))

    if dedup_warnings:
        print("\nprovenance collisions (Fix 1 cross-field dedup):")
        for warning in dedup_warnings:
            print(f"  {warning}")


if __name__ == "__main__":
    main()
