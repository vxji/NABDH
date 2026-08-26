"""equipment and row level security

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-26 03:30:00.000000

NABDH didn't have an "equipment" concept before this — the 10 sensors are a
single implicit machine, and no prediction/alert row was ever scoped to a
piece of equipment. This introduces one: an `equipment` table, a nullable
`equipment_id` FK on predictions/alerts backfilled to a single "Default Unit"
row (id=1) so nothing currently visible changes, and `user_equipment_scope`
for assigning viewers to specific equipment.

On PostgreSQL only: enables Row-Level Security on predictions, alerts, and
audit_log, with one policy per role (admin/operator/viewer), so a viewer
cannot see another equipment's data even via a raw query bypassing the
application layer entirely. See docs/rls_policies.md for the full writeup,
including the "table owner bypasses RLS unless FORCE is set" gotcha.

No-op for RLS on SQLite — SQLite has no such feature; the equipment
table/columns are still created there (harmless, unused by the app's
existing endpoints — only new endpoints introduced alongside this migration
read them).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCOPED_TABLES = ("predictions", "alerts")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()

    equipment = op.create_table(
        "equipment",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("location", sa.String(200), nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.bulk_insert(equipment, [{
        "id": 1, "name": "Default Unit", "location": None,
        "created_at": "2026-08-26T00:00:00+00:00",
    }])
    # Postgres needs its sequence nudged past the explicitly-inserted id=1.
    if _is_postgres():
        bind.execute(sa.text("SELECT setval('equipment_id_seq', 1, true)"))

    for tbl in _SCOPED_TABLES:
        # Deliberately NOT using batch mode here: SQLite's batch mode adds a
        # column-with-FK by copying the table to a new one and dropping the
        # original — which also silently drops the activity_logs triggers
        # migration 0001 attached to that table. A plain, unconstrained
        # ALTER TABLE ADD COLUMN (supported natively by SQLite) sidesteps
        # that entirely; Postgres gets the real FK directly, no batch mode
        # needed there either.
        if _is_postgres():
            op.add_column(tbl, sa.Column(
                "equipment_id", sa.Integer,
                sa.ForeignKey("equipment.id", name=f"fk_{tbl}_equipment_id"),
                nullable=True,
            ))
        else:
            op.add_column(tbl, sa.Column("equipment_id", sa.Integer, nullable=True))
        bind.execute(sa.text(f"UPDATE {tbl} SET equipment_id = 1 WHERE equipment_id IS NULL"))

    op.create_table(
        "user_equipment_scope",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("equipment_id", sa.Integer, sa.ForeignKey("equipment.id"), nullable=False),
        sa.UniqueConstraint("username", "equipment_id", name="uq_user_equipment_scope"),
    )
    op.create_index("idx_user_equipment_scope_username", "user_equipment_scope", ["username"])

    if _is_postgres():
        _enable_rls(bind)


def _enable_rls(bind) -> None:
    for tbl in _SCOPED_TABLES:
        bind.execute(sa.text(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text(f"ALTER TABLE {tbl} FORCE ROW LEVEL SECURITY"))

        bind.execute(sa.text(f"""
            CREATE POLICY {tbl}_admin_policy ON {tbl}
            FOR ALL USING (current_setting('app.user_role', true) = 'admin')
        """))
        bind.execute(sa.text(f"""
            CREATE POLICY {tbl}_operator_policy ON {tbl}
            FOR ALL USING (current_setting('app.user_role', true) = 'operator')
        """))
        # Viewer: only rows for equipment they've been explicitly granted, OR
        # rows with no equipment assigned (equipment_id IS NULL) — this is
        # what keeps every row that existed before this migration visible to
        # existing viewer accounts; only *new*, explicitly multi-equipment
        # data gets scoped.
        bind.execute(sa.text(f"""
            CREATE POLICY {tbl}_viewer_policy ON {tbl}
            FOR ALL USING (
                current_setting('app.user_role', true) = 'viewer'
                AND (
                    equipment_id IS NULL
                    OR equipment_id IN (
                        SELECT equipment_id FROM user_equipment_scope
                        WHERE username = current_setting('app.username', true)
                    )
                )
            )
        """))

    # audit_log has no equipment concept and is already admin-only at the
    # application layer (main.py's /audit, /audit/security). RLS here is
    # defense-in-depth: only a session with app.user_role='admin' can see
    # any row at all, even via a raw query that bypassed require_admin.
    bind.execute(sa.text("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY"))
    bind.execute(sa.text("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY"))
    bind.execute(sa.text("""
        CREATE POLICY audit_log_admin_policy ON audit_log
        FOR ALL USING (current_setting('app.user_role', true) = 'admin')
    """))


def downgrade() -> None:
    bind = op.get_bind()
    if _is_postgres():
        for tbl in _SCOPED_TABLES:
            for policy in ("admin_policy", "operator_policy", "viewer_policy"):
                bind.execute(sa.text(f"DROP POLICY IF EXISTS {tbl}_{policy} ON {tbl}"))
            bind.execute(sa.text(f"ALTER TABLE {tbl} NO FORCE ROW LEVEL SECURITY"))
            bind.execute(sa.text(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY"))
        bind.execute(sa.text("DROP POLICY IF EXISTS audit_log_admin_policy ON audit_log"))
        bind.execute(sa.text("ALTER TABLE audit_log NO FORCE ROW LEVEL SECURITY"))
        bind.execute(sa.text("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY"))

    op.drop_index("idx_user_equipment_scope_username", table_name="user_equipment_scope")
    op.drop_table("user_equipment_scope")

    for tbl in _SCOPED_TABLES:
        op.drop_column(tbl, "equipment_id")

    op.drop_table("equipment")
