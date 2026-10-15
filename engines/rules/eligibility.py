"""Feature 2: is this claim likely to be paid under this policy, and why?

Each rule is a plain function from the inputs to a CheckResult. Every
result carries:

  status        satisfied | at_risk | failed | unknown
  confidence    the lowest confidence among the inputs it read (confidence.py)
  values        the dates, month counts and amounts it used
  explanation   one sentence rendered from those values, arithmetic visible
  clause        the provenance of the policy field it relied on
  missing facts what would let an `unknown` check be decided, and where to get it

A rule never guesses. When an input is missing, the check is `unknown` and
says exactly which fact is missing.

The overall band is then a fixed function of the checks (band.py).
"""

from __future__ import annotations

from datetime import date

from contracts.models import CoverageProfile, Extracted, WaitingPeriod

from engines.rules.confidence import USER_FACT, lowest, of_extracted
from engines.rules.dates import (
    BOUNDARY_NOTE,
    WaitingClock,
    add_days,
    add_months,
    format_date,
    format_span,
    hours_to_whole_days,
    india_date,
    months_and_days,
    waiting_clock,
    whole_months,
)
from engines.rules.models import CheckResult, ClaimFacts, Confidence, EligibilityInput, MissingFact, PolicyFacts, Status, Value
from engines.rules.money import format_rupees
from engines.rules.room_rent import NoCap, room_rent_cap

# --- facts that may be missing, and where each one comes from ---

POLICY_START = MissingFact(
    fact="Policy start date",
    where_to_get=(
        "Printed on your policy schedule or policy certificate; enter it on the policy page. "
        "If your cover has been renewed without a break, you can give the first policy's start date instead."
    ),
    resolving_document="policy_schedule",
)
ADMISSION_DATE = MissingFact(
    fact="Date of admission",
    where_to_get="On the hospital's discharge summary or admission note.",
    resolving_document="discharge_summary",
)
IS_PRE_EXISTING = MissingFact(
    fact="Whether this illness started before the policy did (a pre-existing condition)",
    where_to_get="Your doctor or your own medical history; answer it on this claim.",
    resolving_document=None,
)
FIRST_DIAGNOSED = MissingFact(
    fact="Date this illness was first diagnosed",
    where_to_get="From the doctor's consultation record or the earliest prescription or test report for it.",
    resolving_document="investigation_report",
)
DISEASE_MATCH = MissingFact(
    fact="Whether this illness is one of the conditions your policy lists with its own waiting period",
    where_to_get="Choose from your policy's list on this claim. Your doctor can confirm the diagnosis.",
    resolving_document=None,
)
EXCLUSION_MATCH = MissingFact(
    fact="Whether this treatment falls under one of your policy's permanent exclusions",
    where_to_get="Choose from your policy's list of exclusions on this claim.",
    resolving_document=None,
)
ROOM_RENT = MissingFact(
    fact="Room rent per day for the room you will use",
    where_to_get="The hospital's room tariff, from the admissions or billing desk.",
    resolving_document="itemised_bill",
)
CLAIMED_AMOUNT = MissingFact(
    fact="Amount being claimed",
    where_to_get="The hospital's estimate or final bill.",
    resolving_document="itemised_bill",
)
INTIMATION_TIME = MissingFact(
    fact="When the insurer was told about the hospitalisation",
    where_to_get="Logged as the claim's first event.",
    resolving_document=None,
)


def policy_term(name: str) -> MissingFact:
    """A term the parser did not find in the policy."""
    return MissingFact(
        fact=f"Your policy's {name}",
        where_to_get="In your policy wording. You can confirm or correct it on the policy page.",
        resolving_document="policy_wording",
    )


def _result(
    *,
    rule_id: str,
    title: str,
    critical: bool,
    status: Status,
    confidence: Confidence,
    explanation: str,
    values: dict[str, Value] | None = None,
    clause: Extracted | None = None,
    missing: tuple[MissingFact, ...] = (),
) -> CheckResult:
    return CheckResult(
        id=rule_id,
        title=title,
        critical=critical,
        status=status,
        confidence=confidence,
        values=values or {},
        explanation=explanation,
        governing_clause=clause.provenance if clause is not None else None,
        missing_facts=missing,
    )


