"""Search for policy Q&A: a vector and a keyword index on every chunk, and the question log.

document_chunk.embedding    vector(1024), BGE-M3's dense vector; null until indexed
document_chunk.search_text  tsvector generated from `text` ('english'), with a GIN index
policy_question             every question asked and how it was answered (D-42)

pgvector must be available. On Supabase it is installed in the `extensions`
schema; CREATE EXTENSION IF NOT EXISTS does nothing when it already is. The
downgrade leaves the extension alone: other things may use it.

No vector index (HNSW / IVFFlat): every search is filtered to one document,
a few hundred rows, where an exact scan is fast and complete. An approximate
index would be searched first and filtered second, and could return fewer
than the 20 rows asked for.

Revision ID: 0006_chunk_search
Revises: 0005_policy_dates_and_city_tier
Create Date: 2026-10-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_chunk_search"
down_revision: str | None = "0005_policy_dates_and_city_tier"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER TABLE document_chunk ADD COLUMN embedding vector(1024)")
    op.execute(
        "ALTER TABLE document_chunk ADD COLUMN search_text tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', text)) STORED"
    )
    op.create_index("ix_document_chunk_search_text", "document_chunk", ["search_text"], postgresql_using="gin")

    op.create_table(
        "policy_question",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("script", sa.Text(), nullable=False),
        sa.Column("search_query", sa.Text(), nullable=True),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("retrieved", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("generated", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("verification", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("timings", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["household_id"], ["household.id"], name=op.f("fk_policy_question_household_id_household"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_id"], ["policy.id"], name=op.f("fk_policy_question_policy_id_policy"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_question")),
    )
    op.create_index(op.f("ix_policy_question_household_id"), "policy_question", ["household_id"])
    op.create_index(op.f("ix_policy_question_policy_id"), "policy_question", ["policy_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_policy_question_policy_id"), table_name="policy_question")
    op.drop_index(op.f("ix_policy_question_household_id"), table_name="policy_question")
    op.drop_table("policy_question")
    op.drop_index("ix_document_chunk_search_text", table_name="document_chunk")
    op.drop_column("document_chunk", "search_text")
    op.drop_column("document_chunk", "embedding")
