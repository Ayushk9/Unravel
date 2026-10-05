"""Insurers, and the mapping from each insurer's wording to our own categories."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base


class Insurer(Base):
    __tablename__ = "insurer"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text, unique=True)
    irdai_code: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InsurerTermMap(Base):
    """One insurer's phrase for something we have a canonical name for.

    Example: for one insurer, raw_term "Room, Boarding and Nursing Expenses"
    maps to canonical_field "sub_limit.category", canonical_value "room_rent".
    This is what lets policies from different insurers be compared.
    """

    __tablename__ = "insurer_term_map"
    __table_args__ = (UniqueConstraint("insurer_id", "raw_term", "canonical_field"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    insurer_id: Mapped[UUID] = mapped_column(ForeignKey("insurer.id", ondelete="CASCADE"), index=True)
    raw_term: Mapped[str] = mapped_column(Text)
    canonical_field: Mapped[str] = mapped_column(Text)
    canonical_value: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
