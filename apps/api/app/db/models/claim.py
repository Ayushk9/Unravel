"""A claim and its append-only event log."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.claims.state_machine import STATES
from app.core.ids import new_id
from app.db.base import Base, one_of

CLAIM_TYPES = ("cashless", "reimbursement", "other")
ADMISSION_TYPES = ("planned", "emergency", "other")
EVENT_SOURCES = ("user", "insurer_letter", "system")


class Claim(Base):
    """The facts of a claim. Deliberately has NO status column.

    A claim's current state is the to_state of its latest event (see
    claim_current_state below). Field names match the wire `Claim` type.
    """

    __tablename__ = "claim"
    __table_args__ = (
        CheckConstraint(one_of("claim_type", CLAIM_TYPES), name="claim_type"),
        CheckConstraint(one_of("admission_type", ADMISSION_TYPES), name="admission_type"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    household_id: Mapped[UUID] = mapped_column(ForeignKey("household.id", ondelete="CASCADE"), index=True)
    policy_id: Mapped[UUID] = mapped_column(ForeignKey("policy.id"), index=True)
    member_id: Mapped[UUID] = mapped_column(ForeignKey("member.id"))
    claim_type: Mapped[str] = mapped_column(Text)
    admission_type: Mapped[str] = mapped_column(Text)
    hospital_name: Mapped[str] = mapped_column(Text)
    admitted_on: Mapped[date | None] = mapped_column(Date)
    discharged_on: Mapped[date | None] = mapped_column(Date)
    # Integer paise.
    claimed_amount: Mapped[int | None] = mapped_column(BigInteger)
    settled_amount: Mapped[int | None] = mapped_column(BigInteger)

    # --- facts the user tells us, read by the eligibility rules (D-37) ---
    # Every one is nullable: null means "not answered yet", which the rules
    # report as unknown rather than guess.
    # Display text only. No rule reads it: diagnoses are never matched by keyword.
    diagnosis: Mapped[str | None] = mapped_column(Text)
    condition_is_pre_existing: Mapped[bool | None] = mapped_column(Boolean)
    first_diagnosed_on: Mapped[date | None] = mapped_column(Date)
    # Positions in the policy's waiting_periods / exclusions lists the user
    # says apply. Null: not answered. Empty array: none apply.
    matched_waiting_periods: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    matched_exclusions: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    planned_room_rent_per_day: Mapped[int | None] = mapped_column(BigInteger)  # paise

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClaimEvent(Base):
    """One entry in a claim's history. Rows are inserted and never changed.

    The database rejects UPDATE, DELETE and TRUNCATE on this table (see
    app/db/claim_event_ddl.py).

    Two different times are recorded, because they answer different questions:

      occurred_at   when it happened in the real world, as the user states
                    it (the date printed on the insurer's denial letter).
                    Deadlines are counted from this.
      recorded_at   when the row was written. Set by the database. Shows how
                    late something was logged, and cannot be chosen by a user.
    """

    __tablename__ = "claim_event"
    __table_args__ = (
        # One event per position in a claim's history. This constraint is
        # also what makes concurrent transitions safe: see app/claims/events.py.
        UniqueConstraint("claim_id", "seq"),
        CheckConstraint(one_of("from_state", STATES), name="from_state"),
        CheckConstraint(one_of("to_state", STATES), name="to_state"),
        CheckConstraint(one_of("source", EVENT_SOURCES), name="source"),
        CheckConstraint("seq >= 1", name="seq_positive"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)
    # No ON DELETE CASCADE: a claim with history cannot be deleted either.
    claim_id: Mapped[UUID] = mapped_column(ForeignKey("claim.id"), index=True)
    # 1 for the first event, then 2, 3, ... The order of the log.
    seq: Mapped[int] = mapped_column(Integer)
    # Null only for the first event.
    from_state: Mapped[str | None] = mapped_column(Text)
    to_state: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    note: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    # The Supabase Auth user who logged it. Null for events the system writes.
    created_by: Mapped[UUID | None] = mapped_column()


# The view from claim_event_ddl.py, described so it can be queried like a
# table. It is on its own MetaData so that create_all and Alembic do not
# mistake it for a table to create.
_view_metadata = MetaData()
claim_current_state = Table(
    "claim_current_state",
    _view_metadata,
    Column("claim_id", Uuid, primary_key=True),
    Column("current_state", Text),
    Column("latest_seq", Integer),
    Column("since", DateTime(timezone=True)),
)
