"""Every question asked about a policy, with how it was answered.

Not on the wire. The job row that carried the question is deleted after
24 hours (app/jobs/queue.py); this row is kept. It holds the user's original
words (a Hindi question stays in Hindi), the search terms actually used, the
clauses retrieved and their ranks, the model's raw sentences, and which
sentences verification removed and why. That is the evaluation data for the
report, and the audit trail if an answer is ever questioned.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class PolicyQuestion(Base):
    __tablename__ = "policy_question"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("policy.id", ondelete="CASCADE"), index=True)
    # Not a foreign key: job rows are deleted after 24 hours, this row is not.
    job_id: Mapped[UUID | None] = mapped_column()
    question: Mapped[str] = mapped_column(Text)
    # "latin" or "devanagari": which script the question was typed in.
    script: Mapped[str] = mapped_column(Text)
    # What retrieval searched for: the question itself, or its English rewrite.
    search_query: Mapped[str | None] = mapped_column(Text)
    cache_hit: Mapped[bool] = mapped_column(Boolean)
    # [{chunk_id, page, dense_rank, sparse_rank, fused_rank, rerank_score}, ...] for the clauses shown to the model.
    retrieved: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # The model's own sentences, before verification.
    generated: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # {kept: [...], removed: [{text, chunk_ids, reason, detail}], judgements: [...]}
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Exactly what the job returned (D-42).
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Which model answered each call: {"answer": ..., "judge": ..., "rewrite": ...}. Shows when the fallback was used.
    models: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    # Seconds per stage: {rewrite, retrieve.*, generate, verify.*, total}.
    timings: Mapped[dict[str, float] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
