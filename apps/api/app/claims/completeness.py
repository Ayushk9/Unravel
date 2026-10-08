"""Missing-document detection (Feature 4). A pure function: a set difference.

    missing = required - present

`required` comes from app/rules/required_documents.yaml for this kind of
claim. `present` is the set of document types attached to the claim, using
each document's CURRENT type: the user's correction if they made one,
otherwise the classifier's answer.

A document the classifier was unsure about still counts as present. Telling
the user a document is missing when it is sitting in their list would be
worse than asking them to double-check its label, so low confidence is
reported as a prompt to check, not as an absence.

No verdict is given here, only the list and the reasoning behind it. Whether
a claim is paid is the insurer's decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.rules.loader import RequiredDocuments
from app.schemas.claims import CompletenessReport, RequiredDocumentDetail, RuleSource

UNRECOGNISED = "unknown"


@dataclass(frozen=True)
class AttachedDocument:
    """One classified document on the claim."""

    # Current type: the user's correction when there is one, else the classifier's.
    document_type: str | None
    confidence: str
    user_confirmed: bool


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def compute_completeness(
    claim_id: UUID,
    claim_type: str,
    admission_type: str,
    documents: list[AttachedDocument],
    rules: RequiredDocuments,
) -> CompletenessReport:
    checklist = rules.checklist(claim_type, admission_type)
    required = list(checklist or ())

    # Distinct types, in first-seen order. Unrecognised documents are not a type.
    present: list[str] = []
    for document in documents:
        if document.document_type and document.document_type != UNRECOGNISED and document.document_type not in present:
            present.append(document.document_type)

    missing = [document_type for document_type in required if document_type not in present]

    notes: list[str] = []
    if checklist is None:
        notes.append(
            "We don't have a document checklist for this type of claim, so we can't tell you what is missing. "
            "Ask your insurer which documents they need."
        )
    elif missing:
        notes.append(f"Missing {_plural(len(missing), 'document')} before this claim looks complete.")
    else:
        notes.append("All the documents this type of claim usually needs are present.")

    to_check = sum(1 for d in documents if d.document_type and d.confidence == "low" and not d.user_confirmed)
    if to_check:
        notes.append(
            f"{_plural(to_check, 'document')} could only be identified with low confidence. "
            "Check that the type shown for each is right."
        )
    unrecognised = sum(1 for d in documents if d.document_type in (None, UNRECOGNISED))
    if unrecognised:
        notes.append(f"{_plural(unrecognised, 'document')} could not be recognised. Set the type yourself if you know it.")
    if not rules.verified and checklist is not None:
        notes.append("This checklist has not yet been verified against an official source; your insurer may ask for more.")

    return CompletenessReport(
        claim_id=claim_id,
        required=required,
        present=present,
        missing=missing,
        advisory_note=" ".join(notes),
        required_details=[
            RequiredDocumentDetail(
                type=document_type,
                description=rules.documents[document_type].description,
                where_to_get=rules.documents[document_type].where_to_get,
                source=RuleSource(**rules.documents[document_type].source.model_dump()),
            )
            for document_type in required
        ],
        verified=rules.verified,
    )
