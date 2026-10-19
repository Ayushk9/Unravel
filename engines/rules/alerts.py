"""Feature 8: gaps in a household's cover, worked out on every read.

Nothing is stored and nothing runs on a schedule: the alerts for a policy
are a function of the policy, the household and today's date.

An alert that needs an input the system does not have (the household's
kind of city, a policy start date) is not guessed. It is skipped, and the reason is
returned so the caller can log it.

An alert that relies on a reference figure nobody has verified says it is
an estimate and carries verified=False.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import ClassVar

import yaml
from pydantic import BaseModel, ConfigDict, Field

from contracts.models import CoverageProfile

from engines.rules.dates import add_months, format_date, waiting_clock, whole_months
from engines.rules.models import AlertInput, AlertKind, AlertResult, AlertsOutcome, SkippedAlert
from engines.rules.money import format_rupees
from engines.rules.room_rent import NoCap, room_rent_cap

EXPIRING_WITHIN_DAYS = 90
RENEWAL_WITHIN_DAYS = 30
REFERENCE_FILE = Path(__file__).resolve().parent / "reference" / "typical_costs.yaml"


class _Ref(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReferenceSource(_Ref):
    document: str
    section: str | None
    url: str | None
    verified: bool

    # What an alert shows as its source when there is no published source to
    # point at. The `document` text then only describes a working figure; it
    # is not a source and must not be shown as one.
    NO_SOURCE: ClassVar[str] = "none yet, estimate only"

    def shown_as(self) -> str:
        """The alert's `reference_source`: the document only when it has a URL a reader could check."""
        return self.document if self.url else self.NO_SOURCE


class SumInsuredBand(_Ref):
    members_up_to: int = Field(ge=1)
    minimum_paise: int = Field(gt=0)


class Reference(_Ref):
    version: int
    low_sum_insured: tuple[SumInsuredBand, ...]
    low_sum_insured_source: ReferenceSource
    typical_room_rent_per_day: dict[str, int]
    typical_room_rent_source: ReferenceSource

    def minimum_sum_insured(self, members: int) -> int:
        for band in sorted(self.low_sum_insured, key=lambda b: b.members_up_to):
            if members <= band.members_up_to:
                return band.minimum_paise
        return max(self.low_sum_insured, key=lambda b: b.members_up_to).minimum_paise


@lru_cache
def load_reference() -> Reference:
    return Reference.model_validate(yaml.safe_load(REFERENCE_FILE.read_text(encoding="utf-8")))


def _alert_id(kind: AlertKind, data: AlertInput, suffix: str = "") -> str:
    return f"alert-{kind}-{data.policy.policy_id}{suffix}"


def compute_alerts(data: AlertInput, reference: Reference, today: date) -> AlertsOutcome:
    alerts: list[AlertResult] = []
    skipped: list[SkippedAlert] = []
    policy_id = data.policy.policy_id

    def skip(kind: AlertKind, reason: str) -> None:
        skipped.append(SkippedAlert(kind=kind, policy_id=policy_id, reason=reason))

    profile = data.coverage_profile
    _waiting_periods_ending(data, profile, today, alerts, skip)
    _renewal(data, today, alerts, skip)
    if profile is None:
        for kind in ("no_maternity_cover", "low_sum_insured", "room_rent_below_market"):
            skip(kind, "the policy's coverage details have not been read")
    else:
        _maternity(data, profile, alerts)
        _low_sum_insured(data, profile, reference, alerts, skip)
        _room_rent_below_market(data, profile, reference, alerts, skip)
    return AlertsOutcome(alerts=tuple(alerts), skipped=tuple(skipped))


def _waiting_periods_ending(data: AlertInput, profile: CoverageProfile | None, today: date, alerts: list[AlertResult], skip) -> None:
    if profile is None or not profile.waiting_periods:
        return
    clock = waiting_clock(data.policy.start_date, data.policy.first_inception_date)
    if clock is None:
        skip("waiting_period_expiring", "neither the policy start date nor the first inception date is known")
        return
    start = clock.start
    horizon = today + timedelta(days=EXPIRING_WITHIN_DAYS)
    for position, period in enumerate(profile.waiting_periods):
        months = whole_months(period.months.value)
        if months is None:
            continue
        end = add_months(start, months)
        if not today <= end <= horizon:
            continue
        days_left = (end - today).days
        what = {
            "initial": "initial waiting period",
            "pre_existing": "pre-existing disease waiting period",
            "maternity": "maternity waiting period",
            "disease_specific": f"waiting period for {period.applies_to or 'a listed condition'}",
        }.get(period.kind, "waiting period")
        alerts.append(
            AlertResult(
                id=_alert_id("waiting_period_expiring", data, f"-{position}"),
                policy_id=data.policy.policy_id,
                kind="waiting_period_expiring",
                severity="info",
                title=f"Your {what} ends in {days_left} day{'' if days_left == 1 else 's'}",
                explanation=(
                    f"The {months}-month {what} ends on {format_date(end)}. Treatment from that date is no longer "
                    f"held back by it. {clock.note}"
                ),
                suggested_action="If you have been waiting on planned treatment for this, check with your insurer before booking.",
                reference_source=None,
                triggers_on=end,
                verified=True,
                provenance=period.months.provenance,
            )
        )


