"""Load and validate the two rule files.

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


class _Rule(BaseModel):
    # A misspelt key in the YAML is an error, not something to ignore.
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleSource(_Rule):
    document: str
    section: str | None
    url: str | None


class Trigger(_Rule):
    """Exactly one of: the admission date, or the latest event entering a state."""

    admission: bool = False
    event: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Trigger:
        if self.admission == (self.event is not None):
            raise ValueError("a trigger must be either {admission: true} or {event: <state>}")
        if self.event is not None and self.event not in STATES:
            raise ValueError(f"unknown state {self.event!r}")
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
