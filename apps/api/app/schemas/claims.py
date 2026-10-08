"""Wire shapes for claims (docs/claude-code-frontend-prompt.md section 5, plus D-33 and D-35)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from app.schemas.base import ApiModel
from app.schemas.documents import DocumentType

ClaimState = Literal[
    "intimated", "documents_submitted", "under_review", "queried", "approved", "denied", "escalated", "resolved"
]
ClaimType = Literal["cashless", "reimbursement", "other"]
AdmissionType = Literal["planned", "emergency", "other"]
EventSource = Literal["user", "insurer_letter", "system"]
Urgency = Literal["normal", "soon", "critical", "expired"]


class ClaimEvent(ApiModel):
    id: UUID
    claim_id: UUID
    from_state: ClaimState | None
    to_state: ClaimState
    occurred_at: datetime
    note: str | None
    source: EventSource


class RuleSource(ApiModel):
    """Where a rule comes from, so the user (and the examiner) can check it."""

    document: str
    section: str | None
    url: str | None


class Deadline(ApiModel):
    id: str
    label: str
    due_at: datetime
    days_remaining: int
    # The rule in a plain sentence, with the date it was counted from.
    basis: str
    urgency: Urgency
    source: RuleSource | None
    # False until a person has checked the rule against its source. Clients
    # must mark an unverified deadline as such (D-33).
    verified: bool


class OmittedDeadline(ApiModel):
    """A deadline that could not be worked out, and why. Never guessed instead (D-33)."""

    id: str
    label: str
    reason: str


class Claim(ApiModel):
    id: UUID
    policy_id: UUID
    member_id: UUID
    claim_type: ClaimType
    admission_type: AdmissionType
    hospital_name: str
    admitted_on: date | None
    discharged_on: date | None
    claimed_amount: int | None
    settled_amount: int | None
    # A projection of the event log, never stored or set directly (D-16).
    current_state: ClaimState
    # Oldest first.
    events: list[ClaimEvent]
    # Computed on every read from the events and the policy (D-17).
    deadlines: list[Deadline]
    omitted_deadlines: list[OmittedDeadline]


class ClaimCreateRequest(ApiModel):
    policy_id: UUID
    member_id: UUID
    claim_type: ClaimType
    admission_type: AdmissionType
    hospital_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    admitted_on: date | None
    discharged_on: date | None
    # Integer paise. strict: 5000.5 and "5000" are rejected, not rounded.
    claimed_amount: Annotated[int, Field(strict=True, ge=0)] | None

    @model_validator(mode="after")
    def _discharge_not_before_admission(self) -> ClaimCreateRequest:
        if self.admitted_on and self.discharged_on and self.discharged_on < self.admitted_on:
            raise ValueError("discharged_on cannot be before admitted_on")
        return self


class ClaimEventRequest(ApiModel):
    # Any string is accepted here so that an unknown state is answered by the
    # state machine with the list of allowed states, like any other illegal move.
    to_state: str
    # Must carry a UTC offset; a time with no zone is ambiguous (D-12).
    occurred_at: AwareDatetime
    note: Annotated[str, StringConstraints(max_length=2000)] | None


class RequiredDocumentDetail(ApiModel):
    type: DocumentType
    description: str
    where_to_get: str
    source: RuleSource


class CompletenessReport(ApiModel):
    claim_id: UUID
    required: list[DocumentType]
    present: list[DocumentType]
    missing: list[DocumentType]
    advisory_note: str
    # One entry per required type, in the same order as `required` (D-35).
    required_details: list[RequiredDocumentDetail]
    # False until the checklist has been checked against an official source.
    verified: bool
