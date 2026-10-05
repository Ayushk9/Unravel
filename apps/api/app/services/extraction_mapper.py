"""Replace Engine A's placeholder ids with real ones before anything is stored.

Engine A (`parse_and_extract`) is a pure function over a file. It runs
before the document and policy rows exist, so it cannot know their ids and
fills in throwaway UUIDs:

    Provenance.document_id        one placeholder, repeated on every provenance
    DocumentChunk.document_id     the same placeholder
    CoverageProfile.policy_id     a second placeholder
    DocumentChunk.id              a random uuid4 per chunk
    BillLineItem.id               a random uuid4 per line

`remap_ids` returns a copy in which every one of those is replaced: the
first three by the real ids passed in, the last two by new UUIDv7 ids
(D-11). A placeholder that reached the database would be a provenance link
pointing at a document that does not exist, which is the failure rule 1
("no fact without provenance") exists to prevent.

The function is pure: it does not touch the database and does not modify
its input.
"""

from __future__ import annotations

import re
from uuid import UUID

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

from app.core.ids import new_id

_UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

# Engine A adds a warning that spells out its placeholder ids in text. It is
# an instruction to this function, not information for a user, and keeping it
# would carry the placeholders along inside a string.
_PLACEHOLDER_WARNING_PREFIX = "PLACEHOLDER IDS"


class PlaceholderIdError(Exception):
    """A placeholder id survived remapping. This is a bug; nothing may be stored."""


def find_uuids(result: ExtractionResult) -> set[UUID]:
    """Every UUID anywhere in the result, including inside text fields."""
    return {UUID(match) for match in _UUID_PATTERN.findall(result.model_dump_json())}


def remap_ids(result: ExtractionResult, *, document_id: UUID, policy_id: UUID | None) -> ExtractionResult:
    """Return a copy of `result` carrying only real, server-issued ids.

    `policy_id` is None for documents that produce no policy (a bill). It
    is an error to pass None when the result contains a coverage profile.
    """
    if result.coverage_profile is not None and policy_id is None:
        raise ValueError("policy_id is required when the result contains a coverage profile")

    placeholder_ids = find_uuids(result)

    remapped = ExtractionResult(
        page_count=result.page_count,
        coverage_profile=_remap_coverage_profile(result.coverage_profile, document_id, policy_id),
        line_items=[_remap_line_item(item, document_id) for item in result.line_items],
        chunks=[_remap_chunk(chunk, document_id) for chunk in result.chunks],
        warnings=[warning for warning in result.warnings if not warning.startswith(_PLACEHOLDER_WARNING_PREFIX)],
    )

    # The caller may legitimately pass an id that already appears in the
    # input (re-running the mapper on its own output), so those two are
    # not counted as survivors.
    survivors = (find_uuids(remapped) & placeholder_ids) - {document_id, policy_id}
    if survivors:
        raise PlaceholderIdError(f"{len(survivors)} placeholder id(s) survived remapping: {sorted(map(str, survivors))}")
    return remapped


def _remap_provenance(provenance: Provenance | None, document_id: UUID) -> Provenance | None:
    if provenance is None:
        return None
    return provenance.model_copy(update={"document_id": document_id})


def _remap_extracted(extracted: Extracted, document_id: UUID) -> Extracted:
    return extracted.model_copy(update={"provenance": _remap_provenance(extracted.provenance, document_id)})


def _remap_sub_limit(sub_limit: SubLimit, document_id: UUID) -> SubLimit:
    return sub_limit.model_copy(update={"cap_amount": _remap_extracted(sub_limit.cap_amount, document_id)})


def _remap_waiting_period(waiting_period: WaitingPeriod, document_id: UUID) -> WaitingPeriod:
    return waiting_period.model_copy(update={"months": _remap_extracted(waiting_period.months, document_id)})


def _remap_coverage_profile(
    profile: CoverageProfile | None, document_id: UUID, policy_id: UUID | None
) -> CoverageProfile | None:
    if profile is None:
        return None
    return profile.model_copy(
        update={
            "policy_id": policy_id,
            "sum_insured": _remap_extracted(profile.sum_insured, document_id),
            "co_pay_percent": _remap_extracted(profile.co_pay_percent, document_id),
            "intimation_deadline_hours": _remap_extracted(profile.intimation_deadline_hours, document_id),
            "sub_limits": [_remap_sub_limit(sub_limit, document_id) for sub_limit in profile.sub_limits],
            "waiting_periods": [_remap_waiting_period(period, document_id) for period in profile.waiting_periods],
            "exclusions": [_remap_extracted(exclusion, document_id) for exclusion in profile.exclusions],
        }
    )


def _remap_line_item(item: BillLineItem, document_id: UUID) -> BillLineItem:
    return item.model_copy(update={"id": new_id(), "provenance": _remap_provenance(item.provenance, document_id)})


def _remap_chunk(chunk: DocumentChunk, document_id: UUID) -> DocumentChunk:
    return chunk.model_copy(update={"id": new_id(), "document_id": document_id})
