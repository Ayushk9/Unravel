"""policy.insurer_name and policy.user_entered_fields: identity typed by the user (D-46).

insurer_name           the insurer as the user typed it; the shared `insurer`
                       table is never written from user input
user_entered_fields    which identity fields and dates the user typed in

Backfill: a date already set can only have come from PATCH /policies/{id}
(Engine A never writes dates), so every set date is marked as user-entered.

Revision ID: 0009_policy_user_entered
Revises: 0008_grievance_draft
Create Date: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_policy_user_entered"
down_revision: str | None = "0008_grievance_draft"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("policy", sa.Column("insurer_name", sa.Text(), nullable=True))
    op.add_column(
        "policy",
        sa.Column("user_entered_fields", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
    )
    op.execute(
        """
        UPDATE policy SET user_entered_fields = ARRAY_REMOVE(ARRAY[
            CASE WHEN start_date IS NOT NULL THEN 'start_date' END,
            CASE WHEN end_date IS NOT NULL THEN 'end_date' END,
            CASE WHEN first_inception_date IS NOT NULL THEN 'first_inception_date' END
        ], NULL)
        """
    )


def downgrade() -> None:
    op.drop_column("policy", "user_entered_fields")
    op.drop_column("policy", "insurer_name")
