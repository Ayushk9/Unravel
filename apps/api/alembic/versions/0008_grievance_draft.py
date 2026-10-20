"""grievance_draft: every grievance letter drafted, with its verification record (D-43).

Revision ID: 0008_grievance_draft
Revises: 0007_policy_question_models
Create Date: 2026-10-20
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_grievance_draft"
down_revision: str | None = "0007_policy_question_models"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "grievance_draft",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("rung", sa.Text(), nullable=False),
        sa.Column("retrieved", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("generated", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("verification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("models", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("timings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], name=op.f("fk_grievance_draft_household_id_household"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claim_id"], ["claim.id"], name=op.f("fk_grievance_draft_claim_id_claim"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_grievance_draft")),
    )
    op.create_index(op.f("ix_grievance_draft_household_id"), "grievance_draft", ["household_id"])
    op.create_index(op.f("ix_grievance_draft_claim_id"), "grievance_draft", ["claim_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_grievance_draft_claim_id"), table_name="grievance_draft")
    op.drop_index(op.f("ix_grievance_draft_household_id"), table_name="grievance_draft")
    op.drop_table("grievance_draft")
