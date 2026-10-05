"""Extracted[T] <-> five columns, and the rule that the parser's value survives."""

from __future__ import annotations

from uuid import UUID

from app.db.models import CoverageProfile as CoverageProfileRow
from app.db.models import Exclusion as ExclusionRow
from app.services.extracted_columns import apply_correction, columns_to_extracted, extracted_to_columns
from contracts.models import Extracted, Provenance

DOCUMENT_ID = UUID("01920000-0000-7000-8000-0000000000d1")


def _sum_insured() -> Extracted[int]:
    return Extracted[int](
        value=50_000_000,
        confidence="medium",
        provenance=Provenance(document_id=DOCUMENT_ID, page=3, bbox=(0.1, 0.2, 0.3, 0.4), snippet="Rs. 5,00,000"),
    )


def test_fresh_field_fills_all_five_columns() -> None:
    columns = extracted_to_columns("sum_insured", _sum_insured())

    assert columns == {
        "sum_insured_value": 50_000_000,
        "sum_insured_confidence": "medium",
        "sum_insured_provenance": {
            "document_id": str(DOCUMENT_ID),
            "page": 3,
            "bbox": [0.1, 0.2, 0.3, 0.4],
            "snippet": "Rs. 5,00,000",
        },
        "sum_insured_original_value": 50_000_000,
        "sum_insured_user_confirmed": False,
    }


def test_columns_exist_on_the_table_model() -> None:
    """The names the helper produces are real columns, so a typo fails here."""
    row = CoverageProfileRow(**extracted_to_columns("sum_insured", _sum_insured()))

    assert row.sum_insured_value == 50_000_000
    assert row.sum_insured_original_value == 50_000_000


def test_round_trip_through_a_row() -> None:
    original = _sum_insured()
    row = CoverageProfileRow(**extracted_to_columns("sum_insured", original))

    assert columns_to_extracted(row, "sum_insured") == original


def test_field_with_no_value_round_trips_as_nulls() -> None:
    not_found = Extracted[str](value=None, confidence="low", provenance=None)
    row = ExclusionRow(**extracted_to_columns("text", not_found))

    assert row.text_value is None
    assert row.text_provenance is None
    assert row.text_original_value is None
    assert columns_to_extracted(row, "text") == not_found


def test_correction_keeps_the_parsers_original_value_and_provenance() -> None:
    row = CoverageProfileRow(**extracted_to_columns("sum_insured", _sum_insured()))
    provenance_before = dict(row.sum_insured_provenance)

    apply_correction(row, "sum_insured", 75_000_000)

    assert row.sum_insured_value == 75_000_000
    assert row.sum_insured_user_confirmed is True
    assert row.sum_insured_original_value == 50_000_000  # what the parser said
    assert row.sum_insured_provenance == provenance_before
    assert row.sum_insured_confidence == "medium"


def test_second_correction_still_keeps_the_original() -> None:
    row = CoverageProfileRow(**extracted_to_columns("sum_insured", _sum_insured()))

    apply_correction(row, "sum_insured", 75_000_000)
    apply_correction(row, "sum_insured", 100_000_000)

    assert row.sum_insured_value == 100_000_000
    assert row.sum_insured_original_value == 50_000_000


def test_corrected_field_reads_back_as_user_confirmed() -> None:
    row = CoverageProfileRow(**extracted_to_columns("sum_insured", _sum_insured()))
    apply_correction(row, "sum_insured", 75_000_000)

    extracted = columns_to_extracted(row, "sum_insured")

    assert extracted.value == 75_000_000
    assert extracted.user_confirmed is True
    assert extracted.provenance.page == 3