def _waiting_period(profile: CoverageProfile, kind: str) -> WaitingPeriod | None:
    """The waiting period of this kind, if exactly one was extracted."""
    matches = [period for period in profile.waiting_periods if period.kind == kind]
    return matches[0] if len(matches) == 1 else None


def _served_or_not(clock: WaitingClock, months: int, admitted: date) -> tuple[bool, date, dict[str, Value], str]:
    """The arithmetic every waiting-period rule shares.

    Returns: served?, end date, values, and the sentence describing the
    arithmetic. Callers add BOUNDARY_NOTE and the clock's note once (_notes).
    """
    start = clock.start
    end = add_months(start, months)
    served = admitted >= end
    values: dict[str, Value] = {clock.value_key: start, "waiting_months": months, "waiting_period_ends": end, "admitted_on": admitted}
    if served:
        sentence = (
            f"{clock.started}; the {months}-month waiting period ended on {format_date(end)}. "
            f"Your admission on {format_date(admitted)} is on or after that date, so the period has been served."
        )
    else:
        elapsed_months, elapsed_days = months_and_days(start, admitted)
        left_months, left_days = months_and_days(admitted, end)
        values |= {
            "elapsed_months": elapsed_months,
            "elapsed_days": elapsed_days,
            "remaining_months": left_months,
            "remaining_days": left_days,
        }
        if admitted < start:
            sentence = (
                f"{clock.started}; the {months}-month waiting period ends on {format_date(end)}. "
                f"Your admission on {format_date(admitted)} is before that start."
            )
        else:
            sentence = (
                f"{clock.started}; the {months}-month waiting period ends on {format_date(end)}. "
                f"Your admission on {format_date(admitted)} is before that date: "
                f"{format_span(elapsed_months, elapsed_days)} into the waiting period, "
                f"with {format_span(left_months, left_days)} still to run."
            )
    return served, end, values, sentence


def _clock(policy: PolicyFacts) -> WaitingClock | None:
    return waiting_clock(policy.start_date, policy.first_inception_date)


def _notes(clock: WaitingClock) -> str:
    return f"{BOUNDARY_NOTE} {clock.note}"


def _dates_missing(policy: PolicyFacts, claim: ClaimFacts) -> tuple[MissingFact, ...]:
    missing = []
    if _clock(policy) is None:
        missing.append(POLICY_START)
    if claim.admitted_on is None:
        missing.append(ADMISSION_DATE)
    return tuple(missing)


# ----------------------------------------------------------------------- rules


def coverage_profile_present(data: EligibilityInput) -> CheckResult:
    title = "Policy coverage details"
    if data.coverage_profile is None:
        return _result(
            rule_id="coverage_profile",
            title=title,
            critical=True,
            status="unknown",
            confidence="low",
            explanation="This policy's coverage details have not been read yet, so nothing can be checked against them.",
            missing=(policy_term("coverage details"),),
        )
    return _result(
        rule_id="coverage_profile",
        title=title,
        critical=True,
        status="satisfied",
        confidence=USER_FACT,
        explanation="This policy's coverage details have been read, so the claim can be checked against them.",
    )


def initial_waiting_period(data: EligibilityInput) -> CheckResult:
    rule = {"rule_id": "initial_waiting_period", "title": "Initial waiting period", "critical": True}
    profile, policy, claim = data.coverage_profile, data.policy, data.claim
    period = _waiting_period(profile, "initial") if profile else None
    months = whole_months(period.months.value) if period else None

    missing = list(_dates_missing(policy, claim))
    if months is None:
        missing.append(policy_term("initial waiting period, in whole months"))
    if missing:
        return _result(
            **rule,
            status="unknown",
            confidence="low" if period is None else of_extracted(period.months),
            explanation="The initial waiting period cannot be checked because some facts are missing.",
            clause=period.months if period else None,
            missing=tuple(missing),
        )

    clock = _clock(policy)
    assert period is not None and clock is not None and claim.admitted_on is not None and months is not None
    served, _end, values, sentence = _served_or_not(clock, months, claim.admitted_on)
    return _result(
        **rule,
        status="satisfied" if served else "failed",
        confidence=of_extracted(period.months),
        explanation=f"{sentence} {_notes(clock)}",
        values=values,
        clause=period.months,
    )


