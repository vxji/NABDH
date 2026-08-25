"""notification_settings

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-26 02:47:30.082889

One row per (user, channel): lets each user pick which notification channels
(email / slack / webhook) they want, independent of the channels the system
supports overall.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "notification_settings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("config", sa.Text, nullable=True),
        sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("username", "channel", name="uq_notification_settings_user_channel"),
    )
    op.create_index("idx_notification_settings_username", "notification_settings", ["username"])
    op.create_index("idx_notification_settings_enabled", "notification_settings", ["enabled"])


def downgrade() -> None:
    op.drop_index("idx_notification_settings_enabled", table_name="notification_settings")
    op.drop_index("idx_notification_settings_username", table_name="notification_settings")
    op.drop_table("notification_settings")
