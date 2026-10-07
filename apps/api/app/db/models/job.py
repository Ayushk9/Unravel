"""Long-running work that clients poll (API_DECISIONS D-07)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Text, UniqueConstraint, func
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
    # What the job must do, e.g. {"document_id": "...", "document_kind": "policy"}.
    # Everything a worker needs is in this row, so a worker in another process,
    # or on another machine, can run the job with no shared memory.
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    # `error` is the readable sentence sent to clients (the wire type is a
    # string). The machine-readable code and whether a retry could succeed are
    # kept beside it for operators; they are not part of the wire Job.
    error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    retryable: Mapped[bool | None] = mapped_column(Boolean)

    idempotency_key: Mapped[str | None] = mapped_column(Text)
    # SHA-256 of the request that created the job. A repeat of the same
    # Idempotency-Key with a different hash is a different request (D-27).
    request_hash: Mapped[str | None] = mapped_column(Text)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
