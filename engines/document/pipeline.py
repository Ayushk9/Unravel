"""Engine A public entry point.

`parse_and_extract` is the only public name this module exposes. Everything
else here is a private assembly helper: turn Docling's parsed output plus
Gemini's schema-constrained extraction into the exact contracts.models
shapes the rest of the system expects, with provenance and confidence
computed per provenance.py's rules for every single field.

Three places below fill a contracts/ field this pipeline structurally
cannot know the real value for, because that value is assigned by a part of
the system that runs *after* this one (a database row this function never
sees). Each is a deliberate, logged, conservative choice — not a bug — and
each is called out below and in ExtractionResult.warnings:

  1. Provenance.document_id / DocumentChunk.document_id — this is a pure
     function over a file path, with no document row yet to attach to.
  2. CoverageProfile.policy_id — a Policy row doesn't exist until a later,
     separate API call (`POST /policies`) that hasn't happened yet either.
  3. contracts.models.SubLimit.cap_basis and BillLineItem's plain (non-
     Extracted, non-nullable) money fields have no way to represent "the
     model returned this but we can't classify/parse it" — see
     _build_coverage_profile and _build_line_items for how each is handled
     without ever fabricating a value.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar
from uuid import UUID, uuid4

# Mechanical only — no policy here, that all lives in _bootstrap.py. This
# engine has no package metadata, so when pipeline.py is reached via its
# dotted path (`from engines.document.pipeline import parse_and_extract`,
# exactly how apps/api's job runner imports it) with the repo root as CWD,
# nothing has put engines/document itself on sys.path. Without this, the
# bare `import _bootstrap` right below — and every other bare sibling
# import in this file — fails with ModuleNotFoundError even though the
# files sit right next to this one, because Python only searches sys.path,
# never "next to the currently-importing file", for an absolute import.
# Once this file's own directory is on sys.path, _bootstrap resolves
# normally and does the rest (repo root for `contracts`, plus .env).
_ENGINE_DIR = Path(__file__).resolve().parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

import _bootstrap  # noqa: F401,E402 — puts the repo root on sys.path for `contracts`
from contracts.models import BillLineItem, CoverageProfile, Extracted, ExtractionResult, SubLimit, WaitingPeriod

from chunking import build_chunks
from docling_wrapper import PageInfo, ParsedDocument, convert_document
from errors import ExtractionError
from llm_extraction import extract_with_llm
from llm_schema import LLMBillExtraction, LLMExclusion, LLMPolicyExtraction, LLMSubLimit, LLMWaitingPeriod
from money import MoneyParseError, parse_rupees_to_paise
from provenance import (
    Match,
    build_provenance,
    compute_confidence,
    deduplicate_by_location,
    find_best_match,
    is_spanned_header_column,
)

_T = TypeVar("_T")


def parse_and_extract(file_path: Path, document_kind: Literal["policy", "bill"]) -> ExtractionResult:
    """Parse `file_path` with Docling and extract structured facts with Gemini.

    Raises ExtractionError on unrecoverable failure (bad/missing file,
    Docling conversion failure, Gemini call/schema failure). A field that
    simply couldn't be extracted or matched is not such a failure — it
    comes back as Extracted(value=None, confidence="low", provenance=None)
    inside an otherwise-complete result, per the task's own failure rules.
    """
    if not file_path.exists():
        raise ExtractionError(f"{file_path} does not exist")

    try:
        return _run(file_path, document_kind)
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 — the public contract is "ExtractionResult or ExtractionError", never a raw exception
        raise ExtractionError(f"unrecoverable failure extracting {file_path.name}: {exc}") from exc


def _run(file_path: Path, document_kind: Literal["policy", "bill"]) -> ExtractionResult:
    warnings: list[str] = []

    document_id = uuid4()
    policy_id = uuid4()
    warnings.append(
        f"PLACEHOLDER IDS: document_id={document_id} used on every Provenance/DocumentChunk, "
        f"policy_id={policy_id} used on CoverageProfile. Neither a document row nor a policy row "
        "exists yet at parse time — the caller MUST remap both to the real, database-issued ids "
        "before this result reaches the API. They are not related to each other; do not assume "
        "document_id == policy_id downstream."
    )

    parsed = convert_document(file_path)
    warnings.extend(parsed.warnings)

    llm_result = extract_with_llm(file_path, document_kind, parsed)

    chunks = build_chunks(parsed, document_id, warnings)

    if document_kind == "policy":
        if not isinstance(llm_result, LLMPolicyExtraction):
            raise ExtractionError("internal error: expected a policy extraction result")
        coverage_profile = _build_coverage_profile(llm_result, parsed, document_id, policy_id, warnings)
        line_items: list[BillLineItem] = []
    else:
        if not isinstance(llm_result, LLMBillExtraction):
            raise ExtractionError("internal error: expected a bill extraction result")
        coverage_profile = None
        line_items = _build_line_items(llm_result, parsed, document_id, warnings)

    return ExtractionResult(
        page_count=parsed.page_count,
        coverage_profile=coverage_profile,
        line_items=line_items,
        chunks=chunks,
        warnings=warnings,
    )


@dataclass
class _PendingField:
    """One field's matching inputs, collected in Phase 1 before any
    Match is resolved — see _build_coverage_profile's docstring for why
    matching happens as its own pass, separate from confidence/Provenance
    assembly."""

    source_text: str | None
    value_text: str | None  # raw text of the ACTUAL parsed value, for containment (Fix 1) — None when not applicable


def _numeric_value_text(value: float | None) -> str | None:
    """Digit-comparable text for a float value, without str()'s spurious
    trailing ".0" merging into the digit stream: str(10.0) == "10.0", whose
    digits are "100" — wrong. f"{10.0:g}" == "10", digits "10" — right."""
    return None if value is None else f"{value:g}"


def _parse_money(raw: str | None, warnings: list[str], label: str) -> tuple[int | None, bool]:
    if raw is None:
        return None, False
    try:
        return parse_rupees_to_paise(raw), True
    except MoneyParseError as exc:
        warnings.append(f"{label}: could not parse money amount {raw!r}: {exc}")
        return None, False


def _finalize_extracted(
    value: _T | None,
    value_parsed_cleanly: bool,
    match: Match,
    document_id: UUID,
    pages: dict[int, PageInfo],
    warnings: list[str],
    *,
    basis_from_spanned_header: bool = False,
) -> Extracted[_T]:
    confidence = compute_confidence(
        match=match,
        value_is_present=value is not None,
        value_parsed_cleanly=value_parsed_cleanly,
        basis_from_spanned_header=basis_from_spanned_header,
    )
    provenance = build_provenance(match, document_id, pages, warnings) if value is not None else None
    return Extracted(value=value, confidence=confidence, provenance=provenance)


def _build_coverage_profile(
    llm: LLMPolicyExtraction,
    parsed: ParsedDocument,
    document_id: UUID,
    policy_id: UUID,
    warnings: list[str],
) -> CoverageProfile:
    """Four phases, in order — this shape exists because of Fix 1's
    cross-field uniqueness check (deduplicate_by_location): it needs every
    field's Match at once to spot two fields sharing a (page, bbox), which
    is impossible if each field is matched and finalized in one step, one
    field at a time, the way this used to work.

      1. Parse every raw value into its typed form and record what each
         field should be matched against — independent of provenance.
      2. Match every field against the document (find_best_match, gated
         per Fix 1's validity checks).
      3. Deduplicate across the whole set: no two fields keep a match to
         the same (page, bbox).
      4. Finalize: confidence + Provenance + the contracts object, per
         field, using each field's (possibly demoted) Match from phase 3.
    """
    sum_insured_value, sum_insured_clean = _parse_money(llm.sum_insured_raw, warnings, "sum_insured")

    pending: dict[str, _PendingField] = {
        "sum_insured": _PendingField(llm.sum_insured_source_text, llm.sum_insured_raw),
        "co_pay_percent": _PendingField(llm.co_pay_percent_source_text, _numeric_value_text(llm.co_pay_percent)),
        "intimation_deadline_hours": _PendingField(
            llm.intimation_deadline_hours_source_text, _numeric_value_text(llm.intimation_deadline_hours)
        ),
    }

    sub_limit_rows: list[tuple[str, LLMSubLimit, int | None, bool]] = []
    for i, llm_sub in enumerate(llm.sub_limits):
        # contracts.models.SubLimit.cap_basis has no "unknown"/"other"
        # member, unlike every other enum in the contract (D-06 requires
        # one on all of them — this looks like an oversight, not a
        # deliberate choice). Rather than fabricate a basis —
        # "per_claim" would be a *specific, wrong claim* about how a real
        # rupee cap works, not a neutral default — an undeterminable
        # sub-limit is dropped and counted in warnings. Needs a
        # contracts/ fix (add "unknown" to the Literal) to stop losing
        # these rows.
        if llm_sub.cap_basis == "unknown":
            warnings.append(
                f"sub-limit {llm_sub.label!r} omitted: basis could not be determined from the document, "
                "and contracts.SubLimit.cap_basis has no 'unknown' member to represent that honestly"
            )
            continue
        name = f"sub_limit[{i}:{llm_sub.label}]"
        value, clean = _parse_money(llm_sub.cap_amount_raw, warnings, name)
        pending[name] = _PendingField(llm_sub.source_text, llm_sub.cap_amount_raw)
        sub_limit_rows.append((name, llm_sub, value, clean))

    waiting_period_rows = []
    for i, wp in enumerate(llm.waiting_periods):
        name = f"waiting_period[{i}:{wp.kind}]"
        pending[name] = _PendingField(wp.source_text, _numeric_value_text(wp.months))
        waiting_period_rows.append((name, wp))

    exclusion_rows = []
    for i, exclusion in enumerate(llm.exclusions):
        name = f"exclusion[{i}]"
        pending[name] = _PendingField(exclusion.source_text, None)
        exclusion_rows.append((name, exclusion))

    matches = {name: find_best_match(pf.source_text, parsed, value_text=pf.value_text) for name, pf in pending.items()}
    matches, dedup_warnings = deduplicate_by_location(matches)
    warnings.extend(dedup_warnings)

    sum_insured = _finalize_extracted(
        sum_insured_value, sum_insured_clean, matches["sum_insured"], document_id, parsed.pages, warnings
    )
    co_pay_percent = _finalize_extracted(
        llm.co_pay_percent, True, matches["co_pay_percent"], document_id, parsed.pages, warnings
    )
    intimation_deadline_hours = _finalize_extracted(
        llm.intimation_deadline_hours, True, matches["intimation_deadline_hours"], document_id, parsed.pages, warnings
    )

    sub_limits: list[SubLimit] = []
    for name, llm_sub, value, clean in sub_limit_rows:
        match = matches[name]
        basis_from_spanned_header = (
            match.matched_via == "cell"
            and match.table is not None
            and match.cell is not None
            and is_spanned_header_column(match.table, match.cell)
        )
        cap_amount = _finalize_extracted(
            value, clean, match, document_id, parsed.pages, warnings, basis_from_spanned_header=basis_from_spanned_header
        )
        sub_limits.append(
            SubLimit(
                category=llm_sub.category,
                label=llm_sub.label,
                cap_amount=cap_amount,
                cap_basis=llm_sub.cap_basis,
                percent_value=llm_sub.percent_value,
            )
        )

    waiting_periods: list[WaitingPeriod] = []
    for name, wp in waiting_period_rows:
        months = _finalize_extracted(wp.months, True, matches[name], document_id, parsed.pages, warnings)
        # starts_on/expires_on are left null: the task scopes extraction to
        # "in months" only, and computing actual calendar dates needs the
        # policy's own start date, which belongs to server-side deadline
        # computation (D-17), not this document-level extraction step.
        waiting_periods.append(
            WaitingPeriod(kind=wp.kind, months=months, applies_to=wp.applies_to, starts_on=None, expires_on=None)
        )

    exclusions: list[Extracted[str]] = []
    for name, exclusion in exclusion_rows:
        exclusions.append(_finalize_extracted(exclusion.text, True, matches[name], document_id, parsed.pages, warnings))

    # "Fraction of expected fields that came back non-null" (task section 9)
    # is read here as the three top-level scalar facts every policy has one
    # of. sub_limits/waiting_periods/exclusions are variable-length lists,
    # not a fixed set of "expected fields" a null/non-null ratio applies to
    # cleanly — their extraction quality is already visible in their own
    # per-item confidence and in `warnings` (e.g. dropped sub-limits).
    scalar_fields = (sum_insured, co_pay_percent, intimation_deadline_hours)
    extraction_completeness = sum(1 for f in scalar_fields if f.value is not None) / len(scalar_fields)

    return CoverageProfile(
        policy_id=policy_id,
        sum_insured=sum_insured,
        co_pay_percent=co_pay_percent,
        sub_limits=sub_limits,
        waiting_periods=waiting_periods,
        exclusions=exclusions,
        intimation_deadline_hours=intimation_deadline_hours,
        extraction_completeness=extraction_completeness,
    )


def _build_line_items(
    llm: LLMBillExtraction,
    parsed: ParsedDocument,
    document_id: UUID,
    warnings: list[str],
) -> list[BillLineItem]:
    """contracts.models.BillLineItem's quantity/rate/amount are plain,
    required int/float — not Extracted[T], not nullable — so unlike every
    CoverageProfile field there is no way to represent "couldn't parse
    this" in the row itself, only by dropping the row. A missing quantity
    defaults to 1 (a standard billing convention — an unstated quantity on
    a flat-fee line means one of it — not a fabricated fact about a
    specific number read from the page); a missing rate or amount is
    *derived* from whichever of the two is known once quantity is settled.
    Only when neither rate nor amount can be parsed at all is the line
    dropped, logged, never emitted as a made-up 0.
    """
    items: list[BillLineItem] = []
    for line in llm.line_items:
        rate_value: int | None = None
        amount_value: int | None = None

        if line.rate_raw is not None:
            try:
                rate_value = parse_rupees_to_paise(line.rate_raw)
            except MoneyParseError as exc:
                warnings.append(f"line item {line.description!r}: could not parse rate {line.rate_raw!r}: {exc}")
        if line.amount_raw is not None:
            try:
                amount_value = parse_rupees_to_paise(line.amount_raw)
            except MoneyParseError as exc:
                warnings.append(f"line item {line.description!r}: could not parse amount {line.amount_raw!r}: {exc}")

        if rate_value is None and amount_value is None:
            warnings.append(
                f"line item {line.description!r} dropped: no parseable rate or amount, and "
                "contracts.BillLineItem has no way to represent an unparsed money field"
            )
            continue

        quantity = line.quantity
        if quantity is None:
            quantity = 1.0
            warnings.append(f"line item {line.description!r}: quantity not stated, defaulted to 1")

        if amount_value is None:
            amount_value = round(rate_value * quantity)  # type: ignore[operator]  # rate_value is not None here
        if rate_value is None:
            rate_value = round(amount_value / quantity) if quantity else amount_value

        # value_text prefers amount_raw (the line total is what's usually
        # printed in the row the model quoted) but falls back to rate_raw
        # when only a rate was stated — same Fix 1 containment protection
        # as the coverage-profile fields, so a bill line can't resolve to a
        # different line's amount just because the digit strings are a
        # similar shape.
        match = find_best_match(line.source_text, parsed, value_text=line.amount_raw or line.rate_raw)
        provenance = build_provenance(match, document_id, parsed.pages, warnings)

        items.append(
            BillLineItem(
                id=uuid4(),
                description=line.description,
                quantity=quantity,
                rate=rate_value,
                amount=amount_value,
                provenance=provenance,
            )
        )
    return items
