"""Pipeline assembly tests. Docling and Gemini are both monkeypatched out —
these test the field-building/assembly logic (contracts shape, dropped
sub-limits, bill-line-item derivation, placeholder ids, error wrapping),
not the real conversion or extraction calls, which are exercised instead by
scripts/verify_extraction.py against a real PDF and a real API key."""

from __future__ import annotations

from pathlib import Path

import pytest

import pipeline
from docling_wrapper import ParsedDocument
from errors import ExtractionError
from llm_schema import (
    LLMBillExtraction,
    LLMBillLineItem,
    LLMExclusion,
    LLMPolicyExtraction,
    LLMSubLimit,
    LLMWaitingPeriod,
)


def _empty_parsed_document() -> ParsedDocument:
    return ParsedDocument(
        page_count=1, pages={}, text_items=[], tables=[], markdown="", ocr_used=False, warnings=[]
    )


def _patch_docling(monkeypatch: pytest.MonkeyPatch, parsed: ParsedDocument | None = None) -> None:
    monkeypatch.setattr(pipeline, "convert_document", lambda file_path: parsed or _empty_parsed_document())


def _patch_llm(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    monkeypatch.setattr(pipeline, "extract_with_llm", lambda *args, **kwargs: result)


def _touch(path: Path) -> Path:
    path.write_bytes(b"fake pdf bytes")
    return path


def _empty_policy_extraction(**overrides: object) -> LLMPolicyExtraction:
    base = dict(
        sum_insured_raw=None,
        sum_insured_source_text=None,
        co_pay_percent=None,
        co_pay_percent_source_text=None,
        sub_limits=[],
        waiting_periods=[],
        exclusions=[],
        intimation_deadline_hours=None,
        intimation_deadline_hours_source_text=None,
    )
    base.update(overrides)
    return LLMPolicyExtraction(**base)


def test_missing_file_raises_extraction_error(tmp_path: Path) -> None:
    with pytest.raises(ExtractionError, match="does not exist"):
        pipeline.parse_and_extract(tmp_path / "nope.pdf", "policy")


def test_unexpected_exception_is_wrapped_as_extraction_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = _touch(tmp_path / "policy.pdf")
    _patch_docling(monkeypatch)
    _patch_llm(monkeypatch, _empty_policy_extraction())
    monkeypatch.setattr(pipeline, "build_chunks", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(ExtractionError, match="unrecoverable failure.*boom"):
        pipeline.parse_and_extract(file_path, "policy")


def test_placeholder_ids_are_logged_and_used_consistently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = _touch(tmp_path / "policy.pdf")
    _patch_docling(monkeypatch)
    _patch_llm(monkeypatch, _empty_policy_extraction())

    result = pipeline.parse_and_extract(file_path, "policy")

    assert any("PLACEHOLDER IDS" in w for w in result.warnings)
    assert result.coverage_profile is not None
    # policy_id on the profile and document_id used for provenance are
    # deliberately different placeholders — see the pipeline.py docstring.
    assert result.coverage_profile.policy_id is not None


def test_unparseable_money_yields_null_value_and_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = _touch(tmp_path / "policy.pdf")
    _patch_docling(monkeypatch)
    _patch_llm(
        monkeypatch,
        _empty_policy_extraction(sum_insured_raw="see attached annexure", sum_insured_source_text="see annexure"),
    )

    result = pipeline.parse_and_extract(file_path, "policy")

    assert result.coverage_profile is not None
    assert result.coverage_profile.sum_insured.value is None
    assert result.coverage_profile.sum_insured.confidence == "low"
    assert result.coverage_profile.sum_insured.provenance is None
    assert any("could not parse money amount" in w for w in result.warnings)


def test_sub_limit_with_unknown_basis_is_dropped_with_warning(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = _touch(tmp_path / "policy.pdf")
    _patch_docling(monkeypatch)
    _patch_llm(
        monkeypatch,
        _empty_policy_extraction(
            sub_limits=[
                LLMSubLimit(
                    category="room_rent",
                    label="Room Rent",
                    cap_amount_raw="5,00,000/-",
                    cap_basis="unknown",
                    percent_value=None,
                    source_text="5,00,000/-",
                )
            ]
        ),
    )

    result = pipeline.parse_and_extract(file_path, "policy")

    assert result.coverage_profile is not None
    assert result.coverage_profile.sub_limits == []
    assert any("omitted" in w and "cap_basis" in w for w in result.warnings)


def test_sub_limit_with_known_basis_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = _touch(tmp_path / "policy.pdf")
    _patch_docling(monkeypatch)
    _patch_llm(
        monkeypatch,
        _empty_policy_extraction(
            sub_limits=[
                LLMSubLimit(
                    category="icu",
                    label="ICU",
                    cap_amount_raw="1,25,000/-",
                    cap_basis="per_day",
                    percent_value=None,
                    source_text="1,25,000/-",
                )
            ]
        ),
    )

    result = pipeline.parse_and_extract(file_path, "policy")

    assert result.coverage_profile is not None
    assert len(result.coverage_profile.sub_limits) == 1
    sub_limit = result.coverage_profile.sub_limits[0]
    assert sub_limit.cap_basis == "per_day"
    assert sub_limit.cap_amount.value == 12_500_000


def test_extraction_completeness_counts_only_scalar_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = _touch(tmp_path / "policy.pdf")
    _patch_docling(monkeypatch)
    _patch_llm(
        monkeypatch,
        _empty_policy_extraction(
            sum_insured_raw="5,00,000/-",
            sum_insured_source_text="5,00,000/-",
            co_pay_percent=10.0,
            co_pay_percent_source_text="10%",
            # intimation_deadline_hours left null
        ),
    )

    result = pipeline.parse_and_extract(file_path, "policy")

    assert result.coverage_profile is not None
    assert result.coverage_profile.extraction_completeness == pytest.approx(2 / 3)


def test_waiting_period_and_exclusion_assembled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = _touch(tmp_path / "policy.pdf")
    _patch_docling(monkeypatch)
    _patch_llm(
        monkeypatch,
        _empty_policy_extraction(
            waiting_periods=[
                LLMWaitingPeriod(
                    kind="pre_existing", months=36.0, applies_to=None, source_text="36 months of continuous coverage"
                )
            ],
            exclusions=[LLMExclusion(text="Cosmetic surgery is excluded", source_text="cosmetic surgery is excluded")],
        ),
    )

    result = pipeline.parse_and_extract(file_path, "policy")

    assert result.coverage_profile is not None
    assert len(result.coverage_profile.waiting_periods) == 1
    wp = result.coverage_profile.waiting_periods[0]
    assert wp.kind == "pre_existing"
    assert wp.months.value == 36.0
    assert wp.starts_on is None and wp.expires_on is None

    assert len(result.coverage_profile.exclusions) == 1
    assert result.coverage_profile.exclusions[0].value == "Cosmetic surgery is excluded"


def test_bill_line_item_missing_quantity_defaults_to_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = _touch(tmp_path / "bill.pdf")
    _patch_docling(monkeypatch)
    _patch_llm(
        monkeypatch,
        LLMBillExtraction(
            line_items=[
                LLMBillLineItem(
                    description="Consultation fee",
                    quantity=None,
                    rate_raw=None,
                    amount_raw="1,000/-",
                    source_text="Consultation fee 1,000/-",
                )
            ]
        ),
    )

    result = pipeline.parse_and_extract(file_path, "bill")

    assert len(result.line_items) == 1
    item = result.line_items[0]
    assert item.quantity == 1.0
    assert item.amount == 100_000
    assert item.rate == 100_000  # derived: amount / quantity
    assert any("quantity not stated" in w for w in result.warnings)


def test_bill_line_item_with_neither_rate_nor_amount_is_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = _touch(tmp_path / "bill.pdf")
    _patch_docling(monkeypatch)
    _patch_llm(
        monkeypatch,
        LLMBillExtraction(
            line_items=[
                LLMBillLineItem(
                    description="Mystery charge",
                    quantity=1.0,
                    rate_raw=None,
                    amount_raw=None,
                    source_text="Mystery charge",
                )
            ]
        ),
    )

    result = pipeline.parse_and_extract(file_path, "bill")

    assert result.line_items == []
    assert any("dropped" in w and "Mystery charge" in w for w in result.warnings)


def test_bill_line_item_derives_rate_from_amount_and_quantity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = _touch(tmp_path / "bill.pdf")
    _patch_docling(monkeypatch)
    _patch_llm(
        monkeypatch,
        LLMBillExtraction(
            line_items=[
                LLMBillLineItem(
                    description="Syringes",
                    quantity=4.0,
                    rate_raw=None,
                    amount_raw="400/-",
                    source_text="Syringes x4 400/-",
                )
            ]
        ),
    )

    result = pipeline.parse_and_extract(file_path, "bill")

    assert len(result.line_items) == 1
    item = result.line_items[0]
    assert item.amount == 40_000
    assert item.rate == 10_000  # 40000 paise / 4
