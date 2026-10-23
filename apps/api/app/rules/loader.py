"""Load and validate the rule files.

The files are data, edited by a person. They are validated when loaded, so a
typo (an unknown state, a misspelt unit, a document type that does not
exist) stops the server at startup with a clear message instead of
producing a wrong deadline later.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.claims.state_machine import STATES
from app.db.models.document import DOCUMENT_TYPES

RULES_DIR = Path(__file__).resolve().parent
DEADLINE_RULES_FILE = RULES_DIR / "deadline_rules.yaml"
REQUIRED_DOCUMENTS_FILE = RULES_DIR / "required_documents.yaml"
GRIEVANCE_RUNGS_FILE = RULES_DIR / "grievance_rungs.yaml"
OMBUDSMAN_RULES_FILE = RULES_DIR / "ombudsman_rules.yaml"

RUNGS = ("insurer_grievance_cell", "irdai_bima_bharosa", "insurance_ombudsman")


class _Rule(BaseModel):
    # A misspelt key in the YAML is an error, not something to ignore.
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleSource(_Rule):
    document: str
    section: str | None
    url: str | None


class Trigger(_Rule):
    """Exactly one of: the admission date, or the latest event entering a state.

    An event trigger may name a fallback (D-49): `otherwise: {event, after}` counts
    from `after` past the latest `otherwise.event` when `event` has not happened.
    The Ombudsman window uses it: from the insurer's reply, otherwise from one month
    after the grievance was sent.
    """

    admission: bool = False
    event: str | None = None
    otherwise: FallbackTrigger | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Trigger:
        if self.admission == (self.event is not None):
            raise ValueError("a trigger must be either {admission: true} or {event: <state>}")
        if self.event is not None and self.event not in STATES:
            raise ValueError(f"unknown state {self.event!r}")
        if self.otherwise is not None and self.event is None:
            raise ValueError("a fallback (otherwise) needs an event trigger")
        return self


class Offset(_Rule):
    """Exactly one of: a fixed length, or a value read from the policy."""

    value: int | None = Field(default=None, gt=0)
    unit: Literal["days", "months", "years"] | None = None
    policy_field: Literal["intimation_deadline_hours"] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Offset:
        fixed = self.value is not None and self.unit is not None
        if fixed == (self.policy_field is not None) or (self.value is None) != (self.unit is None):
            raise ValueError("an offset must be either {value, unit} or {policy_field}")
        return self


class FallbackTrigger(_Rule):
    """The fallback of an event trigger: `after` past the latest event entering `event`."""

    event: str
    after: Offset

    @model_validator(mode="after")
    def _fixed(self) -> FallbackTrigger:
        if self.event not in STATES:
            raise ValueError(f"unknown state {self.event!r}")
        if self.after.value is None:
            raise ValueError("a fallback's `after` must be a fixed length {value, unit}")
        return self


Trigger.model_rebuild()


class DeadlineRule(_Rule):
    id: str
    label: str
    trigger: Trigger
    active_in: tuple[str, ...]
    offset: Offset
    description: str
    source: RuleSource
    verified: bool
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def _known_states(self) -> DeadlineRule:
        unknown = [state for state in self.active_in if state not in STATES]
        if unknown:
            raise ValueError(f"rule {self.id}: unknown state(s) in active_in: {unknown}")
        return self


class Urgency(_Rule):
    critical_within_days: int = Field(ge=0)
    soon_within_days: int = Field(ge=0)


class DeadlineRules(_Rule):
    version: int = Field(ge=1)
    urgency: Urgency
    rules: tuple[DeadlineRule, ...]

    @model_validator(mode="after")
    def _unique_ids(self) -> DeadlineRules:
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("deadline rule ids must be unique")
        return self


class RequiredDocument(_Rule):
    description: str
    where_to_get: str
    source: RuleSource


class RequiredDocuments(_Rule):
    version: int = Field(ge=1)
    verified: bool
    documents: dict[str, RequiredDocument]
    # claim_type -> admission_type -> ordered list of document types
    checklists: dict[str, dict[str, tuple[str, ...]]]

    @model_validator(mode="after")
    def _known_types(self) -> RequiredDocuments:
        for name in self.documents:
            if name not in DOCUMENT_TYPES or name == "unknown":
                raise ValueError(f"{name!r} is not a document type in the contract")
        for claim_type, by_admission in self.checklists.items():
            for admission_type, types in by_admission.items():
                missing = [t for t in types if t not in self.documents]
                if missing:
                    raise ValueError(f"checklist {claim_type}/{admission_type} lists undescribed types: {missing}")
        return self

    def checklist(self, claim_type: str, admission_type: str) -> tuple[str, ...] | None:
        """The ordered list for this kind of claim, or None if the file has no entry."""
        return self.checklists.get(claim_type, {}).get(admission_type)


class RungCondition(_Rule):
    """One claim state in which a rung is offered, and the sentence that says why.

    D-49 adds a gate: `opens_with` (offered only from that deadline's date) and
    `closes_with` (no longer offered after it), each with its own sentence.
    """

    state: str
    reason: str
    deadline: str | None = None
    reason_after_due: str | None = None
    opens_with: str | None = None
    reason_before_open: str | None = None
    closes_with: str | None = None
    reason_after_close: str | None = None

    def sentences(self) -> list[str]:
        return [text for text in (self.reason, self.reason_after_due, self.reason_before_open, self.reason_after_close) if text]

    @model_validator(mode="after")
    def _consistent(self) -> RungCondition:
        if self.state not in STATES:
            raise ValueError(f"unknown state {self.state!r}")
        text = " ".join(self.sentences())
        for placeholder, rule in (("{due}", self.deadline), ("{opens}", self.opens_with), ("{closes}", self.closes_with)):
            if placeholder in text and rule is None:
                raise ValueError(f"state {self.state}: a reason uses {placeholder} but names no deadline for it")
        if self.reason_after_due is not None and self.deadline is None:
            raise ValueError(f"state {self.state}: reason_after_due needs a deadline")
        if (self.opens_with is None) != (self.reason_before_open is None):
            raise ValueError(f"state {self.state}: opens_with and reason_before_open go together")
        if (self.closes_with is None) != (self.reason_after_close is None):
            raise ValueError(f"state {self.state}: closes_with and reason_after_close go together")
        return self

    def deadline_ids(self) -> list[str]:
        return [rule for rule in (self.deadline, self.opens_with, self.closes_with) if rule]


class Rung(_Rule):
    label: str
    addressee: str
    when: tuple[RungCondition, ...]
    # Per claim state: why the rung is not offered there (D-49), instead of `unavailable`.
    not_offered: dict[str, str] = Field(default_factory=dict)
    unavailable: str
    source: RuleSource
    verified: bool
    version: int = Field(ge=1)

    @model_validator(mode="after")
    def _known_states(self) -> Rung:
        unknown = [state for state in self.not_offered if state not in STATES]
        if unknown:
            raise ValueError(f"not_offered: unknown state(s) {unknown}")
        return self


class GrievanceRungs(_Rule):
    version: int = Field(ge=1)
    rungs: dict[str, Rung]

    @model_validator(mode="after")
    def _all_rungs(self) -> GrievanceRungs:
        if tuple(self.rungs) != RUNGS:
            raise ValueError(f"the file must describe exactly these rungs, in order: {RUNGS}")
        return self


class AwardCeiling(_Rule):
    value: int | None = Field(default=None, gt=0)  # integer paise
    verified: bool
    # The only wording in which the figure may be shown ({ceiling} = the value, formatted).
    rung_sentence: str | None = None
    source: RuleSource

    @model_validator(mode="after")
    def _verified_means_complete(self) -> AwardCeiling:
        if self.verified and (self.value is None or self.source.url is None or not self.rung_sentence or "{ceiling}" not in self.rung_sentence):
            raise ValueError("a verified award ceiling needs a value, a source url and a rung_sentence containing {ceiling}")
        return self

    def shown_sentence(self) -> str | None:
        """The sentence for the Ombudsman rung, or None while the figure is unverified."""
        if not (self.verified and self.value is not None and self.rung_sentence):
            return None
        from engines.rules.money import format_rupees

        return self.rung_sentence.format(ceiling=format_rupees(self.value))


class InfoSentence(_Rule):
    """A fixed sentence shown as information, with its source; shown only while verified."""

    verified: bool
    sentence: str
    source: RuleSource

    def shown(self) -> str | None:
        return self.sentence if self.verified else None


class OmbudsmanRules(_Rule):
    version: int = Field(ge=1)
    award_ceiling: AwardCeiling
    award_time: InfoSentence


def _check_rung_deadlines(rungs: GrievanceRungs, deadlines: DeadlineRules) -> None:
    """A rung's deadline must be a real rule that is shown in that claim state; otherwise its date never exists."""
    by_id = {rule.id: rule for rule in deadlines.rules}
    for name, rung in rungs.rungs.items():
        for condition in rung.when:
            for rule_id in condition.deadline_ids():
                rule = by_id.get(rule_id)
                if rule is None:
                    raise ValueError(f"rung {name}: unknown deadline rule {rule_id!r}")
                if condition.state not in rule.active_in or rule.trigger.event is None:
                    raise ValueError(f"rung {name}: deadline {rule.id} is not an event deadline shown in state {condition.state}")


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8") as file:
        # safe_load reads plain data only; it cannot be made to run code.
        return yaml.safe_load(file)


@lru_cache
def load_deadline_rules() -> DeadlineRules:
    return DeadlineRules.model_validate(_read(DEADLINE_RULES_FILE))


@lru_cache
def load_required_documents() -> RequiredDocuments:
    return RequiredDocuments.model_validate(_read(REQUIRED_DOCUMENTS_FILE))


@lru_cache
def load_grievance_rungs() -> GrievanceRungs:
    rungs = GrievanceRungs.model_validate(_read(GRIEVANCE_RUNGS_FILE))
    _check_rung_deadlines(rungs, load_deadline_rules())
    return rungs


@lru_cache
def load_ombudsman_rules() -> OmbudsmanRules:
    return OmbudsmanRules.model_validate(_read(OMBUDSMAN_RULES_FILE))