def _renewal(data: AlertInput, today: date, alerts: list[AlertResult], skip) -> None:
    end = data.policy.end_date
    if end is None:
        skip("renewal_due", "the policy end date is not known")
        return
    if not today <= end <= today + timedelta(days=RENEWAL_WITHIN_DAYS):
        return
    days_left = (end - today).days
    alerts.append(
        AlertResult(
            id=_alert_id("renewal_due", data),
            policy_id=data.policy.policy_id,
            kind="renewal_due",
            severity="warning",
            title=f"Your policy ends in {days_left} day{'' if days_left == 1 else 's'}",
            explanation=(
                f"This policy's current term ends on {format_date(end)}. Renewing before it lapses keeps your "
                "waiting-period clock running; a break in cover can restart it."
            ),
            suggested_action="Renew before the end date.",
            reference_source=None,
            triggers_on=end,
            verified=True,
            provenance=None,
        )
    )


def _maternity(data: AlertInput, profile: CoverageProfile, alerts: list[AlertResult]) -> None:
    if any(period.kind == "maternity" for period in profile.waiting_periods):
        return
    alerts.append(
        AlertResult(
            id=_alert_id("no_maternity_cover", data),
            policy_id=data.policy.policy_id,
            kind="no_maternity_cover",
            severity="info",
            title="We didn't find maternity cover in this policy",
            explanation=(
                "No maternity waiting period was found in your policy's extracted terms. That usually means the "
                "policy does not cover maternity, but it can also mean the clause was not read. Check your policy "
                "wording before relying on this."
            ),
            suggested_action="If you are planning a family, check the policy wording or ask your insurer about maternity cover.",
            reference_source=None,
            triggers_on=None,
            verified=True,
            # Based on an absence, so there is no clause to point at.
            provenance=None,
        )
    )


def _low_sum_insured(data: AlertInput, profile: CoverageProfile, reference: Reference, alerts: list[AlertResult], skip) -> None:
    sum_insured = profile.sum_insured
    if sum_insured.value is None:
        skip("low_sum_insured", "the sum insured was not found in the policy")
        return
    members = max(data.household_member_count, 1)
    minimum = reference.minimum_sum_insured(members)
    if sum_insured.value >= minimum:
        return
    source = reference.low_sum_insured_source
    alerts.append(
        AlertResult(
            id=_alert_id("low_sum_insured", data),
            policy_id=data.policy.policy_id,
            kind="low_sum_insured",
            severity="info",
            title=f"{format_rupees(sum_insured.value)} may not be enough for {members} {'person' if members == 1 else 'people'}",
            explanation=(
                f"Your sum insured is {format_rupees(sum_insured.value)}. As a rough estimate, a household of {members} "
                f"may want at least {format_rupees(minimum)}, because one major hospitalisation can use most of a "
                "smaller cover. This figure is an estimate that has not been checked against a published source."
            ),
            suggested_action="Consider whether a top-up or super top-up policy would suit you.",
            reference_source=source.shown_as(),
            triggers_on=None,
            verified=source.verified,
            provenance=sum_insured.provenance,
        )
    )


def _room_rent_below_market(data: AlertInput, profile: CoverageProfile, reference: Reference, alerts: list[AlertResult], skip) -> None:
    tier = data.household_city_tier
    if tier is None:
        skip("room_rent_below_market", "the household has not said what kind of city it lives in")
        return
    typical = reference.typical_room_rent_per_day.get(tier)
    if typical is None:
        skip("room_rent_below_market", f"there is no typical room rate on file for city tier '{tier}'")
        return
    found = room_rent_cap(profile)
    if isinstance(found, NoCap):
        skip("room_rent_below_market", f"in the policy's extracted terms {found.reason}")
        return
    if found.per_day >= typical:
        return
    source = reference.typical_room_rent_source
    place = {"metro": "a metro city", "tier_2": "a tier-2 city"}[tier]
    alerts.append(
        AlertResult(
            id=_alert_id("room_rent_below_market", data),
            policy_id=data.policy.policy_id,
            kind="room_rent_below_market",
            severity="info",
            title=f"Your room rent cap may be below typical rates in {place}",
            explanation=(
                f"{found.how} As a rough estimate, a private single room in {place} costs about "
                f"{format_rupees(typical)} a day, {format_rupees(typical - found.per_day)} more. If you take a room above "
                "your cap, many policies pay other room-linked charges only in proportion, which can reduce the whole "
                "bill. This figure is an estimate that has not been checked against a published source."
            ),
            suggested_action="Before a planned admission, ask the hospital for a room within your cap, or check what the difference would cost you.",
            reference_source=source.shown_as(),
            triggers_on=None,
            verified=source.verified,
            provenance=found.clause.provenance,
        )
    )
