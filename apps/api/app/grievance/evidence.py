"""The evidence checklist of a grievance letter. Deterministic: no model is involved.

Three sources, in this order:

  1. the claim's completeness report: each document this kind of claim
     usually needs, and whether one is attached (app/claims/completeness.py);
  2. the insurer's denial letter, when the claim was denied: the letter
     argues against it, so a copy belongs with the complaint;
  3. documents an eligibility check says would settle a missing fact (its
     `resolving_document`), when not already listed.

An item is `satisfied` when a document of that type is attached to the claim.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.schemas.claims import CompletenessReport
from app.schemas.grievances import EvidenceItem
from engines.rules.models import CheckResult

# Plain names for the contract's document types. Copy, not regulatory data.
DOCUMENT_LABELS = {
    "policy_schedule": "Policy schedule",
    "policy_wording": "Policy wording",
    "discharge_summary": "Discharge summary",
    "itemised_bill": "Itemised hospital bill",
    "payment_receipt": "Payment receipts",
    "investigation_report": "Investigation reports",
    "denial_letter": "Insurer's denial letter",
    "id_proof": "ID proof",
}


def evidence_checklist(report: CompletenessReport, was_denied: bool, checks: Sequence[CheckResult]) -> list[EvidenceItem]:
    present = set(report.present)
    wanted: list[str] = list(report.required)
    if was_denied:
        wanted.append("denial_letter")
    wanted.extend(_resolving_documents(checks))

    items: list[EvidenceItem] = []
    seen: set[str] = set()
    for document_type in wanted:
        if document_type in seen or document_type not in DOCUMENT_LABELS:
            continue
        seen.add(document_type)
        items.append(EvidenceItem(item=f"{DOCUMENT_LABELS[document_type]} attached", satisfied=document_type in present))
    return items


def _resolving_documents(checks: Iterable[CheckResult]) -> list[str]:
    return [
        fact.resolving_document
        for check in checks
        if check.status != "satisfied"
        for fact in check.missing_facts
        if fact.resolving_document is not None
    ]


def enclosures(items: Sequence[EvidenceItem]) -> list[str]:
    """The attached documents, as a letter's enclosures list."""
    return [item.item.removesuffix(" attached") for item in items if item.satisfied]
