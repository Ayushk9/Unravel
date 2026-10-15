"""Small builders so each test states only what it is about."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from contracts.models import CoverageProfile, Extracted, Provenance, SubLimit, WaitingPeriod

from engines.rules.models import AlertInput, ClaimFacts, EligibilityInput, PolicyFacts

POLICY_ID = UUID("01920000-0000-7000-8000-0000000000a1")
CLAIM_ID = UUID("01920000-0000-7000-8000-0000000000c1")
DOCUMENT_ID = UUID("01920000-0000-7000-8000-0000000000d1")
INDIA_NOON = "T12:00:00+05:30"


def extracted(value, confidence: str = "high", user_confirmed: bool = False, page: int = 3) -> Extracted:
    provenance = Provenance(document_id=DOCUMENT_ID, page=page, bbox=(0.1, 0.1, 0.5, 0.12), snippet=str(value))
    return Extracted(value=value, confidence=confidence, provenance=provenance, user_confirmed=user_confirmed)


def waiting(kind: str, months: float | None, confidence: str = "high", applies_to: str | None = None, user_confirmed: bool = False) -> WaitingPeriod:
    return WaitingPeriod(kind=kind, months=extracted(months, confidence, user_confirmed), applies_to=applies_to, starts_on=None, expires_on=None)


def profile(
    *,
    waiting_periods: list[WaitingPeriod] | None = None,
    sub_limits: list[SubLimit] | None = None,
    exclusions: list[Extracted] | None = None,
    sum_insured: int | None = 50_000_000,
    intimation_hours: float | None = 24.0,
) -> CoverageProfile:
    return CoverageProfile(
        policy_id=POLICY_ID,
        sum_insured=extracted(sum_insured) if sum_insured is not None else Extracted(value=None, confidence="low", provenance=None),
        co_pay_percent=extracted(0.0),
        sub_limits=sub_limits if sub_limits is not None else [],
        waiting_periods=waiting_periods if waiting_periods is not None else [],
        exclusions=exclusions if exclusions is not None else [],
        intimation_deadline_hours=extracted(intimation_hours) if intimation_hours is not None else Extracted(value=None, confidence="low", provenance=None),
        extraction_completeness=1.0,
    )


def room_rent(amount: int | None = 500_000, basis: str = "per_day", percent: float | None = None, confidence: str = "high") -> SubLimit:
    return SubLimit(category="room_rent", label="Room rent", cap_amount=extracted(amount, confidence), cap_basis=basis, percent_value=percent)


def claim(**overrides) -> ClaimFacts:
    values = dict(
        claim_id=CLAIM_ID,
        admitted_on=date(2026, 8, 10),
        claimed_amount=18_500_000,
        intimated_at=datetime.fromisoformat("2026-08-10" + INDIA_NOON),
        condition_is_pre_existing=False,
        first_diagnosed_on=date(2026, 8, 9),
        matched_waiting_periods=(),
        matched_exclusions=(),
        planned_room_rent_per_day=450_000,
    )
    values.update(overrides)
    return ClaimFacts(**values)


def policy(start: date | None = date(2024, 3, 14), end: date | None = date(2027, 3, 13)) -> PolicyFacts:
    return PolicyFacts(policy_id=POLICY_ID, start_date=start, end_date=end)


def eligibility_input(profile_value: CoverageProfile | None = None, claim_value: ClaimFacts | None = None, policy_value: PolicyFacts | None = None) -> EligibilityInput:
    return EligibilityInput(
        policy=policy_value or policy(),
        coverage_profile=profile_value if profile_value is not None else profile(),
        claim=claim_value or claim(),
    )


def alert_input(profile_value: CoverageProfile | None, policy_value: PolicyFacts | None = None, members: int = 4) -> AlertInput:
    return AlertInput(policy=policy_value or policy(), coverage_profile=profile_value, household_member_count=members)
