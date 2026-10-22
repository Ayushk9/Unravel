"""Letter text built only from the eligibility rules' own values (D-48). Pure functions, no model.

When the user has said which ground the insurer gave for a denial
(`claim.denial_ground`, an eligibility check id) and our rules find that very
check SATISFIED, the letter opens with a fixed paragraph stating the facts
that contradict the denial, every one of them taken from the check's
`values`: the date waiting periods count from, the length of the waiting
period, the date it ended, and the admission date. It cites the clause the
check's period was read from (its governing clause, with page and bbox).

The same check also gives the deterministic "Before you send" notes: the
assumptions the rule made, which the insurer could question.

Only date-counted waiting-period checks have such a paragraph today
(initial, pre-existing disease, condition-specific). For any other ground
no paragraph is written; nothing is improvised.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.schemas.grievances import BeforeYouSendNote, DraftParagraph
from app.schemas.questions import Citation
from engines.rules.dates import format_date
from engines.rules.models import CheckResult

WAITING_PERIOD_CHECKS = ("initial_waiting_period", "ped_waiting_period", "disease_specific_waiting_period")
PERIOD_NAMES = {
    "initial_waiting_period": "initial waiting period",
    "ped_waiting_period": "waiting period for pre-existing diseases",
    "disease_specific_waiting_period": "waiting period for this condition",
}


@dataclass(frozen=True)
class RulesText:
    paragraph: DraftParagraph
    citation: Citation | None
    notes: list[BeforeYouSendNote]


def ground_check(checks: tuple[CheckResult, ...], denial_ground: str | None) -> CheckResult | None:
    """The eligibility check for the ground the user chose, if they chose one."""
    return next((check for check in checks if check.id == denial_ground), None) if denial_ground else None


def _day(value: object) -> str | None:
    return format_date(value) if isinstance(value, date) else None


def rules_opening(check: CheckResult | None) -> RulesText | None:
    """The fixed opening paragraph and notes, or None when the chosen ground's check is not a satisfied waiting period."""
    if check is None or check.status != "satisfied" or check.id not in WAITING_PERIOD_CHECKS:
        return None
    values = check.values
    from_inception = "first_inception_date" in values
    start = _day(values.get("first_inception_date") or values.get("policy_start"))
    ends, admitted, months = _day(values.get("waiting_period_ends")), _day(values.get("admitted_on")), values.get("waiting_months")
    if not (start and ends and admitted and isinstance(months, int)):
        return None  # a value is missing: say nothing rather than guess

    citation = None
    citation_ids: list[str] = []
    if check.governing_clause is not None:
        citation = Citation(
            id=f"rule-{check.id}", kind="policy_clause", label=f"Page {check.governing_clause.page}",
            provenance=check.governing_clause, external_url=None,
        )
        citation_ids = [citation.id]

    began = "My continuous cover with you began on" if from_inception else "My policy began on"
    period = PERIOD_NAMES[check.id]
    text = (
        f"{began} {start}. The policy's {period} is {months} months, so it ended on {ends}. "
        f"I was admitted on {admitted}, after that waiting period had ended."
    )
    paragraph = DraftParagraph(text=text, citation_ids=citation_ids, verified=False, source="rules")
    return RulesText(paragraph=paragraph, citation=citation, notes=_notes(check, start, from_inception, months, citation_ids))


def _notes(check: CheckResult, start: str, from_inception: bool, months: int, citation_ids: list[str]) -> list[BeforeYouSendNote]:
    notes = []
    if from_inception:
        notes.append(f"The waiting period is counted from {start}, the date you entered as the start of continuous cover. "
                     "The insurer may ask for proof that the policy was renewed without a break since then.")
    else:
        notes.append(f"The waiting period is counted from the current policy's start, {start}. If your cover started earlier "
                     "and was renewed without a break, enter that date on the policy page; it may change this letter.")
    if check.confidence != "high":
        notes.append(f"The {months}-month period was read from your policy with {check.confidence} confidence and has not been "
                     "confirmed by you. Check it against the cited page before sending.")
    return [BeforeYouSendNote(text=text, citation_ids=citation_ids, source="rules", verified=False) for text in notes]


def assessment_agrees(check: CheckResult | None, band: str) -> bool:
    """Our rules agree with the denial (D-47).

    With a chosen ground (D-48): that check failed. Without one: the old rule,
    the claim's band is likely_ineligible (a check failed with high confidence).
    """
    if check is not None:
        return check.status == "failed"
    return band == "likely_ineligible"
