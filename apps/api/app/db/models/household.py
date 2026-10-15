"""A household and the people in it. Every user-owned row traces back to a household."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.ids import new_id
from app.db.base import Base, one_of

# The household's own choice of what kind of city it lives in (D-40). "other" is the escape hatch.
CITY_TIERS = ("metro", "tier_2", "other")


class Household(Base):
    __tablename__ = "household"
    __table_args__ = (CheckConstraint(one_of("city_tier", CITY_TIERS), name="city_tier"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text)
    # The Supabase Auth user id: the `sub` claim of the login token. This is
    # how a request is tied to a household (D-10); no request ever names one.
    auth_user_id: Mapped[UUID] = mapped_column(unique=True)
    # Null until the household says. Only the room-rent alert reads it.
    city_tier: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Member(Base):
    __tablename__ = "member"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    full_name: Mapped[str] = mapped_column(Text)
    relationship: Mapped[str] = mapped_column(Text)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
