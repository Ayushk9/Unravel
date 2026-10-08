"""missing = required - present, as a pure function."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.claims.completeness import AttachedDocument, compute_completeness
from app.db.models.claim import ADMISSION_TYPES, CLAIM_TYPES
from app.rules.loader import RequiredDocuments, load_required_documents

CLAIM_ID = UUID("01920000-0000-7000-8000-0000000000c1")
RULES = load_required_documents()


def doc(document_type: str | None, confidence: str = "high", user_confirmed: bool = False) -> AttachedDocument:
    return AttachedDocument(document_type=document_type, confidence=confidence, user_confirmed=user_confirmed)


def report(documents: list[AttachedDocument], claim_type: str = "reimbursement", admission_type: str = "emergency"):
    return compute_completeness(CLAIM_ID, claim_type, admission_type, documents, RULES)


def test_no_documents_means_everything_required_is_missing() -> None:
    result = report([])

    assert result.required == ["discharge_summary", "itemised_bill", "payment_receipt", "investigation_report", "id_proof"]
    assert result.present == []
    assert result.missing == result.required
    assert "Missing 5 documents" in result.advisory_note


def test_missing_is_the_set_difference_in_checklist_order() -> None:
    result = report([doc("id_proof"), doc("discharge_summary"), doc("itemised_bill")])

    assert result.present == ["id_proof", "discharge_summary", "itemised_bill"]
    assert result.missing == ["payment_receipt", "investigation_report"]
    assert "Missing 2 documents" in result.advisory_note


def test_nothing_missing_when_all_are_present() -> None:
    result = report([doc(t) for t in RULES.checklist("reimbursement", "emergency")])

    assert result.missing == []
    assert "usually needs are present" in result.advisory_note


def test_two_documents_of_one_type_count_once_and_extras_are_harmless() -> None:
    result = report([doc("itemised_bill"), doc("itemised_bill"), doc("denial_letter")])

    assert result.present == ["itemised_bill", "denial_letter"]
    assert "itemised_bill" not in result.missing


def test_a_user_corrected_label_changes_the_result() -> None:
    """The classifier called a receipt a bill; the user fixes it."""
    as_classified = report([doc("discharge_summary"), doc("itemised_bill"), doc("itemised_bill", confidence="low")])
    after_correction = report([doc("discharge_summary"), doc("itemised_bill"), doc("payment_receipt", confidence="low", user_confirmed=True)])

    assert "payment_receipt" in as_classified.missing
    assert "payment_receipt" not in after_correction.missing
    assert after_correction.present == ["discharge_summary", "itemised_bill", "payment_receipt"]


def test_a_low_confidence_document_still_counts_as_present_but_is_flagged() -> None:
    result = report([doc("discharge_summary", confidence="low")])

    assert "discharge_summary" in result.present and "discharge_summary" not in result.missing
    assert "1 document could only be identified with low confidence" in result.advisory_note


def test_a_low_confidence_document_the_user_confirmed_is_no_longer_flagged() -> None:
    result = report([doc("discharge_summary", confidence="low", user_confirmed=True)])

    assert "low confidence" not in result.advisory_note


def test_unrecognised_documents_are_not_present_and_are_mentioned() -> None:
    result = report([doc("unknown"), doc(None)])

    assert result.present == []
    assert "2 documents could not be recognised" in result.advisory_note


def test_checklist_depends_on_claim_type_and_admission_type() -> None:
    assert report([], "cashless", "emergency").required == ["id_proof", "discharge_summary"]
    assert report([], "cashless", "planned").required == ["id_proof", "investigation_report", "discharge_summary"]


@pytest.mark.parametrize("claim_type", [t for t in CLAIM_TYPES if t != "other"])
@pytest.mark.parametrize("admission_type", [t for t in ADMISSION_TYPES if t != "other"])
def test_every_real_combination_has_a_checklist(claim_type: str, admission_type: str) -> None:
    assert RULES.checklist(claim_type, admission_type)


def test_an_unknown_kind_of_claim_gets_no_checklist_and_says_so() -> None:
    result = report([doc("id_proof")], claim_type="other", admission_type="planned")

    assert result.required == [] and result.missing == []
    assert "don't have a document checklist" in result.advisory_note


def test_report_explains_each_required_document_and_is_marked_unverified() -> None:
    result = report([])

    assert [detail.type for detail in result.required_details] == result.required
    for detail in result.required_details:
        assert detail.description and detail.where_to_get and detail.source.document
    assert result.verified is False
    assert "not yet been verified" in result.advisory_note


def test_a_verified_checklist_is_reported_as_verified() -> None:
    rules = RequiredDocuments.model_validate({**RULES.model_dump(), "verified": True})

    result = compute_completeness(CLAIM_ID, "reimbursement", "emergency", [], rules)

    assert result.verified is True
    assert "not yet been verified" not in result.advisory_note


def test_the_note_never_promises_an_outcome() -> None:
    for documents in ([], [doc(t) for t in RULES.checklist("reimbursement", "emergency")]):
        note = report(documents).advisory_note.lower()
        assert not any(word in note for word in ("will be approved", "guarantee", "eligible", "will be paid"))
