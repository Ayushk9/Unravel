"""remap_ids must leave no placeholder UUID anywhere in the result.

The fixtures below are built with Engine A's real output classes and mimic
what `parse_and_extract` returns: one placeholder document id on every
provenance and chunk, a different placeholder policy id, random uuid4 ids
on chunks and line items, and the "PLACEHOLDER IDS" warning that spells the
placeholders out as text.
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.core.ids import new_id
from app.services.extraction_mapper import PlaceholderIdError, find_uuids, remap_ids
from contracts.models import (
    BillLineItem,
    CoverageProfile,
    DocumentChunk,
    Extracted,
    ExtractionResult,
    Provenance,
    SubLimit,
    WaitingPeriod,
)


def _extracted(value: object, placeholder_document_id: UUID, page: int = 1) -> Extracted:
    provenance = Provenance(document_id=placeholder_document_id, page=page, bbox=(0.1, 0.2, 0.3, 0.4), snippet="x")
    return Extracted(value=value, confidence="high", provenance=provenance)


def _policy_result() -> ExtractionResult:
    placeholder_document_id = uuid4()
    placeholder_policy_id = uuid4()
    profile = CoverageProfile(
        policy_id=placeholder_policy_id,
        sum_insured=_extracted(50_000_000, placeholder_document_id),
        co_pay_percent=_extracted(10.0, placeholder_document_id, page=2),
        sub_limits=[
            SubLimit(
                category="room_rent",
                label="Room rent",
                cap_amount=_extracted(500_000, placeholder_document_id, page=10),
                cap_basis="per_day",
                percent_value=None,
            )
        ],
        waiting_periods=[
            WaitingPeriod(
                kind="pre_existing",
                months=_extracted(36.0, placeholder_document_id, page=18),
                applies_to=None,
                starts_on=None,
                expires_on=None,
            )
        ],
        exclusions=[_extracted("Cosmetic surgery is excluded", placeholder_document_id, page=20)],
        # A field the parser could not find: no provenance at all.
        intimation_deadline_hours=Extracted(value=None, confidence="low", provenance=None),
        extraction_completeness=2 / 3,
    )
    return ExtractionResult(
        page_count=48,
        coverage_profile=profile,
        line_items=[],
        chunks=[
            DocumentChunk(id=uuid4(), document_id=placeholder_document_id, page=1, text="Schedule", bbox=None),
            DocumentChunk(id=uuid4(), document_id=placeholder_document_id, page=2, text="Co-pay", bbox=(0, 0, 1, 1)),
        ],
        warnings=[
            f"PLACEHOLDER IDS: document_id={placeholder_document_id} used on every Provenance/DocumentChunk, "
            f"policy_id={placeholder_policy_id} used on CoverageProfile.",
            "sub-limit 'ICU' omitted: basis could not be determined",
        ],
    )


def _bill_result() -> ExtractionResult:
    placeholder_document_id = uuid4()
    return ExtractionResult(
        page_count=2,
        coverage_profile=None,
        line_items=[
            BillLineItem(
                id=uuid4(),
                description="Surgical gloves",
                quantity=1.0,
                rate=420_000,
                amount=420_000,
                provenance=Provenance(document_id=placeholder_document_id, page=1, bbox=None, snippet=None),
            ),
            BillLineItem(id=uuid4(), description="OT charges", quantity=1.0, rate=1, amount=1, provenance=None),
        ],
        chunks=[DocumentChunk(id=uuid4(), document_id=placeholder_document_id, page=1, text="Bill", bbox=None)],
        warnings=[f"PLACEHOLDER IDS: document_id={placeholder_document_id} used on every Provenance/DocumentChunk"],
    )


def test_no_placeholder_uuid_survives_for_a_policy() -> None:
    result = _policy_result()
    placeholders = find_uuids(result)
    document_id, policy_id = new_id(), new_id()

    remapped = remap_ids(result, document_id=document_id, policy_id=policy_id)

    # 2 placeholders + 2 chunk ids. If this is lower the fixture is not
    # exercising what it claims to.
    assert len(placeholders) == 4
    assert find_uuids(remapped).isdisjoint(placeholders)


def test_no_placeholder_uuid_survives_for_a_bill() -> None:
    result = _bill_result()
    placeholders = find_uuids(result)
    document_id = new_id()

    remapped = remap_ids(result, document_id=document_id, policy_id=None)

    assert len(placeholders) == 4  # 1 placeholder + 2 line item ids + 1 chunk id
    assert find_uuids(remapped).isdisjoint(placeholders)


def test_every_remaining_uuid_is_a_real_or_freshly_issued_id() -> None:
    document_id, policy_id = new_id(), new_id()

    remapped = remap_ids(_policy_result(), document_id=document_id, policy_id=policy_id)

    chunk_ids = {chunk.id for chunk in remapped.chunks}
    assert find_uuids(remapped) == {document_id, policy_id} | chunk_ids
    assert all(chunk_id.version == 7 for chunk_id in chunk_ids)


def test_real_ids_land_in_every_expected_place() -> None:
    document_id, policy_id = new_id(), new_id()

    remapped = remap_ids(_policy_result(), document_id=document_id, policy_id=policy_id)
    profile = remapped.coverage_profile

    assert profile is not None
    assert profile.policy_id == policy_id
    assert profile.sum_insured.provenance.document_id == document_id
    assert profile.co_pay_percent.provenance.document_id == document_id
    assert profile.sub_limits[0].cap_amount.provenance.document_id == document_id
    assert profile.waiting_periods[0].months.provenance.document_id == document_id
    assert profile.exclusions[0].provenance.document_id == document_id
    assert profile.intimation_deadline_hours.provenance is None
    assert all(chunk.document_id == document_id for chunk in remapped.chunks)


def test_line_items_get_new_v7_ids_and_real_document_id() -> None:
    result = _bill_result()
    document_id = new_id()

    remapped = remap_ids(result, document_id=document_id, policy_id=None)

    assert [item.id.version for item in remapped.line_items] == [7, 7]
    assert remapped.line_items[0].provenance.document_id == document_id
    assert remapped.line_items[1].provenance is None


def test_everything_except_ids_is_unchanged() -> None:
    result = _policy_result()

    remapped = remap_ids(result, document_id=new_id(), policy_id=new_id())

    assert remapped.page_count == result.page_count
    assert remapped.coverage_profile.sum_insured.value == 50_000_000
    assert remapped.coverage_profile.sum_insured.confidence == "high"
    assert remapped.coverage_profile.sum_insured.provenance.page == 1
    assert remapped.coverage_profile.sum_insured.provenance.bbox == (0.1, 0.2, 0.3, 0.4)
    assert remapped.coverage_profile.sub_limits[0].cap_basis == "per_day"
    assert [chunk.text for chunk in remapped.chunks] == ["Schedule", "Co-pay"]


def test_placeholder_warning_is_dropped_and_other_warnings_kept() -> None:
    remapped = remap_ids(_policy_result(), document_id=new_id(), policy_id=new_id())

    assert remapped.warnings == ["sub-limit 'ICU' omitted: basis could not be determined"]


def test_input_is_not_modified() -> None:
    result = _policy_result()
    before = result.model_dump_json()

    remap_ids(result, document_id=new_id(), policy_id=new_id())

    assert result.model_dump_json() == before


def test_missing_policy_id_for_a_policy_result_is_rejected() -> None:
    with pytest.raises(ValueError, match="policy_id is required"):
        remap_ids(_policy_result(), document_id=new_id(), policy_id=None)


def test_a_placeholder_hidden_in_text_is_refused() -> None:
    """A placeholder that slips through anywhere stops the result being stored."""
    result = _policy_result()
    placeholder = result.coverage_profile.policy_id
    result.warnings.append(f"some later note that mentions {placeholder}")

    with pytest.raises(PlaceholderIdError):
        remap_ids(result, document_id=new_id(), policy_id=new_id())
