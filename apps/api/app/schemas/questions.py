"""Wire shapes for policy Q&A (CONTRACTS.md row 11, D-42)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import StringConstraints

from app.schemas.base import ApiModel
from contracts.models import Provenance


class QuestionRequest(ApiModel):
    # Any language. Trimmed, then 1 to 500 characters (D-42).
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class Citation(ApiModel):
    id: str
    kind: Literal["policy_clause", "regulation", "ombudsman_award", "other"]
    label: str
    provenance: Provenance | None
    external_url: str | None


class Verification(ApiModel):
    sentences_checked: int
    sentences_removed: int


class QuestionAnswerResult(ApiModel):
    """The `result` of a succeeded answer_question job. `answer` carries [[n]] markers into `citations` (D-42)."""

    answer: str
    citations: list[Citation]
    abstained: bool
    missing_context: str | None
    verification: Verification
