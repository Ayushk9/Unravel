"""The coverage profile extracted from a policy document.

Every Extracted[T] field is stored as five columns sharing a prefix:

    <prefix>_value            the current value (changes when the user corrects it)
    <prefix>_confidence       high | medium | low
    <prefix>_provenance       JSONB: {document_id, page, bbox, snippet}, or null
    <prefix>_original_value   what the parser extracted; written once, never updated
    <prefix>_user_confirmed   true once the user has confirmed or corrected it

Comparing _value with _original_value is the extraction-accuracy evaluation
data, so the original must survive every correction. The conversion to and
from Extracted[T] lives in app/services/extracted_columns.py.

Money is BIGINT paise. Percentages, months and hours are double precision.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, DateTime, Double, ForeignKey, Integer, Text, false, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.ids import new_id
from app.db.base import CONFIDENCE_VALUES, Base, one_of

SUB_LIMIT_CATEGORIES = ("room_rent", "icu", "procedure", "ambulance", "opd", "other")
CAP_BASES = ("per_day", "per_claim", "per_policy_year", "percent_of_sum_insured", "other")
WAITING_PERIOD_KINDS = ("initial", "disease_specific", "pre_existing", "maternity", "other")


class CoverageProfile(Base):
    __tablename__ = "coverage_profile"
    __table_args__ = (
        CheckConstraint(one_of("sum_insured_confidence", CONFIDENCE_VALUES), name="sum_insured_confidence"),
        CheckConstraint(one_of("co_pay_percent_confidence", CONFIDENCE_VALUES), name="co_pay_percent_confidence"),
        CheckConstraint(
            one_of("intimation_deadline_hours_confidence", CONFIDENCE_VALUES),
            name="intimation_deadline_hours_confidence",
        ),
        CheckConstraint("extraction_completeness BETWEEN 0 AND 1", name="extraction_completeness"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    # One profile per policy.
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("policy.id", ondelete="CASCADE"), unique=True)

    # sum_insured: Extracted[int], paise
    sum_insured_value: Mapped[int | None] = mapped_column(BigInteger)
    sum_insured_confidence: Mapped[str] = mapped_column(Text)
    sum_insured_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sum_insured_original_value: Mapped[int | None] = mapped_column(BigInteger)
    sum_insured_user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    # co_pay_percent: Extracted[float]
    co_pay_percent_value: Mapped[float | None] = mapped_column(Double)
    co_pay_percent_confidence: Mapped[str] = mapped_column(Text)
    co_pay_percent_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    co_pay_percent_original_value: Mapped[float | None] = mapped_column(Double)
    co_pay_percent_user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    # intimation_deadline_hours: Extracted[float]
    intimation_deadline_hours_value: Mapped[float | None] = mapped_column(Double)
    intimation_deadline_hours_confidence: Mapped[str] = mapped_column(Text)
    intimation_deadline_hours_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    intimation_deadline_hours_original_value: Mapped[float | None] = mapped_column(Double)
    intimation_deadline_hours_user_confirmed: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )

    extraction_completeness: Mapped[float] = mapped_column(Double)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Read-only links to the profile's rows, so a list of policies can load all
    # its rows in one query per table (selectinload) instead of three queries
    # per policy. viewonly: rows are still written through their own tables.
    # lazy="raise": reading one that was not loaded up front is an error, never
    # a hidden extra round trip to the database.
    sub_limits: Mapped[list[SubLimit]] = relationship(viewonly=True, lazy="raise", order_by="SubLimit.position")
    waiting_periods: Mapped[list[WaitingPeriod]] = relationship(viewonly=True, lazy="raise", order_by="WaitingPeriod.position")
    exclusions: Mapped[list[Exclusion]] = relationship(viewonly=True, lazy="raise", order_by="Exclusion.position")


class SubLimit(Base):
    __tablename__ = "sub_limit"
    __table_args__ = (
        CheckConstraint(one_of("category", SUB_LIMIT_CATEGORIES), name="category"),
        CheckConstraint(one_of("cap_basis", CAP_BASES), name="cap_basis"),
        CheckConstraint(one_of("cap_amount_confidence", CONFIDENCE_VALUES), name="cap_amount_confidence"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    coverage_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("coverage_profile.id", ondelete="CASCADE"), index=True
    )
    # Order within the profile, so the list comes back as it was extracted.
    position: Mapped[int] = mapped_column(Integer)
    category: Mapped[str] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text)

    # cap_amount: Extracted[int], paise
    cap_amount_value: Mapped[int | None] = mapped_column(BigInteger)
    cap_amount_confidence: Mapped[str] = mapped_column(Text)
    cap_amount_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cap_amount_original_value: Mapped[int | None] = mapped_column(BigInteger)
    cap_amount_user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    cap_basis: Mapped[str] = mapped_column(Text)
    percent_value: Mapped[float | None] = mapped_column(Double)


class WaitingPeriod(Base):
    __tablename__ = "waiting_period"
    __table_args__ = (
        CheckConstraint(one_of("kind", WAITING_PERIOD_KINDS), name="kind"),
        CheckConstraint(one_of("months_confidence", CONFIDENCE_VALUES), name="months_confidence"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    coverage_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("coverage_profile.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)

    # months: Extracted[float]
    months_value: Mapped[float | None] = mapped_column(Double)
    months_confidence: Mapped[str] = mapped_column(Text)
    months_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    months_original_value: Mapped[float | None] = mapped_column(Double)
    months_user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    applies_to: Mapped[str | None] = mapped_column(Text)
    starts_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date)


class Exclusion(Base):
    """One permanent exclusion. The whole row is a single Extracted[str]."""

    __tablename__ = "exclusion"
    __table_args__ = (CheckConstraint(one_of("text_confidence", CONFIDENCE_VALUES), name="text_confidence"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    coverage_profile_id: Mapped[UUID] = mapped_column(
        ForeignKey("coverage_profile.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)

    # text: Extracted[str]
    text_value: Mapped[str | None] = mapped_column(Text)
    text_confidence: Mapped[str] = mapped_column(Text)
    text_provenance: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    text_original_value: Mapped[str | None] = mapped_column(Text)
    text_user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
