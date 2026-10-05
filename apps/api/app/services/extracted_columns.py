"""Convert between an Extracted[T] and its five database columns.

A field called `sum_insured` is stored as:

    sum_insured_value, sum_insured_confidence, sum_insured_provenance,
    sum_insured_original_value, sum_insured_user_confirmed

Three functions, one per moment in a field's life:

    extracted_to_columns   when the parser's result is first stored
    apply_correction       when the user confirms or corrects the value
    columns_to_extracted   when the field is read back for a response
"""

from __future__ import annotations

from typing import Any

from contracts.models import Extracted, Provenance


def extracted_to_columns(prefix: str, extracted: Extracted[Any]) -> dict[str, Any]:
    """Column values for storing a freshly parsed field.

    `_original_value` is set here, to the parser's value, and nowhere else.
    """
    provenance = extracted.provenance.model_dump(mode="json") if extracted.provenance else None
    return {
        f"{prefix}_value": extracted.value,
        f"{prefix}_confidence": extracted.confidence,
        f"{prefix}_provenance": provenance,
        f"{prefix}_original_value": extracted.value,
        f"{prefix}_user_confirmed": extracted.user_confirmed,
    }


def apply_correction(row: Any, prefix: str, value: Any) -> None:
    """Record the user's confirmed or corrected value on a database row (D-15).

    Only `_value` and `_user_confirmed` change. The provenance and the
    parser's original value are deliberately left untouched, so both what
    the parser read and what the user said remain visible.
    """
    setattr(row, f"{prefix}_value", value)
    setattr(row, f"{prefix}_user_confirmed", True)


def columns_to_extracted(row: Any, prefix: str) -> Extracted[Any]:
    """Rebuild the wire-format Extracted[T] from a database row."""
    provenance = getattr(row, f"{prefix}_provenance")
    return Extracted(
        value=getattr(row, f"{prefix}_value"),
        confidence=getattr(row, f"{prefix}_confidence"),
        provenance=Provenance.model_validate(provenance) if provenance else None,
        user_confirmed=getattr(row, f"{prefix}_user_confirmed"),
    )
