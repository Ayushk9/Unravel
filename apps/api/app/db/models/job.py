"""Long-running work that clients poll (API_DECISIONS D-07)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, one_of

JOB_KINDS = ("parse_document", "answer_question", "generate_grievance_draft")
JOB_STATUSES = ("queued", "running", "succeeded", "failed")


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint(one_of("kind", JOB_KINDS), name="kind"),
        CheckConstraint(one_of("status", JOB_STATUSES), name="status"),
        # D-13: repeating a request with the same Idempotency-Key must return
        # the same job. Both idempotent endpoints are job endpoints, so the key
        # lives here. Rows with a null key are not constrained.
        UniqueConstraint("household_id", "idempotency_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="queued")
    # {"step": "...", "percent": 45}, or null before work starts.
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