def ped_waiting_period(data: EligibilityInput) -> CheckResult:
    rule = {"rule_id": "ped_waiting_period", "title": "Pre-existing disease waiting period", "critical": True}
    profile, policy, claim = data.coverage_profile, data.policy, data.claim
    period = _waiting_period(profile, "pre_existing") if profile else None

    # Never assumed: both answers must come from the user.
    answers_missing = []
    if claim.condition_is_pre_existing is None:
        answers_missing.append(IS_PRE_EXISTING)
    if claim.first_diagnosed_on is None:
        answers_missing.append(FIRST_DIAGNOSED)
    if answers_missing:
        return _result(
            **rule,
            status="unknown",
            confidence=USER_FACT,
            explanation="Whether this waiting period applies depends on facts about the illness that we don't have yet.",
            clause=period.months if period else None,
            missing=tuple(answers_missing),
        )

    assert claim.first_diagnosed_on is not None
    diagnosed = claim.first_diagnosed_on
    values: dict[str, Value] = {"condition_is_pre_existing": claim.condition_is_pre_existing, "first_diagnosed_on": diagnosed}

    clock = _clock(policy)
    if claim.condition_is_pre_existing is False:
        if clock is not None and diagnosed < clock.start:
            # The user's answer and the dates disagree. Said plainly, not decided.
            return _result(
                **rule,
                status="at_risk",
                confidence=USER_FACT,
                explanation=(
                    f"You said this illness is not pre-existing, but it was first diagnosed on {format_date(diagnosed)}. "
                    f"{clock.started}, after that. An insurer is likely to treat it as "
                    f"pre-existing, so this waiting period may apply. {clock.note}"
                ),
                values=values | {clock.value_key: clock.start},
                clause=period.months if period else None,
            )
        return _result(
            **rule,
            status="satisfied",
            confidence=USER_FACT,
            explanation=(
                f"You said this illness is not pre-existing; it was first diagnosed on {format_date(diagnosed)}. "
                "The pre-existing disease waiting period therefore does not apply."
            ),
            values=values,
            clause=period.months if period else None,
        )

    months = whole_months(period.months.value) if period else None
    missing = list(_dates_missing(policy, claim))
    if months is None:
        missing.append(policy_term("pre-existing disease waiting period, in whole months"))
    if missing:
        return _result(
            **rule,
            status="unknown",
            confidence="low" if period is None else of_extracted(period.months),
            explanation="This is a pre-existing condition, but the waiting period cannot be checked because some facts are missing.",
            values=values,
            clause=period.months if period else None,
            missing=tuple(missing),
        )

    assert period is not None and clock is not None and claim.admitted_on is not None and months is not None
    served, _end, period_values, sentence = _served_or_not(clock, months, claim.admitted_on)
    return _result(
        **rule,
        status="satisfied" if served else "failed",
        confidence=lowest(of_extracted(period.months), USER_FACT),
        explanation=f"You said this illness is pre-existing (first diagnosed {format_date(diagnosed)}). {sentence} {_notes(clock)}",
        values=values | period_values,
        clause=period.months,
    )


