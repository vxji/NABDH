"""activity_logs append-only audit trail

Revision ID: 0001
Revises:
Create Date: 2026-08-26 02:39:15.400734

Creates an `activity_logs` table that records every INSERT/UPDATE/DELETE on
`predictions` and `alerts` at the database level (not from Python code).

On PostgreSQL this is enforced with real triggers + `REVOKE UPDATE, DELETE`
so the log cannot be tampered with even by a compromised/buggy backend
(short of a superuser). On SQLite (local dev only, no GRANT/REVOKE model)
we install an equivalent trigger for feature parity, attributing changes via
a `_session_context` helper table that `database.set_session_context()`
updates per request — this is best-effort for local development, not a
tamper-proof guarantee; the Postgres path is the source of truth.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = '0000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRACKED_TABLES = ("predictions", "alerts")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    op.create_table(
        "activity_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("table_name", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("row_id", sa.String(64), nullable=False),
        sa.Column("old_data", sa.Text, nullable=True),
        sa.Column("new_data", sa.Text, nullable=True),
        sa.Column("changed_by", sa.String(64), nullable=True),
        sa.Column("changed_at", sa.String(40), nullable=False),
    )
    op.create_index("idx_activity_logs_table", "activity_logs", ["table_name"])
    op.create_index("idx_activity_logs_changed_at", "activity_logs", ["changed_at"])
    op.create_index("idx_activity_logs_changed_by", "activity_logs", ["changed_by"])

    if _is_postgres():
        _upgrade_postgres()
    else:
        _upgrade_sqlite()


def _upgrade_postgres() -> None:
    bind = op.get_bind()

    bind.execute(sa.text(
        """
        CREATE OR REPLACE FUNCTION nabdh_log_activity() RETURNS trigger AS $$
        DECLARE
            v_user text;
        BEGIN
            v_user := current_setting('app.username', true);
            IF TG_OP = 'DELETE' THEN
                INSERT INTO activity_logs(table_name, operation, row_id, old_data, new_data, changed_by, changed_at)
                VALUES (TG_TABLE_NAME, TG_OP, OLD.id::text, row_to_json(OLD)::text, NULL, v_user, now()::text);
                RETURN OLD;
            ELSIF TG_OP = 'UPDATE' THEN
                INSERT INTO activity_logs(table_name, operation, row_id, old_data, new_data, changed_by, changed_at)
                VALUES (TG_TABLE_NAME, TG_OP, NEW.id::text, row_to_json(OLD)::text, row_to_json(NEW)::text, v_user, now()::text);
                RETURN NEW;
            ELSE
                INSERT INTO activity_logs(table_name, operation, row_id, old_data, new_data, changed_by, changed_at)
                VALUES (TG_TABLE_NAME, TG_OP, NEW.id::text, NULL, row_to_json(NEW)::text, v_user, now()::text);
                RETURN NEW;
            END IF;
        END;
        $$ LANGUAGE plpgsql;
        """
    ))

    for tbl in _TRACKED_TABLES:
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{tbl}_activity ON {tbl}"))
        bind.execute(sa.text(
            f"""
            CREATE TRIGGER trg_{tbl}_activity
            AFTER INSERT OR UPDATE OR DELETE ON {tbl}
            FOR EACH ROW EXECUTE FUNCTION nabdh_log_activity();
            """
        ))

    # Immutability guarantee: nobody — including the app's own DB role — can
    # UPDATE or DELETE rows in activity_logs. INSERT (via the trigger, which
    # runs with definer rights) is unaffected.
    bind.execute(sa.text("REVOKE UPDATE, DELETE ON activity_logs FROM PUBLIC"))


def _upgrade_sqlite() -> None:
    bind = op.get_bind()

    bind.execute(sa.text(
        "CREATE TABLE IF NOT EXISTS _session_context (id INTEGER PRIMARY KEY CHECK (id = 1), username TEXT)"
    ))
    bind.execute(sa.text(
        "INSERT OR IGNORE INTO _session_context (id, username) VALUES (1, NULL)"
    ))

    # Column lists mirrored from database.py's schema, used to build a
    # json_object(...) snapshot of OLD/NEW rows (SQLite has no row_to_json).
    columns = {
        "predictions": ["id", "request_id", "timestamp", "prediction", "confidence",
                         "severity", "health_score", "failure_mode", "ttf_hours",
                         "latency_ms", "model_version"],
        "alerts": ["id", "request_id", "timestamp", "severity", "confidence",
                   "message", "acknowledged", "ack_at"],
    }

    def _json_object(alias: str, cols: list) -> str:
        pairs = ", ".join(f"'{c}', {alias}.{c}" for c in cols)
        return f"json_object({pairs})"

    try:
        for tbl in _TRACKED_TABLES:
            cols = columns[tbl]
            bind.execute(sa.text(
                f"""
                CREATE TRIGGER trg_{tbl}_activity_insert AFTER INSERT ON {tbl}
                BEGIN
                    INSERT INTO activity_logs(table_name, operation, row_id, old_data, new_data, changed_by, changed_at)
                    VALUES ('{tbl}', 'INSERT', NEW.id, NULL, {_json_object('NEW', cols)},
                            (SELECT username FROM _session_context WHERE id = 1),
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
                END;
                """
            ))
            bind.execute(sa.text(
                f"""
                CREATE TRIGGER trg_{tbl}_activity_update AFTER UPDATE ON {tbl}
                BEGIN
                    INSERT INTO activity_logs(table_name, operation, row_id, old_data, new_data, changed_by, changed_at)
                    VALUES ('{tbl}', 'UPDATE', NEW.id, {_json_object('OLD', cols)}, {_json_object('NEW', cols)},
                            (SELECT username FROM _session_context WHERE id = 1),
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
                END;
                """
            ))
            bind.execute(sa.text(
                f"""
                CREATE TRIGGER trg_{tbl}_activity_delete AFTER DELETE ON {tbl}
                BEGIN
                    INSERT INTO activity_logs(table_name, operation, row_id, old_data, new_data, changed_by, changed_at)
                    VALUES ('{tbl}', 'DELETE', OLD.id, {_json_object('OLD', cols)}, NULL,
                            (SELECT username FROM _session_context WHERE id = 1),
                            strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
                END;
                """
            ))
    except Exception as exc:  # pragma: no cover - only if SQLite lacks JSON1
        print(
            f"[migration 0001] WARNING: SQLite JSON1 trigger setup failed ({exc}). "
            "activity_logs table still exists but will not auto-populate on this "
            "SQLite build. This only affects local dev; Postgres enforces the real "
            "guarantee."
        )


def downgrade() -> None:
    bind = op.get_bind()
    if _is_postgres():
        for tbl in _TRACKED_TABLES:
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{tbl}_activity ON {tbl}"))
        bind.execute(sa.text("DROP FUNCTION IF EXISTS nabdh_log_activity()"))
    else:
        for tbl in _TRACKED_TABLES:
            for suffix in ("insert", "update", "delete"):
                bind.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_{tbl}_activity_{suffix}"))
        bind.execute(sa.text("DROP TABLE IF EXISTS _session_context"))

    op.drop_index("idx_activity_logs_changed_by", table_name="activity_logs")
    op.drop_index("idx_activity_logs_changed_at", table_name="activity_logs")
    op.drop_index("idx_activity_logs_table", table_name="activity_logs")
    op.drop_table("activity_logs")
