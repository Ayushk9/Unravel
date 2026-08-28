"""SQLAlchemy 2.0 async-compatible ORM mappings.

The mappings are synchronous-looking by design: the same mapped classes work
with ``AsyncSession``; async behaviour belongs to the engine/session layer.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship as orm_relationship

from app.db.base import Base
from app.db.uuid7 import uuid7


def utc_now() -> datetime:
    """Return an aware UTC instant for application-managed timestamp updates."""
    return datetime.now(timezone.utc)


JSON = JSONB


def uuid_pk() -> Mapped[UUID]:
    """Return a fresh UUIDv7 primary-key column for each mapped table."""
    return mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid7)


class Household(Base):
    __tablename__ = "household"

    id: Mapped[UUID] = uuid_pk()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    members: Mapped[list[Member]] = orm_relationship(back_populates="household", cascade="all, delete-orphan")
    documents: Mapped[list[Document]] = orm_relationship(back_populates="household", cascade="all, delete-orphan")
    policies: Mapped[list[Policy]] = orm_relationship(back_populates="household", cascade="all, delete-orphan")


class Member(Base):
    __tablename__ = "member"

    id: Mapped[UUID] = uuid_pk()
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    relationship: Mapped[str] = mapped_column(String(80), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)

    household: Mapped[Household] = orm_relationship(back_populates="members")


class Insurer(Base):
    __tablename__ = "insurer"
    __table_args__ = (UniqueConstraint("irdai_code", name="uq_insurer_irdai_code"),)

    id: Mapped[UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    irdai_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    policies: Mapped[list[Policy]] = orm_relationship(back_populates="insurer")
    term_maps: Mapped[list[InsurerTermMap]] = orm_relationship(back_populates="insurer", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "document"

    id: Mapped[UUID] = uuid_pk()
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), nullable=False, index=True)
    file_name: Mapped[str] = mapped_column(String(1024), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detected_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detected_type_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    detected_type_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    detected_type_original_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    detected_type_user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    parse_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="queued")
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    household: Mapped[Household] = orm_relationship(back_populates="documents")
    chunks: Mapped[list[DocumentChunk]] = orm_relationship(back_populates="document", cascade="all, delete-orphan")
    sourced_policies: Mapped[list[Policy]] = orm_relationship(back_populates="source_document")


class Policy(Base):
    __tablename__ = "policy"
    __table_args__ = (UniqueConstraint("household_id", "policy_number", name="uq_policy_household_policy_number"),)

    id: Mapped[UUID] = uuid_pk()
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), nullable=False, index=True)
    insurer_id: Mapped[UUID] = mapped_column(ForeignKey("insurer.id", ondelete="RESTRICT"), nullable=False, index=True)
    policy_number: Mapped[str] = mapped_column(String(255), nullable=False)
    product_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    policy_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_document_id: Mapped[UUID] = mapped_column(ForeignKey("document.id", ondelete="RESTRICT"), nullable=False, index=True)

    household: Mapped[Household] = orm_relationship(back_populates="policies")
    insurer: Mapped[Insurer] = orm_relationship(back_populates="policies")
    source_document: Mapped[Document] = orm_relationship(back_populates="sourced_policies", foreign_keys=[source_document_id])
    coverage_profile: Mapped[CoverageProfile | None] = orm_relationship(back_populates="policy", cascade="all, delete-orphan", uselist=False)


class CoverageProfile(Base):
    __tablename__ = "coverage_profile"
    __table_args__ = (
        CheckConstraint("extraction_completeness >= 0 AND extraction_completeness <= 1", name="ck_coverage_profile_completeness"),
    )

    id: Mapped[UUID] = uuid_pk()
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("policy.id", ondelete="CASCADE"), nullable=False, unique=True)
    sum_insured_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sum_insured_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sum_insured_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    sum_insured_original_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sum_insured_user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    co_pay_percent_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    co_pay_percent_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    co_pay_percent_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    co_pay_percent_original_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    co_pay_percent_user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    intimation_deadline_hours_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    intimation_deadline_hours_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    intimation_deadline_hours_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    intimation_deadline_hours_original_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    intimation_deadline_hours_user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    extraction_completeness: Mapped[float] = mapped_column(Float, nullable=False)

    policy: Mapped[Policy] = orm_relationship(back_populates="coverage_profile")
    sub_limits: Mapped[list[SubLimit]] = orm_relationship(back_populates="coverage_profile", cascade="all, delete-orphan")
    waiting_periods: Mapped[list[WaitingPeriod]] = orm_relationship(back_populates="coverage_profile", cascade="all, delete-orphan")
    exclusions: Mapped[list[Exclusion]] = orm_relationship(back_populates="coverage_profile", cascade="all, delete-orphan")


class SubLimit(Base):
    __tablename__ = "sub_limit"

    id: Mapped[UUID] = uuid_pk()
    coverage_profile_id: Mapped[UUID] = mapped_column(ForeignKey("coverage_profile.id", ondelete="CASCADE"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    cap_amount_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cap_amount_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    cap_amount_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    cap_amount_original_value: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cap_amount_user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    cap_basis: Mapped[str] = mapped_column(String(80), nullable=False)
    percent_value: Mapped[float | None] = mapped_column(Float, nullable=True)

    coverage_profile: Mapped[CoverageProfile] = orm_relationship(back_populates="sub_limits")


class WaitingPeriod(Base):
    __tablename__ = "waiting_period"

    id: Mapped[UUID] = uuid_pk()
    coverage_profile_id: Mapped[UUID] = mapped_column(ForeignKey("coverage_profile.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    months_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    months_confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    months_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    months_original_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    months_user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    applies_to: Mapped[str | None] = mapped_column(Text, nullable=True)
    starts_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    expires_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    coverage_profile: Mapped[CoverageProfile] = orm_relationship(back_populates="waiting_periods")


class Exclusion(Base):
    __tablename__ = "exclusion"

    id: Mapped[UUID] = uuid_pk()
    coverage_profile_id: Mapped[UUID] = mapped_column(ForeignKey("coverage_profile.id", ondelete="CASCADE"), nullable=False, index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    provenance: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    original_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    coverage_profile: Mapped[CoverageProfile] = orm_relationship(back_populates="exclusions")


class DocumentChunk(Base):
    __tablename__ = "document_chunk"

    id: Mapped[UUID] = uuid_pk()
    document_id: Mapped[UUID] = mapped_column(ForeignKey("document.id", ondelete="CASCADE"), nullable=False, index=True)
    page: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    bbox: Mapped[dict[str, Any] | list[float] | None] = mapped_column(JSON, nullable=True)

    document: Mapped[Document] = orm_relationship(back_populates="chunks")


class InsurerTermMap(Base):
    __tablename__ = "insurer_term_map"

    insurer_id: Mapped[UUID] = mapped_column(ForeignKey("insurer.id", ondelete="CASCADE"), primary_key=True)
    raw_term: Mapped[str] = mapped_column(String(255), primary_key=True)
    canonical_term: Mapped[str] = mapped_column(String(255), nullable=False, index=True)

    insurer: Mapped[Insurer] = orm_relationship(back_populates="term_maps")


class Job(Base):
    __tablename__ = "job"
    __table_args__ = (
        UniqueConstraint("household_id", "idempotency_key", name="uq_job_household_idempotency_key"),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_job_status",
        ),
    )

    id: Mapped[UUID] = uuid_pk()
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="queued")
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=utc_now)