def disease_specific_waiting_period(data: EligibilityInput) -> CheckResult:
    rule = {"rule_id": "disease_specific_waiting_period", "title": "Waiting period for specific conditions", "critical": True}
    profile, policy, claim = data.coverage_profile, data.policy, data.claim

    if claim.matched_waiting_periods is None:
        return _result(
            **rule,
            status="unknown",
            confidence=USER_FACT,
            explanation="Some illnesses have their own waiting period. We don't know yet whether this one is among them.",
            missing=(DISEASE_MATCH,),
        )
    if not claim.matched_waiting_periods:
        return _result(
            **rule,
            status="satisfied",
            confidence=USER_FACT,
            explanation="You said this illness is not one of the conditions your policy lists with its own waiting period.",
            values={"matched_waiting_periods": 0},
        )

    assert profile is not None
    periods = []
    for position in claim.matched_waiting_periods:
        if not 0 <= position < len(profile.waiting_periods) or profile.waiting_periods[position].kind != "disease_specific":
            return _result(
                **rule,
                status="unknown",
                confidence=USER_FACT,
                explanation="The condition you chose no longer matches your policy's list. Please choose it again.",
                missing=(DISEASE_MATCH,),
            )
        periods.append(profile.waiting_periods[position])

    missing = list(_dates_missing(policy, claim))
    if any(whole_months(period.months.value) is None for period in periods):
        missing.append(policy_term("waiting period for this condition, in whole months"))
    if missing:
        return _result(
            **rule,
            status="unknown",
            confidence=lowest(*(of_extracted(p.months) for p in periods)),
            explanation="The waiting period for this condition cannot be checked because some facts are missing.",
            clause=periods[0].months,
            missing=tuple(missing),
        )

    clock = _clock(policy)
    assert clock is not None and claim.admitted_on is not None
    confidence = lowest(*(of_extracted(p.months) for p in periods))
    sentences, values = [], {}
    not_served = None
    for period in periods:
        served, _end, period_values, sentence = _served_or_not(clock, whole_months(period.months.value) or 0, claim.admitted_on)
        condition = period.applies_to or "this condition"
        sentences.append(f"For {condition}: {sentence}")
        values |= {f"{condition}: {key}": value for key, value in period_values.items()}
        if not served and not_served is None:
            not_served = period
    explanation = " ".join(sentences) + f" {_notes(clock)}"
    return _result(
        **rule,
        status="failed" if not_served else "satisfied",
        confidence=confidence,
        explanation=explanation,
        values=values,
        clause=(not_served or periods[0]).months,
    )


def permanent_exclusions(data: EligibilityInput) -> CheckResult:
    rule = {"rule_id": "permanent_exclusions", "title": "Permanent exclusions", "critical": True}
    profile, claim = data.coverage_profile, data.claim

    if claim.matched_exclusions is None:
        return _result(
            **rule,
            status="unknown",
            confidence=USER_FACT,
            explanation="Your policy permanently excludes some treatments. We don't know yet whether this claim is one of them.",
            missing=(EXCLUSION_MATCH,),
        )
    if not claim.matched_exclusions:
        return _result(
            **rule,
            status="satisfied",
            confidence=USER_FACT,
            explanation="You said this treatment is not one of your policy's permanent exclusions.",
            values={"matched_exclusions": 0},
        )

    assert profile is not None
    if any(not 0 <= position < len(profile.exclusions) for position in claim.matched_exclusions):
        return _result(
            **rule,
            status="unknown",
            confidence=USER_FACT,
            explanation="The exclusion you chose no longer matches your policy's list. Please choose it again.",
            missing=(EXCLUSION_MATCH,),
        )
    matched = [profile.exclusions[position] for position in claim.matched_exclusions]
    quoted = "; ".join(f'"{exclusion.value}"' for exclusion in matched if exclusion.value)
    return _result(
        **rule,
        status="failed",
        # A doubtful reading of the exclusion text cannot give a confident "failed".
        confidence=lowest(*(of_extracted(exclusion) for exclusion in matched)),
        explanation=f"You said this treatment falls under your policy's exclusion: {quoted}. Treatment that a policy permanently excludes is not covered.",
        values={"matched_exclusions": len(matched)},
        clause=matched[0],
    )


def room_rent_sub_limit(data: EligibilityInput) -> CheckResult:
    rule = {"rule_id": "room_rent_sub_limit", "title": "Room rent limit", "critical": False}
    claim = data.claim
    found = room_rent_cap(data.coverage_profile)

    if claim.planned_room_rent_per_day is None:
        return _result(**rule, status="unknown", confidence=USER_FACT,
                       explanation="We don't know the room rent you will pay, so it can't be compared with your policy's limit.",
                       clause=found.clause, missing=(ROOM_RENT,))
    if isinstance(found, NoCap):
        return _result(**rule, status="unknown", confidence="low",
                       explanation=f"In your policy's extracted terms {found.reason}, so the room rent can't be checked.",
                       clause=found.clause, missing=(policy_term("room rent limit per day"),))

    rent, cap, how, clause, confidence = claim.planned_room_rent_per_day, found.per_day, found.how, found.clause, found.confidence
    values: dict[str, Value] = {"room_rent_per_day": rent, "room_rent_cap_per_day": cap}
    if rent <= cap:
        return _result(**rule, status="satisfied", confidence=confidence, values=values, clause=clause,
                       explanation=f"{how} The room you plan to use costs {format_rupees(rent)} per day, within that limit.")
    return _result(
        **rule,
        status="at_risk",
        confidence=confidence,
        values=values | {"excess_per_day": rent - cap},
        clause=clause,
        explanation=(
            f"{how} The room you plan to use costs {format_rupees(rent)} per day, {format_rupees(rent - cap)} over it. "
            "Many policies then apply a proportionate deduction: charges linked to the room, such as doctors' visits, "
            "nursing and some procedures, are paid only in the ratio of the capped rent to the actual rent. "
            "That can reduce the whole bill, not just the room charge."
        ),
    )


