"""claim.denial_ground: the insurer's denial ground, as the user chose it (D-48).

One of the eligibility check ids, validated by the API (the list can grow
without a migration). Null means not answered.

Revision ID: 0010_claim_denial_ground
Revises: 0009_policy_user_entered
Create Date: 2026-10-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0010_claim_denial_ground"
down_revision: str | None = "0009_policy_user_entered"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("claim", sa.Column("denial_ground", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("claim", "denial_ground")
