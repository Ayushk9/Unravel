"""Wire shapes for eligibility (contract section 5, plus the D-36 additions)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.schemas.base import ApiModel
from app.schemas.documents import DocumentType
from app.schemas.grievances import OmbudsmanAward
from contracts.models import Provenance

Status = Literal["satisfied", "at_risk", "failed", "unknown"]
Band = Literal["likely_eligible", "at_risk", "likely_ineligible", "insufficient_information"]


class MissingFact(ApiModel):
    fact: str
    where_to_get: str
    resolving_document: DocumentType | None


class EligibilityCheck(ApiModel):
    id: str
    title: str
    status: Status
    explanation: str
    governing_clause: Provenance | None
    # The first of missing_facts, kept for clients built before D-36.
    missing_fact: str | None
    resolving_document: DocumentType | None
    # How far the inputs can be trusted: never a probability (D-36).
    confidence: Literal["high", "medium", "low"]
    # The dates (YYYY-MM-DD), months, days and paise the explanation was built from.
    values: dict[str, str | int | bool | None]
    missing_facts: list[MissingFact]


class EligibilityAssessment(ApiModel):
    claim_id: UUID
    band: Band
    checks: list[EligibilityCheck]
    # Checked awards on the same ground as a failed or at-risk check (D-45); the note says why when empty.
    ombudsman_precedent: list[OmbudsmanAward]
    ombudsman_precedent_note: str | None
    generated_at: datetime


__all__ = ["Band", "EligibilityAssessment", "EligibilityCheck", "MissingFact", "Status", "date"]
