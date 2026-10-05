"""Shared Pydantic v2 contracts for extraction and policy data."""

from __future__ import annotations

from datetime import date
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


T = TypeVar("T")
BoundingBox = tuple[float, float, float, float]


class ContractModel(BaseModel):
    """Base wire model: snake_case fields only, with no undeclared inputs."""

    model_config = ConfigDict(extra="forbid")


class Extracted(ContractModel, Generic[T]):
    """A value extracted from a document, including its evidence and confidence."""

    value: T | None
    confidence: Literal["high", "medium", "low"]
    provenance: Provenance | None
    user_confirmed: bool = False


class Provenance(ContractModel):
    """The location in an uploaded document from which a value was extracted."""

    document_id: UUID
    page: int = Field(ge=1)
    bbox: BoundingBox | None
    snippet: str | None

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, bbox: BoundingBox | None) -> BoundingBox | None:
        """Require normalised document coordinates when an exact location exists."""
        if bbox is not None and any(coordinate < 0 or coordinate > 1 for coordinate in bbox):
            raise ValueError("bbox coordinates must be normalised between 0 and 1")
        return bbox


Extracted.model_rebuild()


class SubLimit(ContractModel):
    category: Literal["room_rent", "icu", "procedure", "ambulance", "opd", "other"]
    label: str
    cap_amount: Extracted[int]
    cap_basis: Literal["per_day", "per_claim", "per_policy_year", "percent_of_sum_insured", "other"]
    percent_value: float | None


class WaitingPeriod(ContractModel):
    kind: Literal["initial", "disease_specific", "pre_existing", "maternity", "other"]
    months: Extracted[float]
    applies_to: str | None
    starts_on: date | None
    expires_on: date | None


class CoverageProfile(ContractModel):
    policy_id: UUID
    sum_insured: Extracted[int]
    co_pay_percent: Extracted[float]
    sub_limits: list[SubLimit]
    waiting_periods: list[WaitingPeriod]
    exclusions: list[Extracted[str]]
    intimation_deadline_hours: Extracted[float]
    extraction_completeness: float = Field(ge=0, le=1)


class BillLineItem(ContractModel):
    id: UUID
    description: str
    quantity: float
    rate: int
    amount: int
    provenance: Provenance | None


class DocumentChunk(ContractModel):
    id: UUID
    document_id: UUID
    page: int = Field(ge=1)
    text: str
    bbox: BoundingBox | None

    @field_validator("bbox")
    @classmethod
    def validate_bbox(cls, bbox: BoundingBox | None) -> BoundingBox | None:
        """Require normalised document coordinates when an exact location exists."""
        if bbox is not None and any(coordinate < 0 or coordinate > 1 for coordinate in bbox):
            raise ValueError("bbox coordinates must be normalised between 0 and 1")
        return bbox


class ExtractionResult(ContractModel):
    page_count: int = Field(ge=0)
    coverage_profile: CoverageProfile | None
    line_items: list[BillLineItem]
    chunks: list[DocumentChunk]
    warnings: list[str]
