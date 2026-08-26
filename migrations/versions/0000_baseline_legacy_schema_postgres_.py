"""baseline legacy schema (postgres bootstrap)

Revision ID: 0000
Revises:
Create Date: 2026-08-26 03:20:00.000000

Mirrors database.py's init_db() DDL so a fresh PostgreSQL database gets the
same 7 tables SQLite dev already has (created by init_db(), which runs
before Alembic and is unaffected by this migration). No-op on SQLite.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0000'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return  # SQLite already has these tables via database.init_db()

    op.create_table(
        "predictions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), nullable=False, unique=True),
        sa.Column("timestamp", sa.String(40), nullable=False),
        sa.Column("prediction", sa.Integer, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("health_score", sa.Float, nullable=True),
        sa.Column("failure_mode", sa.String(40), nullable=True),
        sa.Column("ttf_hours", sa.Float, nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("model_version", sa.String(40), nullable=True),
        sa.Column("sensor_data", sa.Text, nullable=True),
        sa.Column("shap_values", sa.Text, nullable=True),
        sa.Column("top_factors", sa.Text, nullable=True),
        sa.Column("anomalies", sa.Text, nullable=True),
    )
    op.create_index("idx_predictions_timestamp", "predictions", ["timestamp"])
    op.create_index("idx_predictions_severity", "predictions", ["severity"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("sensor_data", sa.Text, nullable=True),
        sa.Column("acknowledged", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ack_at", sa.String(40), nullable=True),
    )
    op.create_index("idx_alerts_acknowledged", "alerts", ["acknowledged"])

    op.create_table(
        "prescriptive_actions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.String(40), nullable=False),
        sa.Column("failure_mode", sa.String(40), nullable=True),
        sa.Column("actions", sa.Text, nullable=False),
        sa.Column("priority", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
    )

    op.create_table(
        "rca_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), nullable=False, unique=True),
        sa.Column("timestamp", sa.String(40), nullable=False),
        sa.Column("primary_cause", sa.Text, nullable=False),
        sa.Column("causal_chain", sa.Text, nullable=False),
        sa.Column("failure_mode", sa.String(40), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
    )

    op.create_table(
        "drift_history",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("checked_at", sa.String(40), nullable=False),
        sa.Column("total_features_checked", sa.Integer, nullable=False),
        sa.Column("drifted_features", sa.Text, nullable=False),
        sa.Column("drift_details", sa.Text, nullable=False),
        sa.Column("retrain_triggered", sa.Integer, nullable=False, server_default="0"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("timestamp", sa.String(40), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("path", sa.String(200), nullable=False),
        sa.Column("status", sa.Integer, nullable=True),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
    )
    op.create_index("idx_audit_log_timestamp", "audit_log", ["timestamp"])

    op.create_table(
        "security_audit",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("username", sa.String(50), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("timestamp", sa.String(40), nullable=False),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("severity", sa.String(10), nullable=False, server_default="INFO"),
    )
    op.create_index("idx_sec_audit_event", "security_audit", ["event_type"])
    op.create_index("idx_sec_audit_username", "security_audit", ["username"])
    op.create_index("idx_sec_audit_timestamp", "security_audit", ["timestamp"])
    op.create_index("idx_sec_audit_severity", "security_audit", ["severity"])


def downgrade() -> None:
    if not _is_postgres():
        return
    for tbl in (
        "security_audit", "audit_log", "drift_history",
        "rca_records", "prescriptive_actions", "alerts", "predictions",
    ):
        op.drop_table(tbl)