def claim_intimation(data: EligibilityInput) -> CheckResult:
    rule = {"rule_id": "claim_intimation", "title": "Telling the insurer in time", "critical": False}
    profile, claim = data.coverage_profile, data.claim
    deadline = profile.intimation_deadline_hours if profile else None

    missing = []
    if deadline is None or deadline.value is None:
        missing.append(policy_term("deadline for telling the insurer about a hospitalisation"))
    if claim.admitted_on is None:
        missing.append(ADMISSION_DATE)
    if claim.intimated_at is None:
        missing.append(INTIMATION_TIME)
    if missing:
        return _result(**rule, status="unknown", confidence="low" if deadline is None else of_extracted(deadline),
                       explanation="Whether the insurer was told in time can't be checked because some facts are missing.",
                       clause=deadline, missing=tuple(missing))

    assert deadline is not None and deadline.value is not None and claim.admitted_on is not None and claim.intimated_at is not None
    hours = deadline.value
    due = add_days(claim.admitted_on, hours_to_whole_days(hours))
    told = india_date(claim.intimated_at)
    values: dict[str, Value] = {"deadline_hours": int(hours) if hours == int(hours) else str(hours), "admitted_on": claim.admitted_on, "intimation_due_by": due, "intimated_on": told}
    base = (
        f"Your policy asks you to tell the insurer within {hours:g} hours of admission. Admitted on "
        f"{format_date(claim.admitted_on)}; only the date is known, so that is counted as by the end of {format_date(due)}."
    )
    if told <= due:
        return _result(**rule, status="satisfied", confidence=of_extracted(deadline), values=values, clause=deadline,
                       explanation=f"{base} The insurer was told on {format_date(told)}, in time.")
    late = (told - due).days
    return _result(
        **rule,
        status="at_risk",
        confidence=of_extracted(deadline),
        values=values | {"days_late": late},
        clause=deadline,
        explanation=(
            f"{base} The insurer was told on {format_date(told)}, {late} day{'' if late == 1 else 's'} late. "
            "Insurers can accept a late notice with a reason, but it can also be used to question the claim."
        ),
    )


def sum_insured_adequacy(data: EligibilityInput) -> CheckResult:
    rule = {"rule_id": "sum_insured_adequacy", "title": "Amount within the sum insured", "critical": False}
    profile, claim = data.coverage_profile, data.claim
    sum_insured = profile.sum_insured if profile else None

    missing = []
    if claim.claimed_amount is None:
        missing.append(CLAIMED_AMOUNT)
    if sum_insured is None or sum_insured.value is None:
        missing.append(policy_term("sum insured"))
    if missing:
        return _result(**rule, status="unknown", confidence="low" if sum_insured is None else of_extracted(sum_insured),
                       explanation="The claimed amount can't be compared with the sum insured because some facts are missing.",
                       clause=sum_insured, missing=tuple(missing))

    assert sum_insured is not None and sum_insured.value is not None and claim.claimed_amount is not None
    claimed, cover = claim.claimed_amount, sum_insured.value
    values: dict[str, Value] = {"claimed_amount": claimed, "sum_insured": cover}
    if claimed <= cover:
        return _result(**rule, status="satisfied", confidence=of_extracted(sum_insured), values=values, clause=sum_insured,
                       explanation=f"The amount claimed, {format_rupees(claimed)}, is within your sum insured of {format_rupees(cover)}.")
    return _result(
        **rule,
        status="at_risk",
        confidence=of_extracted(sum_insured),
        values=values | {"amount_over": claimed - cover},
        clause=sum_insured,
        explanation=(
            f"The amount claimed, {format_rupees(claimed)}, is {format_rupees(claimed - cover)} more than your sum insured "
            f"of {format_rupees(cover)}. The part above the sum insured is not payable under this policy."
        ),
    )
