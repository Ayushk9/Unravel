"""Every grievance letter drafted, with how it was made.

Not on the wire (the draft reaches the client as its job's result, and that
row is deleted after 24 hours). This row is kept: the clauses retrieved, the
model's raw paragraphs, each paragraph's verification outcome and which model
wrote and judged it. That is the evaluation data behind citation precision
for the report, and the audit trail if a letter is ever questioned.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class GrievanceDraft(Base):
    __tablename__ = "grievance_draft"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claim.id", ondelete="CASCADE"), index=True)
    # The job that produced it; the job row itself is deleted after 24 hours.
    job_id: Mapped[UUID | None] = mapped_column()
    rung: Mapped[str] = mapped_column(Text)
    # The search queries and the clauses each one retrieved, with ranks.
    retrieved: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # The model's draft exactly as parsed.
    generated: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Per paragraph: verified or not, the reason, and the judge's verdict on each cited clause.
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # The GrievanceDraft sent to the client.
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Which model made each call: {"draft": ..., "judge": ...}.
    models: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    timings: Mapped[dict[str, float] | None] = mapped_column(JSONB)
    prompt_version: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
