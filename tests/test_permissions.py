"""
Tests for §3: extensible permission system.

Verifies the DB-seeded role_permissions mapping is exactly equivalent to the
existing require_role hierarchy (nothing regresses for current endpoints),
and that a brand-new role/permission grant added purely as data — no code
change — is honored immediately after auth.reload_permissions().
"""
import database
from auth import User, UserRole
import auth

from tests.conftest import auth_headers


def _fake_user(role: UserRole) -> User:
    return User(username=f"fake-{role.value}", hashed_password="x", role=role)


def test_default_seed_matches_existing_role_hierarchy():
    auth.reload_permissions()

    viewer   = _fake_user(UserRole.VIEWER)
    operator = _fake_user(UserRole.OPERATOR)
    admin    = _fake_user(UserRole.ADMIN)

    viewer_perms = {"view_history", "view_analytics", "view_alerts", "view_drift"}
    for p in viewer_perms:
        assert auth.has_permission(viewer, p)
        assert auth.has_permission(operator, p)
        assert auth.has_permission(admin, p)

    operator_only = {"run_prediction", "acknowledge_alert", "view_rca", "view_prescriptive"}
    for p in operator_only:
        assert not auth.has_permission(viewer, p)
        assert auth.has_permission(operator, p)
        assert auth.has_permission(admin, p)

    admin_only = {
        "view_audit", "register_user", "view_security_audit", "view_immutable_log",
        "manage_permissions", "edit_sensor_thresholds", "approve_maintenance_action",
        "retrain_model", "export_reports",
    }
    for p in admin_only:
        assert not auth.has_permission(viewer, p)
        assert not auth.has_permission(operator, p)
        assert auth.has_permission(admin, p)


def test_new_permission_grant_is_honored_without_code_changes():
    conn = database._connect()
    try:
        conn.execute(
            "INSERT INTO permissions (key, description) VALUES (?, ?)",
            ("custom_test_permission", "Added at runtime for a test"),
        )
        conn.execute(
            "INSERT INTO role_permissions (role, permission_key) VALUES (?, ?)",
            ("operator", "custom_test_permission"),
        )
        conn.commit()

        auth.reload_permissions()

        operator = _fake_user(UserRole.OPERATOR)
        viewer   = _fake_user(UserRole.VIEWER)
        assert auth.has_permission(operator, "custom_test_permission")
        assert not auth.has_permission(viewer, "custom_test_permission")
    finally:
        conn.execute("DELETE FROM role_permissions WHERE permission_key = ?", ("custom_test_permission",))
        conn.execute("DELETE FROM permissions WHERE key = ?", ("custom_test_permission",))
        conn.commit()
        conn.close()
        auth.reload_permissions()


def test_permissions_endpoint_requires_manage_permissions(client, viewer_token, operator_token, admin_token):
    resp = client.get("/permissions", headers=auth_headers(viewer_token))
    assert resp.status_code == 403

    resp = client.get("/permissions", headers=auth_headers(operator_token))
    assert resp.status_code == 403

    resp = client.get("/permissions", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert "permissions" in body and "role_permissions" in body
    assert "admin" in body["role_permissions"]


def test_permissions_reload_endpoint(client, admin_token):
    resp = client.post("/permissions/reload", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["status"] == "reloaded"
