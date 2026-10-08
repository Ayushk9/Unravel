"""The cheap first-page reader and the classifier's cache. No network, no database."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.classification import classifier
from app.classification.classifier import PROMPT, Classification, classify
from app.classification.pdf_text import read_first_pages, render_first_page_png
from app.db.models.document import DOCUMENT_TYPES


def _pdf_with_text(lines_per_page: list[str]) -> bytes:
    """A small but valid PDF with one line of text on each page."""
    objects: list[bytes] = []
    page_ids = [4 + 2 * i for i in range(len(lines_per_page))]
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page_id, line in zip(page_ids, lines_per_page):
        stream = f"BT /F1 18 Tf 72 720 Td ({line}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {page_id + 1} 0 R "
            f"/Resources << /Font << /F1 3 0 R >> >> >>".encode()
        )
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    body = b"%PDF-1.4\n"
    offsets = []
    for number, content in enumerate(objects, start=1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n".encode() + content + b"\nendobj\n"
    xref_at = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    body += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    return body


@pytest.fixture
def discharge_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "upload.pdf"
    path.write_bytes(_pdf_with_text(["DISCHARGE SUMMARY - Sahyadri Hospital, Pune", "Diagnosis and treatment", "Page three is not read"]))
    return path


def test_only_the_first_two_pages_are_read_and_the_page_count_is_reported(discharge_pdf: Path) -> None:
    text, page_count = read_first_pages(discharge_pdf)

    assert page_count == 3
    assert "DISCHARGE SUMMARY" in text and "Diagnosis and treatment" in text
    assert "Page three" not in text


def test_first_page_can_be_rendered_as_an_image_for_scans(discharge_pdf: Path) -> None:
    assert render_first_page_png(discharge_pdf).startswith(b"\x89PNG\r\n\x1a\n")


def test_the_model_may_only_answer_with_contract_document_types() -> None:
    allowed = Classification.model_json_schema()["properties"]["detected_type"]["enum"]

    assert tuple(allowed) == DOCUMENT_TYPES, "the classifier's label list must be exactly the contract's DocumentType"
    assert "unknown" in allowed, "the escape value for a document it does not recognise"
    assert Classification.model_json_schema()["properties"]["confidence"]["enum"] == ["high", "medium", "low"]
    with pytest.raises(ValueError):
        Classification(detected_type="claim_form", confidence="high")
    for document_type in DOCUMENT_TYPES:
        assert document_type in PROMPT


def test_a_cached_answer_is_returned_without_calling_the_model(discharge_pdf: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engines.document.cache import build_cache_key

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr(classifier, "CACHE_DIR", cache_dir)
    key = build_cache_key(discharge_pdf, "claim_document", f"{classifier.PROMPT_VERSION}:test-model")
    (cache_dir / f"{key}.json").write_text(json.dumps({"detected_type": "discharge_summary", "confidence": "high"}))

    # An empty API key: any attempt to reach the model would fail.
    result = classify(discharge_pdf, "application/pdf", gemini_api_key="", gemini_model="test-model")

    assert result == {
        "detected_type": "discharge_summary",
        "confidence": "high",
        "page_count": 3,
        "snippet": "DISCHARGE SUMMARY - Sahyadri Hospital, Pune Diagnosis and treatment",
        "cached": True,
    }


def test_the_cache_key_changes_with_the_file_and_with_the_prompt_version(discharge_pdf: Path, tmp_path: Path) -> None:
    from engines.document.cache import build_cache_key

    other = tmp_path / "other.pdf"
    other.write_bytes(_pdf_with_text(["ITEMISED BILL"]))
    renamed_copy = tmp_path / "renamed.pdf"
    renamed_copy.write_bytes(discharge_pdf.read_bytes())

    key = build_cache_key(discharge_pdf, "claim_document", "v1")
    assert build_cache_key(renamed_copy, "claim_document", "v1") == key, "same bytes, same key, whatever the name"
    assert build_cache_key(other, "claim_document", "v1") != key
    assert build_cache_key(discharge_pdf, "claim_document", "v2") != key
