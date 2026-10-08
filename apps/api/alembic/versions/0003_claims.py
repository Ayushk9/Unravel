"""Claims and their append-only event log.

claim         the facts of a claim. It has no status column.
claim_event   one row per thing that happened to a claim, numbered by seq.
              UNIQUE(claim_id, seq) gives each claim a single ordered history
              and makes concurrent transitions safe.
document      claim_id gains its foreign key to claim.

Two things here cannot be expressed as table definitions, so they are SQL:

  Triggers that reject UPDATE, DELETE and TRUNCATE on claim_event. The log is
  an audit trail; the database itself refuses to rewrite it, whatever the
  application code does.

  The view claim_current_state: a claim's state is the to_state of its
  latest event, computed from the log rather than stored beside it.

The SQL is duplicated in app/db/claim_event_ddl.py for the test database;
tests/test_claim_ddl.py checks the two copies are identical.

Revision ID: 0003_claims
Revises: 0002_job_pipeline
Create Date: 2026-10-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_claims"
down_revision: str | None = "0002_job_pipeline"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table('claim',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('household_id', sa.Uuid(), nullable=False),
        sa.Column('policy_id', sa.Uuid(), nullable=False),
        sa.Column('member_id', sa.Uuid(), nullable=False),
        sa.Column('claim_type', sa.Text(), nullable=False),
        sa.Column('admission_type', sa.Text(), nullable=False),
        sa.Column('hospital_name', sa.Text(), nullable=False),
        sa.Column('admitted_on', sa.Date(), nullable=True),
        sa.Column('discharged_on', sa.Date(), nullable=True),
        sa.Column('claimed_amount', sa.BigInteger(), nullable=True),
        sa.Column('settled_amount', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("admission_type IN ('planned', 'emergency', 'other')", name=op.f('ck_claim_admission_type')),
        sa.CheckConstraint("claim_type IN ('cashless', 'reimbursement', 'other')", name=op.f('ck_claim_claim_type')),
        sa.ForeignKeyConstraint(['household_id'], ['household.id'], name=op.f('fk_claim_household_id_household'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['member_id'], ['member.id'], name=op.f('fk_claim_member_id_member')),
        sa.ForeignKeyConstraint(['policy_id'], ['policy.id'], name=op.f('fk_claim_policy_id_policy')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_claim'))
    )
    op.create_index(op.f('ix_claim_household_id'), 'claim', ['household_id'], unique=False)
    op.create_index(op.f('ix_claim_policy_id'), 'claim', ['policy_id'], unique=False)
    op.create_table('claim_event',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('claim_id', sa.Uuid(), nullable=False),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('from_state', sa.Text(), nullable=True),
        sa.Column('to_state', sa.Text(), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.CheckConstraint("from_state IN ('intimated', 'documents_submitted', 'under_review', 'queried', 'approved', 'denied', 'escalated', 'resolved')", name=op.f('ck_claim_event_from_state')),
        sa.CheckConstraint("source IN ('user', 'insurer_letter', 'system')", name=op.f('ck_claim_event_source')),
        sa.CheckConstraint("to_state IN ('intimated', 'documents_submitted', 'under_review', 'queried', 'approved', 'denied', 'escalated', 'resolved')", name=op.f('ck_claim_event_to_state')),
        sa.CheckConstraint('seq >= 1', name=op.f('ck_claim_event_seq_positive')),
        sa.ForeignKeyConstraint(['claim_id'], ['claim.id'], name=op.f('fk_claim_event_claim_id_claim')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_claim_event')),
        sa.UniqueConstraint('claim_id', 'seq', name=op.f('uq_claim_event_claim_id_seq'))
    )
    op.create_index(op.f('ix_claim_event_claim_id'), 'claim_event', ['claim_id'], unique=False)
    op.create_foreign_key(op.f('fk_document_claim_id_claim'), 'document', 'claim', ['claim_id'], ['id'])

    # The function both triggers call: abort the statement.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION claim_event_reject_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'claim_event is append-only: % is not allowed', TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    # No UPDATE or DELETE of any event row.
    op.execute(
        """
        CREATE TRIGGER claim_event_no_update_or_delete
            BEFORE UPDATE OR DELETE ON claim_event
            FOR EACH ROW EXECUTE FUNCTION claim_event_reject_change()
        """
    )
    # No TRUNCATE either (row triggers do not fire for it).
    op.execute(
        """
        CREATE TRIGGER claim_event_no_truncate
            BEFORE TRUNCATE ON claim_event
            FOR EACH STATEMENT EXECUTE FUNCTION claim_event_reject_change()
        """
    )
    # Current state = to_state of the highest-seq event per claim.
    op.execute(
        """
        CREATE VIEW claim_current_state AS
            SELECT DISTINCT ON (claim_id)
                claim_id,
                to_state AS current_state,
                seq AS latest_seq,
                occurred_at AS since
            FROM claim_event
            ORDER BY claim_id, seq DESC
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS claim_current_state")
    op.execute("DROP TRIGGER IF EXISTS claim_event_no_truncate ON claim_event")
    op.execute("DROP TRIGGER IF EXISTS claim_event_no_update_or_delete ON claim_event")
    op.execute("DROP FUNCTION IF EXISTS claim_event_reject_change()")
    op.drop_constraint(op.f('fk_document_claim_id_claim'), 'document', type_='foreignkey')
    op.drop_index(op.f('ix_claim_event_claim_id'), table_name='claim_event')
    op.drop_table('claim_event')
    op.drop_index(op.f('ix_claim_policy_id'), table_name='claim')
    op.drop_index(op.f('ix_claim_household_id'), table_name='claim')
    op.drop_table('claim')
