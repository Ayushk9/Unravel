"""A policy and which household members it covers."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, Date, DateTime, ForeignKey, Table, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, one_of

POLICY_TYPES = ("individual", "family_floater", "group_employer", "top_up", "other")


class Policy(Base):
    __tablename__ = "policy"
    __table_args__ = (CheckConstraint(one_of("policy_type", POLICY_TYPES), name="policy_type"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    source_document_id: Mapped[UUID] = mapped_column(ForeignKey("document.id"), index=True)

    # Nullable because Engine A does not extract these yet. A null here means
    # "not known", which is the truth; a made-up value would not be.
    insurer_id: Mapped[UUID | None] = mapped_column(ForeignKey("insurer.id"))
    policy_number: Mapped[str | None] = mapped_column(Text)
    product_name: Mapped[str | None] = mapped_column(Text)
    policy_type: Mapped[str | None] = mapped_column(Text)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Which members a policy covers. A plain link table: one row per (policy, member).
policy_member = Table(
    "policy_member",
    Base.metadata,
    Column("policy_id", ForeignKey("policy.id", ondelete="CASCADE"), primary_key=True),
    Column("member_id", ForeignKey("member.id", ondelete="CASCADE"), primary_key=True),
)
