"""Facts about a claim that the eligibility rules read.

All nullable: null means the user has not answered yet, and the rules then
report the check as unknown instead of guessing. Dates are DATE, money is
BIGINT paise, and the two "matched" columns hold positions in the policy's
extracted waiting-period and exclusion lists.

Revision ID: 0004_claim_facts
Revises: 0003_claims
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004_claim_facts"
down_revision: str | None = "0003_claims"
branch_labels: str | None = None
depends_on: str | None = None

COLUMNS = (
    ("diagnosis", sa.Text()),
    ("condition_is_pre_existing", sa.Boolean()),
    ("first_diagnosed_on", sa.Date()),
    ("matched_waiting_periods", sa.ARRAY(sa.Integer())),
    ("matched_exclusions", sa.ARRAY(sa.Integer())),
    ("planned_room_rent_per_day", sa.BigInteger()),
)


def upgrade() -> None:
    for name, column_type in COLUMNS:
        op.add_column("claim", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("claim", name)
