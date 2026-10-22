"""The deterministic parts of a grievance letter. Pure functions, no model.

Every fact in the letter (names, policy number, dates, amounts, the denial
date and the reason recorded for it, the pages cited) is put there by this
code from stored data. The model's output reaches the letter only as the text
of the argument paragraphs, which `render_letter_text` places between the
header and the closing and labels when they are unconfirmed.

A fact that is not recorded is `None`, shown as "not recorded". It is never
filled with a guess or a placeholder that looks like a real value.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.schemas.grievances import DraftParagraph, HeaderLine
from app.schemas.questions import Citation
from engines.rules.dates import format_date
from engines.rules.money import format_rupees

NOT_RECORDED = "not recorded"
DISCLAIMER = (
    "This is a draft based on your documents, not legal advice. "
    "Check every statement before you send it; you send it yourself."
)
UNCONFIRMED_MARK = "[NOT CONFIRMED AGAINST YOUR POLICY. Check or remove before sending.]"
NO_ARGUMENT_PLACEHOLDER = (
    "[Write here why you disagree with the decision. We couldn't draft this part from your policy's text.]"
)
SIGN_OFF = "Yours faithfully,\n\n(Your name, signature, address and phone number)"
DATE_LINE = "Date: (fill in when you send it)"

# D-47: fixed procedural requests, added when no model paragraph survived verification or our
# rules agree with the denial. They assert nothing about the policy, so they need no citation.
TEMPLATE_PARAGRAPHS = (
    "Please tell me the exact clause of the policy, with its number and wording, on which the decision on this claim is based.",
    "Please share the documents and other evidence your decision relied on, including any medical opinion or investigation report.",
    "Please give me your decision in writing, with the reasons for it, so that I can understand how the policy was applied to this claim.",
)
ASSESSMENT_AGREES = (
    "Our assessment agrees with the insurer's stated reason. This letter asks the insurer to explain its decision; it does not dispute it."
)
EXPLANATION_PREFIX = "Request for an explanation of"
EXPLANATION_REQUEST = "I request you to reply to each of these points in writing."

SUBJECT_PREFIX = {
    "insurer_grievance_cell": "Request to review",
    "irdai_bima_bharosa": "Grievance about",
    "insurance_ombudsman": "Complaint about",
}
REQUEST = {
    "insurer_grievance_cell": "I request you to review this claim and to reply to me in writing.",
    "irdai_bima_bharosa": "I request IRDAI to take up this grievance with the insurer.",
    "insurance_ombudsman": "I request the Ombudsman to consider this complaint against the insurer's decision.",
}


@dataclass(frozen=True)
class LetterFacts:
    """Everything the deterministic parts are made from. Each value comes from the database."""

    rung: str
    addressee_template: str
    insurer_name: str | None
    policy_number: str | None
    product_name: str | None
    patient_name: str | None
    hospital_name: str | None
    admitted_on: date | None
    discharged_on: date | None
    claimed_amount: int | None  # paise
    denied_on: date | None
    denial_reason: str | None  # the note recorded with the `denied` event


def addressee(facts: LetterFacts) -> str:
    return facts.addressee_template.format(insurer=facts.insurer_name or "your insurer")


def subject(facts: LetterFacts, asks_for_explanation: bool = False) -> str:
    topic = "the denial of a health insurance claim" if facts.denied_on else "the delay in deciding a health insurance claim"
    who = facts.patient_name or "the insured person"
    policy = f"policy {facts.policy_number}" if facts.policy_number else "policy number not recorded"
    prefix = EXPLANATION_PREFIX if asks_for_explanation else SUBJECT_PREFIX[facts.rung]
    return f"{prefix} {topic}: {who}, {policy}"


def header_lines(facts: LetterFacts) -> list[HeaderLine]:
    def day(value: date | None) -> str | None:
        return format_date(value) if value else None

    lines = [
        HeaderLine(label="Insured person (patient)", value=facts.patient_name),
        HeaderLine(label="Insurer", value=facts.insurer_name),
        HeaderLine(label="Policy number", value=facts.policy_number),
        HeaderLine(label="Plan", value=facts.product_name),
        HeaderLine(label="Hospital", value=facts.hospital_name),
        HeaderLine(label="Admitted on", value=day(facts.admitted_on)),
        HeaderLine(label="Discharged on", value=day(facts.discharged_on)),
        HeaderLine(label="Amount claimed", value=format_rupees(facts.claimed_amount) if facts.claimed_amount is not None else None),
    ]
    if facts.denied_on:
        lines += [
            HeaderLine(label="Claim denied on", value=day(facts.denied_on)),
            # The user's own record of the reason; it is quoted, not restated.
            HeaderLine(label="Reason for denial, as recorded", value=f"“{facts.denial_reason}”" if facts.denial_reason else None),
        ]
    return lines


def closing(rung: str, enclosed: list[str], asks_for_explanation: bool = False) -> str:
    parts = [EXPLANATION_REQUEST if asks_for_explanation else REQUEST[rung]]
    if enclosed:
        parts.append("Enclosures:\n" + "\n".join(f"- {name}" for name in enclosed))
    parts.append(SIGN_OFF)
    return "\n\n".join(parts)


def references(paragraph: DraftParagraph, citations: list[Citation]) -> str:
    """"(Policy document, pages 9 and 12)": the pages a paragraph cites, from the citations, never from model text."""
    by_id = {c.id: c for c in citations}
    pages = sorted({by_id[i].provenance.page for i in paragraph.citation_ids if i in by_id and by_id[i].provenance})
    if not pages:
        return ""
    if len(pages) == 1:
        return f"(Policy document, page {pages[0]})"
    return f"(Policy document, pages {', '.join(map(str, pages[:-1]))} and {pages[-1]})"


def template_paragraphs() -> list[DraftParagraph]:
    """The fixed procedural requests (D-47). Never model output; `verified` is false because nothing was checked."""
    return [DraftParagraph(text=text, citation_ids=[], verified=False, source="template") for text in TEMPLATE_PARAGRAPHS]


def render_letter_text(
    facts: LetterFacts, paragraphs: list[DraftParagraph], citations: list[Citation], closing_text: str, asks_for_explanation: bool = False
) -> str:
    """The whole letter as plain text, for "Copy text". Unconfirmed paragraphs carry a visible mark."""
    header = "\n".join(f"{line.label}: {line.value or NOT_RECORDED}" for line in header_lines(facts))
    body: list[str] = []
    for paragraph in paragraphs:
        text = f"{paragraph.text} {references(paragraph, citations)}".strip()
        # A template request states nothing about the policy, so it carries no "not confirmed" mark.
        body.append(text if paragraph.verified or paragraph.source == "template" else f"{UNCONFIRMED_MARK}\n{text}")
    if not body:
        body.append(NO_ARGUMENT_PLACEHOLDER)
    sections = [
        f"To,\n{addressee(facts)}",
        DATE_LINE,
        f"Subject: {subject(facts, asks_for_explanation)}",
        header,
        "Dear Sir or Madam,",
        *body,
        closing_text,
        f"---\n{DISCLAIMER}",
    ]
    return "\n\n".join(sections)
