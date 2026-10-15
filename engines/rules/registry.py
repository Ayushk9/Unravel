"""Every rule, in one list. docs/RULES.md is generated from this file.

Each entry says which inputs the rule reads, so the table in RULES.md shows,
for every verdict, exactly what it depends on.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from engines.rules import alerts, eligibility
from engines.rules.models import CheckResult, EligibilityInput


@dataclass(frozen=True)
class EligibilityRule:
    id: str
    title: str
    critical: bool
    reads_extracted: tuple[str, ...]
    reads_facts: tuple[str, ...]
    outcomes: str
    evaluate: Callable[[EligibilityInput], CheckResult]


@dataclass(frozen=True)
class AlertRule:
    kind: str
    severity: str
    reads: tuple[str, ...]
    fires_when: str
    skipped_when: str
    uses_reference_data: bool


ELIGIBILITY_RULES: tuple[EligibilityRule, ...] = (
    EligibilityRule(
        "coverage_profile", "Policy coverage details", True, (), ("policy has a coverage profile",),
        "satisfied when the policy has been read; unknown while it has not", eligibility.coverage_profile_present,
    ),
    EligibilityRule(
        "initial_waiting_period", "Initial waiting period", True,
        ("waiting_periods[initial].months",), ("policy.start_date", "claim.admitted_on"),
        "failed if admitted before start + months; satisfied on or after", eligibility.initial_waiting_period,
    ),
    EligibilityRule(
        "ped_waiting_period", "Pre-existing disease waiting period", True,
        ("waiting_periods[pre_existing].months",),
        ("facts.condition_is_pre_existing", "facts.first_diagnosed_on", "policy.start_date", "claim.admitted_on"),
        "satisfied if not pre-existing or period served; at risk if 'not pre-existing' but diagnosed before the start date; "
        "failed if pre-existing and admitted before start + months; unknown if either fact is missing",
        eligibility.ped_waiting_period,
    ),
    EligibilityRule(
        "disease_specific_waiting_period", "Waiting period for specific conditions", True,
        ("waiting_periods[disease_specific].months",), ("facts.matched_waiting_periods", "policy.start_date", "claim.admitted_on"),
        "satisfied if the user chose none, or every chosen period is served; failed if one is not served; unknown if not answered",
        eligibility.disease_specific_waiting_period,
    ),
    EligibilityRule(
        "permanent_exclusions", "Permanent exclusions", True,
        ("exclusions[i]",), ("facts.matched_exclusions",),
        "satisfied if the user chose none; failed if the user chose one; unknown if not answered",
        eligibility.permanent_exclusions,
    ),
    EligibilityRule(
        "room_rent_sub_limit", "Room rent limit", False,
        ("sub_limits[room_rent].cap_amount", "sub_limits[room_rent].percent_value", "sum_insured"),
        ("facts.planned_room_rent_per_day",),
        "satisfied if rent <= cap; at risk if above (proportionate deduction); percent caps in integer paise",
        eligibility.room_rent_sub_limit,
    ),
    EligibilityRule(
        "claim_intimation", "Telling the insurer in time", False,
        ("intimation_deadline_hours",), ("claim.admitted_on", "the 'intimated' event's occurred_at"),
        "satisfied if intimated by admission date + hours (rounded up to whole days); at risk if later; unknown if the deadline was not extracted",
        eligibility.claim_intimation,
    ),
    EligibilityRule(
        "sum_insured_adequacy", "Amount within the sum insured", False,
        ("sum_insured",), ("claim.claimed_amount",),
        "satisfied if claimed <= sum insured; at risk if above",
        eligibility.sum_insured_adequacy,
    ),
)

ALERT_RULES: tuple[AlertRule, ...] = (
    AlertRule(
        "waiting_period_expiring", "info", ("waiting_periods[*].months", "policy.start_date"),
        f"a waiting period ends within the next {alerts.EXPIRING_WITHIN_DAYS} days",
        "no policy start date, or the period is not in whole months", False,
    ),
    AlertRule(
        "renewal_due", "warning", ("policy.end_date",),
        f"the policy ends within the next {alerts.RENEWAL_WITHIN_DAYS} days", "no policy end date", False,
    ),
    AlertRule(
        "no_maternity_cover", "info", ("waiting_periods[maternity]",),
        "no maternity waiting period was found in the policy's extracted terms", "the policy has not been read", False,
    ),
    AlertRule(
        "low_sum_insured", "info", ("sum_insured", "household member count"),
        "the sum insured is below the reference figure for the household's size", "no sum insured extracted", True,
    ),
    AlertRule(
        "room_rent_below_market", "warning", ("sub_limits[room_rent]", "household city"),
        "the room rent cap is well below the typical rate in the household's city", "no household city is stored (always, for now)", True,
    ),
)
