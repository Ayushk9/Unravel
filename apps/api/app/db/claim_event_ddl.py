"""Database objects for the claim event log that SQLAlchemy models cannot express.

Two things live in the database itself rather than in Python:

1. APPEND-ONLY ENFORCEMENT (triggers)

   The event log is the claim's audit trail: what happened, in what order,
   and when it was recorded. Its value depends on nobody being able to edit
   history afterwards. If "never update or delete an event" were only a rule
   in the Python code, any bug, any future endpoint, any script, or anyone
   with a SQL console could break it and nothing would notice.

   So the rule is enforced by the DBMS. A trigger is a function the database
   runs automatically before a statement takes effect. These triggers run
   before any UPDATE, DELETE or TRUNCATE on claim_event and raise an error,
   which aborts the statement. The application's database user can INSERT
   events and SELECT them, and that is all, no matter what code it runs.

   Honest limit: the table's owner (or a superuser) can drop the trigger.
   This protects against application bugs and casual edits, not against a
   database administrator. Full protection would need a separate, less
   privileged role for the application.

2. CURRENT STATE AS A PROJECTION (view)

   A claim has no "status" column. Its current state is, by definition, the
   to_state of its latest event. A stored status column would be a second
   copy of that fact which could disagree with the log after a failed
   update. The view computes it from the log every time, so it cannot
   disagree.

   DISTINCT ON (claim_id) keeps the first row of each claim_id group, and
   ORDER BY claim_id, seq DESC makes that first row the highest seq.

The same statements are embedded, as literal text, in the Alembic migration
0003_claims (a migration must not change when this file changes). A test
checks the two copies match. The test database is built with create_all,
which knows nothing of triggers or views, so it runs these directly.
"""

from __future__ import annotations

CREATE_REJECT_FUNCTION = """
CREATE OR REPLACE FUNCTION claim_event_reject_change() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'claim_event is append-only: % is not allowed', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql
""".strip()

CREATE_ROW_TRIGGER = """
CREATE TRIGGER claim_event_no_update_or_delete
    BEFORE UPDATE OR DELETE ON claim_event
    FOR EACH ROW EXECUTE FUNCTION claim_event_reject_change()
""".strip()

# A row trigger does not fire for TRUNCATE, which would otherwise empty the
# whole log in one statement.
CREATE_TRUNCATE_TRIGGER = """
CREATE TRIGGER claim_event_no_truncate
    BEFORE TRUNCATE ON claim_event
    FOR EACH STATEMENT EXECUTE FUNCTION claim_event_reject_change()
""".strip()

CREATE_CURRENT_STATE_VIEW = """
CREATE VIEW claim_current_state AS
    SELECT DISTINCT ON (claim_id)
        claim_id,
        to_state AS current_state,
        seq AS latest_seq,
        occurred_at AS since
    FROM claim_event
    ORDER BY claim_id, seq DESC
""".strip()

CREATE_STATEMENTS = (
    CREATE_REJECT_FUNCTION,
    CREATE_ROW_TRIGGER,
    CREATE_TRUNCATE_TRIGGER,
    CREATE_CURRENT_STATE_VIEW,
)

DROP_STATEMENTS = (
    "DROP VIEW IF EXISTS claim_current_state",
    "DROP TRIGGER IF EXISTS claim_event_no_truncate ON claim_event",
    "DROP TRIGGER IF EXISTS claim_event_no_update_or_delete ON claim_event",
    "DROP FUNCTION IF EXISTS claim_event_reject_change()",
)
