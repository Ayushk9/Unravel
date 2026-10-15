"""Two facts the user can now give: when continuous cover began, and what kind of city they live in.

policy.first_inception_date: the start of cover renewed without a break.
    Waiting periods are counted from it when it is set (D-39).
household.city_tier: metro, tier_2 or other, chosen by the household.
    The room-rent alert reads it (D-40).

Both nullable: null means the user has not said.

Revision ID: 0005_policy_dates_and_city_tier
Revises: 0004_claim_facts
Create Date: 2026-10-15
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005_policy_dates_and_city_tier"
down_revision: str | None = "0004_claim_facts"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("policy", sa.Column("first_inception_date", sa.Date(), nullable=True))
    op.add_column("household", sa.Column("city_tier", sa.Text(), nullable=True))
    op.create_check_constraint(op.f("ck_household_city_tier"), "household", "city_tier IN ('metro', 'tier_2', 'other')")


def downgrade() -> None:
    op.drop_constraint(op.f("ck_household_city_tier"), "household", type_="check")
    op.drop_column("household", "city_tier")
    op.drop_column("policy", "first_inception_date")
