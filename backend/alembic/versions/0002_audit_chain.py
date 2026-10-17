"""Audit hash chain and append-only enforcement (§10.1).

hash = SHA256(prev_hash || canonical_json(payload) || occurred_at || event_type),
prev_hash = hash of the previous row for the same org, computed under a per-org
advisory lock so concurrent inserts cannot interleave and break the chain.
Chain order is occurred_at (stamped after the lock is taken), not id: identity values are
assigned before the trigger runs, so id order can differ from lock order under concurrency.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# One canonical expression, shared by the trigger and the verify query in app/services/audit.py.
HASH_EXPR = """encode(sha256(convert_to(
    coalesce({prev}, '') || ({payload})::text ||
    to_char(({occurred_at}) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') ||
    ({event_type}), 'UTF8')), 'hex')"""


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_events_chain() RETURNS trigger AS $$
        DECLARE
          last_hash CHAR(64);
        BEGIN
          PERFORM pg_advisory_xact_lock(hashtext('audit:' || NEW.org_id));
          SELECT hash INTO last_hash FROM audit_events
            WHERE org_id = NEW.org_id ORDER BY occurred_at DESC, id DESC LIMIT 1;
          NEW.occurred_at := date_trunc('microseconds', clock_timestamp());
          NEW.prev_hash := last_hash;
          NEW.hash := """
        + HASH_EXPR.format(
            prev="NEW.prev_hash",
            payload="NEW.payload",
            occurred_at="NEW.occurred_at",
            event_type="NEW.event_type",
        )
        + """;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_chain_trg
          BEFORE INSERT ON audit_events
          FOR EACH ROW EXECUTE FUNCTION audit_events_chain();
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_events_append_only() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_events is append-only: % is not permitted', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only_trg
          BEFORE UPDATE OR DELETE ON audit_events
          FOR EACH ROW EXECUTE FUNCTION audit_events_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only_trg ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_append_only()")
    op.execute("DROP TRIGGER IF EXISTS audit_events_chain_trg ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_chain()")
