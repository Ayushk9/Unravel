"""Ombudsman precedent: checked awards, matched to a claim by denial-ground tag.

The awards come from reference/ombudsman_awards.yaml, which only Ayush fills.
An award is used only once he has checked it (`checked_by_ayush: true`).

Matching is exact and deterministic: an award is shown for a claim when its
`denial_ground` tag is the id of one of the claim's eligibility checks that
failed or is at risk. There is no keyword search, no similarity score and no
model. An award is context, never a forecast; every note below says so.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid5

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from engines.rules.models import CheckResult

AWARDS_FILE = Path(__file__).resolve().parent / "reference" / "ombudsman_awards.yaml"

# Award ids are derived from the case reference, so the same award keeps the
# same id across restarts (links and pagination cursors depend on it). This
# namespace is a fixed, arbitrary UUID; changing it would change every id.
AWARD_ID_NAMESPACE = UUID("0192a7c0-5e1d-7a3b-9c4e-6f2b8d1a0e57")

NOT_A_PREDICTION = "Past decisions are not a prediction of how your claim will be decided."
NOTE_NONE_LOADED = f"Precedent corpus not yet loaded, so no similar Ombudsman cases are shown. {NOT_A_PREDICTION}"
NOTE_NO_MATCH = (
    "None of the checked Ombudsman decisions concern the same ground as a failed or at-risk check on this claim. "
    f"{NOT_A_PREDICTION}"
)
NOTE_MATCHED = (
    "These checked Ombudsman decisions concern the same ground as a failed or at-risk check on this claim. "
    "They are not a prediction of how your claim will be decided."
)

Outcome = Literal["upheld", "overturned", "partially_allowed", "unknown"]


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AwardEntry(_Entry):
    """One award as written in the YAML file."""

    case_reference: str = Field(min_length=1)
    insurer_name: str = Field(min_length=1)
    decided_on: date
    denial_ground: str
    outcome: Outcome
    summary: str = Field(min_length=1)
    external_url: str | None
    checked_by_ayush: bool


class AwardsFile(_Entry):
    version: int = Field(ge=1)
    awards: tuple[AwardEntry, ...]

    @model_validator(mode="after")
    def _valid(self) -> AwardsFile:
        tags = ground_labels()
        for award in self.awards:
            if award.denial_ground not in tags:
                raise ValueError(f"award {award.case_reference!r}: unknown denial_ground {award.denial_ground!r}; use one of {sorted(tags)}")
        references = [award.case_reference for award in self.awards]
        if len(references) != len(set(references)):
            raise ValueError("case_reference must be unique")
        return self


class Award(_Entry):
    """A checked award, ready to serve. `denial_ground` is the tag; `denial_ground_label` is its plain name."""

    id: UUID
    case_reference: str
    insurer_name: str
    decided_on: date
    denial_ground: str
    denial_ground_label: str
    outcome: Outcome
    summary: str
    external_url: str | None


class Precedent(_Entry):
    awards: tuple[Award, ...]
    note: str


def ground_labels() -> dict[str, str]:
    """Every allowed denial-ground tag (an eligibility check id) and its plain name."""
    from engines.rules.registry import ELIGIBILITY_RULES

    return {rule.id: rule.title for rule in ELIGIBILITY_RULES}


def award_id(case_reference: str) -> UUID:
    return uuid5(AWARD_ID_NAMESPACE, case_reference)


def parse_awards(data: dict) -> tuple[Award, ...]:
    """Validate the file's contents and keep only the awards Ayush has checked, newest first."""
    parsed = AwardsFile.model_validate(data)
    labels = ground_labels()
    checked = [
        Award(
            id=award_id(entry.case_reference),
            case_reference=entry.case_reference,
            insurer_name=entry.insurer_name,
            decided_on=entry.decided_on,
            denial_ground=entry.denial_ground,
            denial_ground_label=labels[entry.denial_ground],
            outcome=entry.outcome,
            summary=entry.summary,
            external_url=entry.external_url,
        )
        for entry in parsed.awards
        if entry.checked_by_ayush
    ]
    return tuple(sorted(checked, key=lambda a: (a.decided_on, str(a.id)), reverse=True))


def load_awards(path: Path = AWARDS_FILE) -> tuple[Award, ...]:
    return parse_awards(yaml.safe_load(path.read_text(encoding="utf-8")))


def match_precedent(checks: Sequence[CheckResult], awards: Sequence[Award]) -> Precedent:
    """The awards whose ground is a failed or at-risk check on this claim, and the note to show with them."""
    if not awards:
        return Precedent(awards=(), note=NOTE_NONE_LOADED)
    grounds = {check.id for check in checks if check.status in ("failed", "at_risk")}
    matched = tuple(award for award in awards if award.denial_ground in grounds)
    return Precedent(awards=matched, note=NOTE_MATCHED if matched else NOTE_NO_MATCH)
