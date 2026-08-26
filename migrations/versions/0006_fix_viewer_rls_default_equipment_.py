"""fix viewer RLS default-equipment visibility

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-26 04:15:00.000000

Bug found while building §5 (equipment timeline): migration 0004's viewer
policy allowed rows through when `equipment_id IS NULL`, on the assumption
that pre-existing/default-equipment predictions would be left NULL. But
0004's own backfill (`UPDATE predictions SET equipment_id = 1 WHERE
equipment_id IS NULL`) — and insert_prediction()'s `equipment_id: int = 1`
default added alongside §5 — mean every row, historical and new, actually
carries `equipment_id = 1`, never NULL. So the "nothing currently visible
changes" guarantee this whole RLS design was built around silently didn't
hold: every existing viewer account would see zero rows on Postgres unless
an admin explicitly granted them equipment 1 in user_equipment_scope.

Fix: the viewer policy now also treats equipment_id = 1 (the seeded
"Default Unit", guaranteed to exist) as globally visible, same as NULL.
Equipment id > 1 still requires an explicit user_equipment_scope grant —
that part of the design was correct and is unchanged.

Postgres only; no-op on SQLite (RLS doesn't exist there).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCOPED_TABLES = ("predictions", "alerts")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    bind = op.get_bind()
    for tbl in _SCOPED_TABLES:
        bind.execute(sa.text(f"DROP POLICY IF EXISTS {tbl}_viewer_policy ON {tbl}"))
        bind.execute(sa.text(f"""
            CREATE POLICY {tbl}_viewer_policy ON {tbl}
            FOR ALL USING (
                current_setting('app.user_role', true) = 'viewer'
                AND (
                    equipment_id IS NULL
                    OR equipment_id = 1
                    OR equipment_id IN (
                        SELECT equipment_id FROM user_equipment_scope
                        WHERE username = current_setting('app.username', true)
                    )
                )
            )
        """))


def downgrade() -> None:
    if not _is_postgres():
        return

    bind = op.get_bind()
    for tbl in _SCOPED_TABLES:
        bind.execute(sa.text(f"DROP POLICY IF EXISTS {tbl}_viewer_policy ON {tbl}"))
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
