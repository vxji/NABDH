"""extensible permissions

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-26 03:05:00.000000

Adds `permissions` (key + description) and `role_permissions` (role -> key)
so authorization can grow beyond the 3 fixed roles without code changes.
Seeded so the 3 existing roles (viewer/operator/admin) get permission sets
that are byte-for-byte equivalent to today's `_ROLE_LEVEL` hierarchy in
auth.py — nothing currently gated by `require_role` changes behavior.

Adds one extra key, `manage_permissions` (admin-only), beyond the 4 the spec
asked for as seed data — needed so the new GET/POST /permissions endpoints
have something real to gate on and demonstrate require_permission()
end-to-end via HTTP, not just in unit tests.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_PERMISSIONS = [
    ("view_history",             "View prediction history"),
    ("view_analytics",           "View aggregated analytics"),
    ("view_alerts",              "View alert history"),
    ("view_drift",               "View drift reports/history"),
    ("run_prediction",           "Submit sensor readings for prediction"),
    ("acknowledge_alert",        "Acknowledge an open alert"),
    ("view_rca",                 "View root cause analysis"),
    ("view_prescriptive",        "View prescriptive maintenance actions"),
    ("view_audit",               "View the API request audit log"),
    ("register_user",            "Create new user accounts"),
    ("view_security_audit",      "View authentication/security events"),
    ("view_immutable_log",       "View the append-only activity_logs trail"),
    ("manage_permissions",       "View and reload the role/permission mapping"),
    ("edit_sensor_thresholds",   "Edit per-sensor critical thresholds"),
    ("approve_maintenance_action", "Approve a prescriptive maintenance action"),
    ("retrain_model",            "Trigger model retraining"),
    ("export_reports",           "Export/download generated PDF reports"),
]

# Cumulative: operator = viewer's set + its own; admin = operator's set + its own.
_VIEWER_ONLY = ["view_history", "view_analytics", "view_alerts", "view_drift"]
_OPERATOR_ONLY = ["run_prediction", "acknowledge_alert", "view_rca", "view_prescriptive"]
_ADMIN_ONLY = [
    "view_audit", "register_user", "view_security_audit", "view_immutable_log",
    "manage_permissions", "edit_sensor_thresholds", "approve_maintenance_action",
    "retrain_model", "export_reports",
]

_ROLE_PERMISSIONS = {
    "viewer":   _VIEWER_ONLY,
    "operator": _VIEWER_ONLY + _OPERATOR_ONLY,
    "admin":    _VIEWER_ONLY + _OPERATOR_ONLY + _ADMIN_ONLY,
}


def upgrade() -> None:
    permissions_table = op.create_table(
        "permissions",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("description", sa.Text, nullable=False),
    )

    role_permissions_table = op.create_table(
        "role_permissions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("permission_key", sa.String(64), sa.ForeignKey("permissions.key"), nullable=False),
        sa.UniqueConstraint("role", "permission_key", name="uq_role_permissions_role_key"),
    )
    op.create_index("idx_role_permissions_role", "role_permissions", ["role"])

    op.bulk_insert(
        permissions_table,
        [{"key": key, "description": desc} for key, desc in _PERMISSIONS],
    )
    op.bulk_insert(
        role_permissions_table,
        [
            {"role": role, "permission_key": key}
            for role, keys in _ROLE_PERMISSIONS.items()
            for key in keys
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_role_permissions_role", table_name="role_permissions")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
