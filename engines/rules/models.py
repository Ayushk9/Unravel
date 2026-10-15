"""The engine's input and output types."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from contracts.models import CoverageProfile, Provenance

Confidence = Literal["high", "medium", "low"]
Status = Literal["satisfied", "at_risk", "failed", "unknown"]
Band = Literal["likely_eligible", "at_risk", "likely_ineligible", "insufficient_information"]
DocumentType = Literal[
    "policy_schedule",
    "policy_wording",
    "discharge_summary",
    "itemised_bill",
    "payment_receipt",
    "investigation_report",
    "denial_letter",
    "id_proof",
    "unknown",
]
# A value a rule used: a date, a whole number (months, days, hours, paise), a yes/no, or text.
Value = date | int | bool | str | None


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyFacts(_Model):
    """What the engine knows about a policy beyond its coverage profile."""

    policy_id: UUID
    start_date: date | None
    end_date: date | None
    # The start of continuous cover, if the user gave it. Waiting periods are
    # counted from it, or from start_date when it is None (dates.waiting_clock).
    first_inception_date: date | None = None


class ClaimFacts(_Model):
    """Facts about one claim. All of them come from the user or the event log, never from a guess."""

    claim_id: UUID
    admitted_on: date | None
    claimed_amount: int | None  # paise
    # When the claim was intimated: the `intimated` event's occurred_at.
    intimated_at: datetime | None
    condition_is_pre_existing: bool | None
    first_diagnosed_on: date | None
    # Positions in the policy's waiting_periods / exclusions lists that the user
    # says apply. None: not answered. Empty: the user says none apply.
    matched_waiting_periods: tuple[int, ...] | None
    matched_exclusions: tuple[int, ...] | None
    planned_room_rent_per_day: int | None  # paise


class EligibilityInput(_Model):
    policy: PolicyFacts
    coverage_profile: CoverageProfile | None
    claim: ClaimFacts


class MissingFact(_Model):
    fact: str
    where_to_get: str
    # A document type from the contract, when one of them would provide the fact.
    resolving_document: DocumentType | None


class CheckResult(_Model):
    id: str
    title: str
    critical: bool
    status: Status
    confidence: Confidence
    # The structured values the explanation is rendered from.
    values: dict[str, Value]
    explanation: str
    governing_clause: Provenance | None
    missing_facts: tuple[MissingFact, ...]


class Assessment(_Model):
    band: Band
    # Ordered: missing facts first for insufficient information, otherwise failed, at risk, unknown, satisfied.
    checks: tuple[CheckResult, ...]
    precedent_note: str


CityTier = Literal["metro", "tier_2", "other"]
AlertKind = Literal["room_rent_below_market", "waiting_period_expiring", "renewal_due", "no_maternity_cover", "low_sum_insured"]


class AlertInput(_Model):
    policy: PolicyFacts
    coverage_profile: CoverageProfile | None
    household_member_count: int
    # The kind of city the household lives in, as the user chose it. None: not told,
    # and the room-rent alert is skipped.
    household_city_tier: CityTier | None = None


class AlertResult(_Model):
    id: str
    policy_id: UUID
    kind: AlertKind
    severity: Literal["info", "warning", "critical"]
    title: str
    explanation: str
    suggested_action: str | None
    reference_source: str | None
    triggers_on: date | None
    # False when the alert relies on reference figures nobody has checked yet.
    verified: bool
    provenance: Provenance | None


class SkippedAlert(_Model):
    kind: AlertKind
    policy_id: UUID
    reason: str


class AlertsOutcome(_Model):
    alerts: tuple[AlertResult, ...]
    skipped: tuple[SkippedAlert, ...]
