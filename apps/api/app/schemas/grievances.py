"""Wire shapes for grievance drafting and Ombudsman awards (CONTRACTS.md rows 20, 22, 30; D-43 to D-45)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from app.schemas.base import ApiModel
from app.schemas.questions import Citation

# The contract's rung enum. "other" is its escape hatch (D-06): it can appear
# in a response from a newer server, but a request for it is refused (D-44).
Rung = Literal["insurer_grievance_cell", "irdai_bima_bharosa", "insurance_ombudsman"]
WireRung = Literal["insurer_grievance_cell", "irdai_bima_bharosa", "insurance_ombudsman", "other"]


class GrievanceDraftRequest(ApiModel):
    rung: Rung


class GrievanceRungOption(ApiModel):
    """Whether a letter for this rung makes sense now, and why (D-43)."""

    rung: WireRung
    label: str
    available: bool
    reason: str
    # The deadline rules the reason's dates come from (deadline_rules.yaml ids).
    rule_ids: list[str]
    # False if this rung's own description or any rule it uses is unchecked.
    verified: bool


class HeaderLine(ApiModel):
    label: str
    # Null when the fact is not recorded; clients show "not recorded", never a guess.
    value: str | None


class DraftParagraph(ApiModel):
    text: str
    # Ids into `citations`. Every one is a clause of the claim's policy. Empty for a template paragraph.
    citation_ids: list[str]
    # False when the number check or the support judge could not confirm it (product rule 4).
    # Always false for a template paragraph: it is a request, not a checked claim (D-47).
    verified: bool
    # "model": written by the model and checked. "template": our fixed procedural request,
    # no model output (D-47). "rules": fixed text built only from an eligibility check's own
    # values, citing its clause (D-48). "other" is the escape hatch (D-06).
    source: Literal["model", "rules", "template", "other"]


class BeforeYouSendNote(ApiModel):
    """Something to check before sending, shown on the screen and never put in the letter (D-48)."""

    text: str
    citation_ids: list[str]
    # "rules": built by code from an eligibility check. "model": a condition the model found in a
    # cited clause, checked like a paragraph; `verified` false means the check could not confirm it.
    source: Literal["model", "rules", "other"]
    verified: bool


class EvidenceItem(ApiModel):
    item: str
    satisfied: bool


class GrievanceDraft(ApiModel):
    """The `result` of a succeeded generate_grievance_draft job.

    Everything except `paragraphs[].text` is filled by code from stored data.
    The model writes the argument paragraphs only.
    """

    id: UUID
    claim_id: UUID
    rung: WireRung
    subject: str
    addressee: str
    header_lines: list[HeaderLine]
    paragraphs: list[DraftParagraph]
    citations: list[Citation]
    evidence_checklist: list[EvidenceItem]
    # verified model paragraphs / all model paragraphs; 0 when there are none. Template paragraphs don't count (D-47).
    citation_precision: float
    closing: str
    disclaimer: str
    # The whole letter as plain text, rendered by the server, for "Copy text".
    letter_text: str
    missing_context: str | None
    # Set when our rules agree with the denial (D-47, made exact by D-48): the letter then asks
    # the insurer to explain its decision rather than dispute it. Null otherwise.
    assessment_note: str | None
    # Conditions and assumptions to check before sending (D-48). Never in letter_text.
    before_you_send: list[BeforeYouSendNote]
    generated_at: datetime


class OmbudsmanAward(ApiModel):
    id: UUID
    case_reference: str
    insurer_name: str
    decided_on: date
    # The ground's plain name, e.g. "Pre-existing disease waiting period" (D-45).
    denial_ground: str
    outcome: Literal["upheld", "overturned", "partially_allowed", "unknown"]
    summary: str
    external_url: str | None
