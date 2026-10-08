"""Claim documents: upload to a claim, classification, the missing list, correcting a label."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests import fake_workers
from tests.db import ApiTester, Database

PDF = b"%PDF-1.7\nfake pdf body"
DOCUMENT_KEYS = {
    "id", "file_name", "mime_type", "page_count", "uploaded_at", "detected_type",
    "parse_status", "parse_error", "deleted_at", "claim_id",
}


def _new_claim(api: ApiTester, db: Database, claim_type: str = "reimbursement", admission_type: str = "emergency") -> str:
    response = api.post(
        "/claims",
        json={
            "policy_id": str(db.create_policy(api.household_id)),
            "member_id": str(db.create_member(api.household_id)),
            "claim_type": claim_type,
            "admission_type": admission_type,
            "hospital_name": "Sahyadri Hospital",
            "admitted_on": "2026-03-01",
            "discharged_on": None,
            "claimed_amount": None,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _attach(api: ApiTester, claim_id: str, file_name: str) -> dict:
    accepted = api.upload(PDF, key=str(uuid4()), file_name=file_name, claim_id=claim_id)
    assert accepted.status_code == 202, accepted.text
    return accepted.json()


@pytest.fixture(scope="module")
def filed(database: Database) -> SimpleNamespace:
    """A reimbursement claim with three documents attached and classified."""
    api = ApiTester(database, database.create_household())
    # If a claim document ever reached Engine A, this stand-in would crash the job.
    api.use_worker(fake_workers.crash, fake_workers.classify_by_file_name)
    claim_id = _new_claim(api, database)
    jobs = [_attach(api, claim_id, name) for name in ("discharge-summary.pdf", "itemised-bill.pdf", "blurry-bill-or-receipt.pdf")]
    api.finish_jobs()
    documents = api.get(f"/documents?claim_id={claim_id}").json()
    return SimpleNamespace(api=api, db=database, claim_id=claim_id, jobs=jobs, documents=documents)


def test_claim_uploads_are_classified_without_running_the_policy_parser(filed: SimpleNamespace) -> None:
    for accepted in filed.jobs:
        job = filed.api.get(f"/jobs/{accepted['job_id']}").json()
        assert job["status"] == "succeeded", job
        assert job["result"]["policy_id"] is None, "a claim document never creates a policy"
        assert job["kind"] == "parse_document"
    assert filed.db.scalar(
        "SELECT count(*) FROM policy p JOIN document d ON d.id = p.source_document_id WHERE d.claim_id = :c", c=filed.claim_id
    ) == 0


def test_documents_for_a_claim_come_back_typed_with_confidence_and_provenance(filed: SimpleNamespace) -> None:
    listing = filed.documents

    assert set(listing) == {"items", "next_cursor", "total"}
    assert listing["total"] == 3 and listing["next_cursor"] is None
    assert [d["detected_type"]["value"] for d in listing["items"]] == ["discharge_summary", "itemised_bill", "itemised_bill"]
    assert [d["detected_type"]["confidence"] for d in listing["items"]] == ["high", "high", "low"]
    for document in listing["items"]:
        assert set(document) == DOCUMENT_KEYS
        assert document["claim_id"] == filed.claim_id and document["parse_status"] == "parsed"
        assert document["page_count"] == 3
        detected = document["detected_type"]
        assert set(detected) == {"value", "confidence", "provenance", "user_confirmed"}
        assert detected["user_confirmed"] is False
        assert detected["provenance"]["document_id"] == document["id"] and detected["provenance"]["page"] == 1


def test_completeness_is_required_minus_present_and_flags_low_confidence(filed: SimpleNamespace) -> None:
    response = filed.api.post(f"/claims/{filed.claim_id}/completeness")

    assert response.status_code == 200
    report = response.json()
    assert set(report) == {"claim_id", "required", "present", "missing", "advisory_note", "required_details", "verified"}
    assert report["required"] == ["discharge_summary", "itemised_bill", "payment_receipt", "investigation_report", "id_proof"]
    assert report["present"] == ["discharge_summary", "itemised_bill"]
    assert report["missing"] == ["payment_receipt", "investigation_report", "id_proof"]
    assert report["verified"] is False
    assert "Missing 3 documents" in report["advisory_note"]
    assert "1 document could only be identified with low confidence" in report["advisory_note"]
    assert [d["type"] for d in report["required_details"]] == report["required"]
    assert all(set(d) == {"type", "description", "where_to_get", "source"} for d in report["required_details"])


def test_correcting_a_label_changes_the_missing_list_and_keeps_the_classifiers_answer(filed: SimpleNamespace) -> None:
    blurry = filed.documents["items"][2]

    response = filed.api.patch(f"/documents/{blurry['id']}", json={"detected_type": "payment_receipt"})

    assert response.status_code == 200
    corrected = response.json()["detected_type"]
    assert corrected["value"] == "payment_receipt" and corrected["user_confirmed"] is True
    assert corrected["provenance"] == blurry["detected_type"]["provenance"]

    row = filed.db.execute(
        "SELECT detected_type_value, detected_type_original_value, detected_type_confidence, detected_type_user_confirmed "
        "FROM document WHERE id = :d", d=blurry["id"],
    )[0]
    assert tuple(row) == ("payment_receipt", "itemised_bill", "low", True), "the classifier's answer and confidence are kept"

    report = filed.api.post(f"/claims/{filed.claim_id}/completeness").json()
    assert report["present"] == ["discharge_summary", "itemised_bill", "payment_receipt"]
    assert report["missing"] == ["investigation_report", "id_proof"]
    assert "low confidence" not in report["advisory_note"], "a label the user set is no longer flagged for checking"


def test_a_label_outside_the_contract_is_422(filed: SimpleNamespace) -> None:
    response = filed.api.patch(f"/documents/{filed.documents['items'][0]['id']}", json={"detected_type": "claim_form"})

    assert response.status_code == 422
    assert response.json()["error"]["field_errors"][0]["field"] == "detected_type"


def test_documents_are_listed_one_page_at_a_time_with_a_cursor(filed: SimpleNamespace) -> None:
    first = filed.api.get(f"/documents?claim_id={filed.claim_id}&limit=2").json()
    second = filed.api.get(f"/documents?claim_id={filed.claim_id}&limit=2&cursor={first['next_cursor']}").json()

    assert len(first["items"]) == 2 and first["next_cursor"] == first["items"][-1]["id"] and first["total"] == 3
    assert len(second["items"]) == 1 and second["next_cursor"] is None
    ids = [d["id"] for d in first["items"] + second["items"]]
    assert ids == [d["id"] for d in filed.documents["items"]], "no document skipped or repeated across pages"
    assert filed.api.get("/documents?limit=0").status_code == 422
    assert filed.api.get("/documents?cursor=not-a-cursor").status_code == 422


def test_policy_documents_are_not_mixed_into_a_claims_documents(filed: SimpleNamespace) -> None:
    everything = filed.api.get("/documents?limit=100").json()

    with_claim = [d for d in everything["items"] if d["claim_id"] == filed.claim_id]
    without_claim = [d for d in everything["items"] if d["claim_id"] is None]
    assert len(with_claim) == 3
    assert len(without_claim) == 1, "the policy's own source document"


def test_deleting_a_document_hides_it_and_updates_the_missing_list(api: ApiTester, db: Database) -> None:
    claim_id = _new_claim(api, db, claim_type="cashless", admission_type="emergency")
    _attach(api, claim_id, "aadhaar.pdf")
    _attach(api, claim_id, "discharge-summary.pdf")
    api.finish_jobs()
    documents = api.get(f"/documents?claim_id={claim_id}").json()["items"]
    assert api.post(f"/claims/{claim_id}/completeness").json()["missing"] == []

    deleted = api.delete(f"/documents/{documents[0]['id']}")

    assert deleted.status_code == 204 and deleted.content == b""
    assert api.get(f"/documents/{documents[0]['id']}").status_code == 404
    assert [d["id"] for d in api.get(f"/documents?claim_id={claim_id}").json()["items"]] == [documents[1]["id"]]
    assert api.post(f"/claims/{claim_id}/completeness").json()["missing"] == ["id_proof"]
    # Soft delete (D-20): the row and its file are still there.
    assert db.scalar("SELECT deleted_at IS NOT NULL FROM document WHERE id = :d", d=documents[0]["id"]) is True
    assert len(api.storage.objects) == 2
    assert api.delete(f"/documents/{documents[0]['id']}").status_code == 404


def test_an_unrecognised_document_is_stored_as_unknown_and_does_not_count_as_present(api: ApiTester, db: Database) -> None:
    claim_id = _new_claim(api, db)
    _attach(api, claim_id, "holiday-photo.pdf")
    api.finish_jobs()

    (document,) = api.get(f"/documents?claim_id={claim_id}").json()["items"]
    report = api.post(f"/claims/{claim_id}/completeness").json()

    assert document["detected_type"]["value"] == "unknown"
    assert report["present"] == []
    assert "1 document could not be recognised" in report["advisory_note"]


@pytest.mark.parametrize("worker", [fake_workers.classify_fails, fake_workers.classify_returns_an_invented_type])
def test_a_failed_classification_ends_the_job_with_a_readable_message(api: ApiTester, db: Database, worker) -> None:
    api.use_worker(fake_workers.crash, worker)
    claim_id = _new_claim(api, db)

    accepted = _attach(api, claim_id, "discharge-summary.pdf")
    api.finish_jobs()

    job = api.get(f"/jobs/{accepted['job_id']}").json()
    assert job["status"] == "failed" and job["error"].endswith(".")
    assert "secret" not in job["error"] and "503" not in job["error"] and "claim_form" not in job["error"]
    (document,) = api.get(f"/documents?claim_id={claim_id}").json()["items"]
    assert document["parse_status"] == "failed" and document["detected_type"]["value"] is None
    # A document that could not be labelled is neither present nor guessed at.
    assert api.post(f"/claims/{claim_id}/completeness").json()["present"] == []


def test_an_image_can_be_attached_to_a_claim(api: ApiTester, db: Database) -> None:
    claim_id = _new_claim(api, db)

    accepted = api.upload(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, key=str(uuid4()), file_name="aadhaar.png", content_type="image/png", claim_id=claim_id)
    api.finish_jobs()

    assert accepted.status_code == 202
    (document,) = api.get(f"/documents?claim_id={claim_id}").json()["items"]
    assert document["mime_type"] == "image/png" and document["detected_type"]["value"] == "id_proof"
