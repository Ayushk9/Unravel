"""policy_question.models: which Gemini model answered each call of a question.

{"answer": "gemini-3.8-flash", "judge": "gemini-3.7-flash", "rewrite": ...}.
The fallback model (GEMINI_FALLBACK_MODEL) is used only after the primary's
retries fail, so this records when that happened. Null for rows made before.

Revision ID: 0007_policy_question_models
Revises: 0006_chunk_search
Create Date: 2026-10-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_policy_question_models"
down_revision: str | None = "0006_chunk_search"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("policy_question", sa.Column("models", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("policy_question", "models")
