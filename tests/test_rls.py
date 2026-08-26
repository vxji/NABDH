"""
Live PostgreSQL tests for §1's Row-Level Security policies (migration
0004_equipment_and_row_level_security). These connect directly with raw SQL
— bypassing the FastAPI app and database.py entirely — to prove enforcement
happens at the database level, independent of any application code.

Requires TEST_DATABASE_URL set to a postgresql:// DSN pointing at a
scratch/test database (migrations are applied automatically, destructively —
do not point this at anything with real data). Skips automatically otherwise.
This repo's author could not run these against a live Postgres in the
environment these tests were written in (no Docker/psql available) — they're
written from careful reading of Postgres RLS semantics, not confirmed by
actually executing them. Please run `pytest -m postgres` yourself against a
real Postgres before relying on this migration in production.

IMPORTANT: if TEST_DATABASE_URL's role is a Postgres superuser (e.g. the
default `postgres` user in a fresh official Postgres Docker image),
RLS is bypassed unconditionally regardless of FORCE ROW LEVEL SECURITY —
that's Postgres's own rule, not a bug in this migration. These tests detect
that and skip with an explanatory message; create a non-superuser role to
get a real signal.
"""
import os
import pathlib

import pytest

pytestmark = pytest.mark.postgres

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "")

if not TEST_DATABASE_URL.startswith("postgresql"):
    pytest.skip(
        "TEST_DATABASE_URL not set to a postgresql:// DSN — skipping live RLS tests",
        allow_module_level=True,
    )

from sqlalchemy import create_engine, text  # noqa: E402

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def pg_engine():
    from alembic import command
    from alembic.config import Config

    engine = create_engine(TEST_DATABASE_URL)

    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        is_super = conn.execute(
            text("SELECT usesuper FROM pg_user WHERE usename = current_user")
        ).scalar()
    if is_super:
        pytest.skip(
            "TEST_DATABASE_URL connects as a Postgres superuser — RLS is bypassed "
            "unconditionally for superusers, so this connection can't exercise the "
            "policies at all. Create a non-superuser role and point TEST_DATABASE_URL "
            "at it instead."
        )

    yield engine
    engine.dispose()


def _set_session(conn, username: str, role: str) -> None:
    conn.execute(text("SELECT set_config('app.username', :u, false)"), {"u": username})
    conn.execute(text("SELECT set_config('app.user_role', :r, false)"), {"r": role})


def test_viewer_cannot_see_other_equipments_predictions(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO equipment (id, name, created_at) VALUES (2, 'Pump B', now()::text) "
            "ON CONFLICT (id) DO NOTHING"
        ))
        conn.execute(text(
            "INSERT INTO predictions (request_id, timestamp, prediction, confidence, severity, equipment_id) "
            "VALUES ('rls-test-out-of-scope', now()::text, 1, 0.9, 'HIGH', 2) "
            "ON CONFLICT (request_id) DO NOTHING"
        ))
        conn.execute(text(
            "INSERT INTO user_equipment_scope (username, equipment_id) VALUES ('rls_test_viewer', 1) "
            "ON CONFLICT (username, equipment_id) DO NOTHING"
        ))

    with pg_engine.connect() as conn:
        _set_session(conn, "rls_test_viewer", "viewer")
        rows = conn.execute(text(
            "SELECT request_id FROM predictions WHERE request_id = 'rls-test-out-of-scope'"
        )).fetchall()
        assert rows == [], "viewer scoped to equipment 1 should not see equipment 2's prediction"

    with pg_engine.connect() as conn:
        _set_session(conn, "admin_test_user", "admin")
        rows = conn.execute(text(
            "SELECT request_id FROM predictions WHERE request_id = 'rls-test-out-of-scope'"
        )).fetchall()
        assert len(rows) == 1, "admin should see every equipment's predictions"


def test_viewer_still_sees_unscoped_default_equipment_rows(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO predictions (request_id, timestamp, prediction, confidence, severity, equipment_id) "
            "VALUES ('rls-test-default-unit', now()::text, 0, 0.1, 'NONE', 1) "
            "ON CONFLICT (request_id) DO NOTHING"
        ))

    with pg_engine.connect() as conn:
        _set_session(conn, "some_unscoped_viewer", "viewer")
        rows = conn.execute(text(
            "SELECT request_id FROM predictions WHERE request_id = 'rls-test-default-unit'"
        )).fetchall()
        assert len(rows) == 1, "a viewer with zero explicit grants must still see the default equipment's rows"


def test_audit_log_hidden_from_non_admin_roles(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO audit_log (timestamp, method, path) VALUES (now()::text, 'GET', '/rls-test-path')"
        ))

    for role in ("viewer", "operator"):
        with pg_engine.connect() as conn:
            _set_session(conn, "someone", role)
            rows = conn.execute(text(
                "SELECT * FROM audit_log WHERE path = '/rls-test-path'"
            )).fetchall()
            assert rows == [], f"{role} must not see any audit_log row"

    with pg_engine.connect() as conn:
        _set_session(conn, "admin", "admin")
        rows = conn.execute(text("SELECT * FROM audit_log WHERE path = '/rls-test-path'")).fetchall()
        assert len(rows) == 1


def test_activity_logs_cannot_be_updated_or_deleted(pg_engine):
    with pg_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO predictions (request_id, timestamp, prediction, confidence, severity, equipment_id) "
            "VALUES ('rls-test-revoke-check', now()::text, 1, 0.9, 'HIGH', 1) "
            "ON CONFLICT (request_id) DO NOTHING"
        ))

    with pg_engine.connect() as conn:
        # new_data is stored as TEXT (row_to_json(...)::text), not JSONB —
        # cast it back to json to pick a field out of it.
        row = conn.execute(text(
            "SELECT id FROM activity_logs WHERE (new_data::json)->>'request_id' = 'rls-test-revoke-check' "
            "ORDER BY id DESC LIMIT 1"
        )).fetchone()
    assert row is not None, "insert on predictions should have populated activity_logs via trigger"

    import sqlalchemy.exc

    with pytest.raises(sqlalchemy.exc.DBAPIError):
        with pg_engine.begin() as conn:
            conn.execute(text("UPDATE activity_logs SET changed_by = 'tampered' WHERE id = :id"), {"id": row[0]})

    with pytest.raises(sqlalchemy.exc.DBAPIError):
        with pg_engine.begin() as conn:
            conn.execute(text("DELETE FROM activity_logs WHERE id = :id"), {"id": row[0]})
