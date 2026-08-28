"""The JSON shape Gemini is constrained to return.

This is deliberately NOT `contracts.models` — those are the wire contract to
the frontend (money as paise-int, waiting periods as float months, a single
`Extracted[T]` wrapper) and the model should never be trusted to produce
that directly:

  - Money must go through `money.parse_rupees_to_paise` ourselves (see
    money.py's docstring on why LLM arithmetic on money is not trusted), so
    every rupee field here is the *raw text* the model read ("5,00,000/-"),
    not a number.
  - Confidence is computed deterministically from provenance-match quality
    (see provenance.py), never asked of the model — so there is no
    `confidence` field here at all.
  - Every field the model fills also carries a `source_text` sibling: the
    verbatim quote it was read from. This is the only channel provenance
    recovery has back into the document (see provenance.py) — without it, a
    correctly-extracted number could never be tied back to a page and bbox.

Field descriptions are set via `Field(description=...)`, not docstrings —
pydantic's `model_json_schema()` (which becomes Gemini's `response_schema`)
only emits `description`, so a plain comment or attribute docstring here
would silently never reach the model.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LLMSubLimit(BaseModel):
    category: Literal["room_rent", "icu", "procedure", "ambulance", "opd", "other"]
    label: str
    cap_amount_raw: str | None = Field(
        description='Verbatim rupee amount as written, e.g. "5,00,000/-" or "1% of Sum Insured". '
        "Null if this row has no cap amount stated."
    )
    cap_basis: Literal["per_day", "per_claim", "per_policy_year", "percent_of_sum_insured", "unknown"]
    percent_value: float | None = Field(
        description='Only set when cap_basis is percent_of_sum_insured, e.g. 1.0 for "1% of Sum Insured".'
    )
    source_text: str | None = Field(description="Verbatim quote (cell text or sentence) this row was read from.")


class LLMWaitingPeriod(BaseModel):
    kind: Literal["initial", "disease_specific", "pre_existing", "maternity"]
    months: float | None
    applies_to: str | None = Field(
        description="Free text describing what this waiting period applies to, e.g. a named disease. "
        "Null for initial/pre_existing/maternity unless the document specifies further."
    )
    source_text: str | None = Field(description="Verbatim quote this waiting period was read from.")


class LLMExclusion(BaseModel):
    text: str = Field(description="A concise statement of one permanent exclusion, in your own words.")
    source_text: str | None = Field(description="Verbatim quote this exclusion was read from.")


class LLMPolicyExtraction(BaseModel):
    sum_insured_raw: str | None = Field(description='Verbatim rupee amount as written, e.g. "5,00,000/-".')
    sum_insured_source_text: str | None
    co_pay_percent: float | None = Field(
        description='A plain percentage, e.g. 10.0 for "10% co-payment". Null if the policy states no '
        "co-pay or doesn't mention one."
    )
    co_pay_percent_source_text: str | None
    sub_limits: list[LLMSubLimit]
    waiting_periods: list[LLMWaitingPeriod]
    exclusions: list[LLMExclusion]
    intimation_deadline_hours: float | None = Field(
        description='Claim intimation deadline converted to hours, e.g. 24.0 for "within 24 hours", '
        '720.0 for "within 30 days".'
    )
    intimation_deadline_hours_source_text: str | None


class LLMBillLineItem(BaseModel):
    description: str
    quantity: float | None
    rate_raw: str | None = Field(
        description='Verbatim per-unit rate as written, e.g. "2,500/-". Null if the bill only states a '
        "total amount for this line."
    )
    amount_raw: str | None = Field(description="Verbatim line total as written.")
    source_text: str | None = Field(description="Verbatim quote this line item was read from.")


class LLMBillExtraction(BaseModel):
    line_items: list[LLMBillLineItem]
