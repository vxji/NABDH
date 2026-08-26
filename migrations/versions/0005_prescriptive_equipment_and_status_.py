"""prescriptive equipment and status tracking

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-26 04:00:00.000000

Adds equipment_id (backfilled to the "Default Unit", id=1, same as
migration 0004 did for predictions/alerts) and resolved_at to
prescriptive_actions — needed by §5's equipment timeline, whose
"last actual maintenance" comes from the most recently RESOLVED
prescriptive action for that equipment. There was previously no way to
mark a prescriptive action resolved at all; PATCH /prescriptive/{id}/status
(added alongside this migration) is what sets resolved_at.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    bind = op.get_bind()

    if _is_postgres():
        op.add_column("prescriptive_actions", sa.Column(
            "equipment_id", sa.Integer,
            sa.ForeignKey("equipment.id", name="fk_prescriptive_actions_equipment_id"),
            nullable=True,
        ))
    else:
        # Plain column, no inline FK — see migration 0004's note on why
        # SQLite's batch-mode (needed for an inline FK) recreates the table
        # and silently drops any triggers attached to it.
        op.add_column("prescriptive_actions", sa.Column("equipment_id", sa.Integer, nullable=True))

    op.add_column("prescriptive_actions", sa.Column("resolved_at", sa.String(40), nullable=True))

    bind.execute(sa.text("UPDATE prescriptive_actions SET equipment_id = 1 WHERE equipment_id IS NULL"))


def downgrade() -> None:
    op.drop_column("prescriptive_actions", "resolved_at")
    op.drop_column("prescriptive_actions", "equipment_id")
