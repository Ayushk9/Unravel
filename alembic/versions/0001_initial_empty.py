"""Create the core data layer.

Revision ID: 0001_initial_empty
Revises:
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "0001_initial_empty"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create normalised household, document, policy, extraction, and job tables."""
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "household",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_table(
        "insurer",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("irdai_code", sa.String(64), nullable=True),
        sa.UniqueConstraint("irdai_code", name="uq_insurer_irdai_code"),
    )
    op.create_table(
        "member",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey(
            "household.id", ondelete="CASCADE"), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("relationship", sa.String(80), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
    )
    op.create_index("ix_member_household_id", "member", ["household_id"])
    op.create_table(
        "document",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey(
            "household.id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_name", sa.String(1024), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("storage_path", sa.String(2048),
                  nullable=False, unique=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("detected_type", sa.String(80), nullable=True),
        sa.Column("parse_status", sa.String(40),
                  nullable=False, server_default="queued"),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_document_household_id", "document", ["household_id"])
    op.create_table(
        "policy",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("household_id", uuid, sa.ForeignKey(
            "household.id", ondelete="CASCADE"), nullable=False),
        sa.Column("insurer_id", uuid, sa.ForeignKey(
            "insurer.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("policy_number", sa.String(255), nullable=False),
        sa.Column("product_name", sa.String(255), nullable=True),
        sa.Column("policy_type", sa.String(80), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("source_document_id", uuid, sa.ForeignKey(
            "document.id", ondelete="RESTRICT"), nullable=False),
        sa.UniqueConstraint("household_id", "policy_number",
                            name="uq_policy_household_policy_number"),
    )
    op.create_index("ix_policy_household_id", "policy", ["household_id"])
    op.create_index("ix_policy_insurer_id", "policy", ["insurer_id"])
    op.create_index("ix_policy_source_document_id",
                    "policy", ["source_document_id"])
    op.create_table(
        "coverage_profile",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("policy_id", uuid, sa.ForeignKey(
            "policy.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("sum_insured_value", sa.BigInteger(), nullable=True),
        sa.Column("sum_insured_confidence", sa.String(16), nullable=True),
        sa.Column("sum_insured_provenance", jsonb, nullable=True),
        sa.Column("sum_insured_original_value",
                  sa.BigInteger(), nullable=True),
        sa.Column("sum_insured_user_confirmed", sa.Boolean(),
                  nullable=False, server_default=sa.text("false")),
        sa.Column("co_pay_percent_value", sa.Float(), nullable=True),
        sa.Column("co_pay_percent_confidence", sa.String(16), nullable=True),
        sa.Column("co_pay_percent_provenance", jsonb, nullable=True),
        sa.Column("co_pay_percent_original_value", sa.Float(), nullable=True),
        sa.Column("co_pay_percent_user_confirmed", sa.Boolean(),
                  nullable=False, server_default=sa.text("false")),
        sa.Column("intimation_deadline_hours_value",
                  sa.Float(), nullable=True),
        sa.Column("intimation_deadline_hours_confidence",
                  sa.String(16), nullable=True),
        sa.Column("intimation_deadline_hours_provenance",
                  jsonb, nullable=True),
        sa.Column("intimation_deadline_hours_original_value",
                  sa.Float(), nullable=True),
        sa.Column("intimation_deadline_hours_user_confirmed",
                  sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("extraction_completeness", sa.Float(), nullable=False),
        sa.CheckConstraint("extraction_completeness >= 0 AND extraction_completeness <= 1",
                           name="ck_coverage_profile_completeness"),
    )
    op.create_table(
        "sub_limit",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("coverage_profile_id", uuid, sa.ForeignKey(
            "coverage_profile.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("cap_amount_value", sa.BigInteger(), nullable=True),
        sa.Column("cap_amount_confidence", sa.String(16), nullable=True),
        sa.Column("cap_amount_provenance", jsonb, nullable=True),
        sa.Column("cap_amount_original_value", sa.BigInteger(), nullable=True),
        sa.Column("cap_amount_user_confirmed", sa.Boolean(),
                  nullable=False, server_default=sa.text("false")),
        sa.Column("cap_basis", sa.String(80), nullable=False),
        sa.Column("percent_value", sa.Float(), nullable=True),
    )
    op.create_index("ix_sub_limit_coverage_profile_id",
                    "sub_limit", ["coverage_profile_id"])
    op.create_table(
        "waiting_period",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("coverage_profile_id", uuid, sa.ForeignKey(
            "coverage_profile.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("months_value", sa.Float(), nullable=True),
        sa.Column("months_confidence", sa.String(16), nullable=True),
        sa.Column("months_provenance", jsonb, nullable=True),
        sa.Column("months_original_value", sa.Float(), nullable=True),
        sa.Column("months_user_confirmed", sa.Boolean(),
                  nullable=False, server_default=sa.text("false")),
        sa.Column("applies_to", sa.Text(), nullable=True),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("expires_on", sa.Date(), nullable=True),
    )
    op.create_index("ix_waiting_period_coverage_profile_id",
                    "waiting_period", ["coverage_profile_id"])
    op.create_table(
        "exclusion",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("coverage_profile_id", uuid, sa.ForeignKey(
            "coverage_profile.id", ondelete="CASCADE"), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("confidence", sa.String(16), nullable=True),
        sa.Column("provenance", jsonb, nullable=True),
        sa.Column("original_value", sa.Text(), nullable=True),
        sa.Column("user_confirmed", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
    )
    op.create_index("ix_exclusion_coverage_profile_id",
                    "exclusion", ["coverage_profile_id"])
    op.create_table(
        "document_chunk",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("document_id", uuid, sa.ForeignKey(
            "document.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("bbox", jsonb, nullable=True),
    )
    op.create_index("ix_document_chunk_document_id",
                    "document_chunk", ["document_id"])
    op.create_table(
        "insurer_term_map",
        sa.Column("insurer_id", uuid, sa.ForeignKey(
            "insurer.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("raw_term", sa.String(255), primary_key=True),
        sa.Column("canonical_term", sa.String(255), nullable=False),
    )
    op.create_index("ix_insurer_term_map_canonical_term",
                    "insurer_term_map", ["canonical_term"])
    op.create_table(
        "job",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False,
                  server_default="queued"),
        sa.Column("progress", jsonb, nullable=True),
        sa.Column("result", jsonb, nullable=True),
        sa.Column("error", jsonb, nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("idempotency_key", name="uq_job_idempotency_key"),
    )


def downgrade() -> None:
    """Drop the data layer in dependency order."""
    op.drop_table("job")
    op.drop_table("insurer_term_map")
    op.drop_table("document_chunk")
    op.drop_table("exclusion")
    op.drop_table("waiting_period")
    op.drop_table("sub_limit")
    op.drop_table("coverage_profile")
    op.drop_table("policy")
    op.drop_table("document")
    op.drop_table("member")
    op.drop_table("insurer")
    op.drop_table("household")
