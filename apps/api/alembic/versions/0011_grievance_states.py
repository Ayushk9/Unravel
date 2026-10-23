"""claim_event states: grievance_sent and insurer_replied (D-49).

Rule 14(3)(a), Insurance Ombudsman Rules, 2017: a complaint to the Ombudsman
lies only after a written representation to the insurer and its rejection, an
unsatisfactory reply, or no reply within one month. Two states record those
steps. The state columns are TEXT with a CHECK (app/db/base.one_of), so adding
values means replacing the two CHECK constraints. Existing events are valid
under both the old and the new list.

Downgrade refuses to run while any event uses a new state: the event log is
append-only, so such rows cannot be removed to make the old constraint fit.

Revision ID: 0011_grievance_states
Revises: 0010_claim_denial_ground
Create Date: 2026-10-23
"""

from __future__ import annotations

from alembic import op

revision: str = "0011_grievance_states"
down_revision: str | None = "0010_claim_denial_ground"
branch_labels: str | None = None
depends_on: str | None = None

OLD = ("intimated", "documents_submitted", "under_review", "queried", "approved", "denied", "escalated", "resolved")
NEW = ("intimated", "documents_submitted", "under_review", "queried", "approved", "denied",
       "grievance_sent", "insurer_replied", "escalated", "resolved")


def _replace(states: tuple[str, ...]) -> None:
    allowed = ", ".join(f"'{state}'" for state in states)
    for column in ("from_state", "to_state"):
        op.drop_constraint(op.f(f"ck_claim_event_{column}"), "claim_event", type_="check")
        op.create_check_constraint(op.f(f"ck_claim_event_{column}"), "claim_event", f"{column} IN ({allowed})")


def upgrade() -> None:
    _replace(NEW)


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM claim_event WHERE to_state IN ('grievance_sent', 'insurer_replied')
                                                 OR from_state IN ('grievance_sent', 'insurer_replied')) THEN
            RAISE EXCEPTION 'claim_event rows use grievance_sent or insurer_replied; the append-only log cannot be downgraded';
          END IF;
        END $$;
        """
    )
    _replace(OLD)
