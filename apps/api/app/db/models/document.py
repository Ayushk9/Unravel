"""Uploaded files and the text chunks parsed out of them."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Text, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import CONFIDENCE_VALUES, Base, one_of

DOCUMENT_TYPES = (
    "policy_schedule",
    "policy_wording",
    "discharge_summary",
    "itemised_bill",
    "payment_receipt",
    "investigation_report",
    "denial_letter",
    "id_proof",
    "unknown",
)
PARSE_STATUSES = ("queued", "parsing", "parsed", "failed")


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (
        CheckConstraint(one_of("parse_status", PARSE_STATUSES), name="parse_status"),
        CheckConstraint(one_of("detected_type_value", DOCUMENT_TYPES), name="detected_type_value"),
        CheckConstraint(one_of("detected_type_original_value", DOCUMENT_TYPES), name="detected_type_original_value"),
        CheckConstraint(one_of("detected_type_confidence", CONFIDENCE_VALUES), name="detected_type_confidence"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    # The claim this document was uploaded for. Null for uploads made
    # outside a claim (a policy document).
    # use_alter: document -> claim -> policy -> document is a cycle of foreign
    # keys, so this one is added with ALTER TABLE after all three tables exist.
    claim_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("claim.id", use_alter=True, name="fk_document_claim_id_claim"), index=True
    )

    file_name: Mapped[str] = mapped_column(Text)
    mime_type: Mapped[str] = mapped_column(Text)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str | None] = mapped_column(Text)
    # SHA-256 of the file's bytes, as hex. Identifies the exact file uploaded.
    sha256: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # detected_type: Extracted[DocumentType], stored as five columns.
    detected_type_value: Mapped[str | None] = mapped_column(Text)
    detected_type_confidence: Mapped[str] = mapped_column(Text, default="low")
    detected_type_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    detected_type_original_value: Mapped[str | None] = mapped_column(Text)
    detected_type_user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    parse_status: Mapped[str] = mapped_column(Text, default="queued")
    parse_error: Mapped[str | None] = mapped_column(Text)
    # Engine A's notes about this parse (a dropped row, an unparseable amount).
    # A list of strings; kept so a surprising result can be explained later.
    warnings: Mapped[list[str] | None] = mapped_column(JSONB)
    # Soft delete (D-20). Null means the document is live.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentChunk(Base):
    __tablename__ = "document_chunk"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    document_id: Mapped[UUID] = mapped_column(ForeignKey("document.id", ondelete="CASCADE"), index=True)
    # Order of the chunk within its document.
    position: Mapped[int] = mapped_column(Integer)
    page: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    # [x0, y0, x1, y1], normalised 0..1, top-left origin (D-23). Null if unknown.
    bbox: Mapped[list[float] | None] = mapped_column(JSONB)
