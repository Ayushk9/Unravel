"""Columns needed by the document job pipeline.

document: sha256, size_bytes (which exact file was uploaded) and warnings
          (Engine A's notes about the parse).
job:      payload (what to do), request_hash (idempotency), error_code and
          retryable (machine-readable failure details), started_at and
          finished_at (timing, and 24-hour retention of finished jobs).

Revision ID: 0002_job_pipeline
Revises: 0001_initial_schema
Create Date: 2026-10-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_job_pipeline"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("document", sa.Column("sha256", sa.Text(), nullable=True))
    op.add_column("document", sa.Column("size_bytes", sa.BigInteger(), nullable=True))
    op.add_column("document", sa.Column("warnings", postgresql.JSONB(), nullable=True))

    op.add_column("job", sa.Column("payload", postgresql.JSONB(), nullable=True))
    op.add_column("job", sa.Column("error_code", sa.Text(), nullable=True))
    op.add_column("job", sa.Column("retryable", sa.Boolean(), nullable=True))
    op.add_column("job", sa.Column("request_hash", sa.Text(), nullable=True))
    op.add_column("job", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("job", "finished_at")
    op.drop_column("job", "started_at")
    op.drop_column("job", "request_hash")
    op.drop_column("job", "retryable")
    op.drop_column("job", "error_code")
    op.drop_column("job", "payload")

    op.drop_column("document", "warnings")
    op.drop_column("document", "size_bytes")
    op.drop_column("document", "sha256")
