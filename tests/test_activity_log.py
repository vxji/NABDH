"""
Tests for the append-only activity_logs feature (migration 0001).

Focus: on SQLite, the DB triggers created by the migration fire correctly and
attribution flows through database.set_session_context(); the
/audit/immutable-log endpoint is admin-only and supports its filters. The
Postgres-only guarantee (REVOKE UPDATE/DELETE) is covered separately by a
@pytest.mark.postgres test that needs a live Postgres instance.
"""
import database

from tests.conftest import auth_headers


def test_insert_on_predictions_is_logged():
    database.set_session_context("admin")
    database.insert_prediction(
        request_id="activity-log-test-1", prediction=1, confidence=0.91, severity="HIGH",
        health_score=12.0, failure_mode="THERMAL_OVERLOAD", ttf_hours=2.0, latency_ms=5.0,
        model_version="test", sensor_data={"sensor_1": 90.0}, shap_values={"sensor_1": 0.5},
        top_factors=[], anomalies=[],
    )
    logs = database.get_activity_logs(table_name="predictions", operation="INSERT", limit=500)
    matching = [l for l in logs if l["new_data"] and l["new_data"].get("request_id") == "activity-log-test-1"]
    assert len(matching) == 1
    assert matching[0]["changed_by"] == "admin"
    assert matching[0]["operation"] == "INSERT"
    assert matching[0]["old_data"] is None
    database.set_session_context(None)


def test_delete_on_alerts_is_logged():
    database.set_session_context("operator")
    database.insert_alert(
        request_id="activity-log-test-2", severity="HIGH", confidence=0.9,
        message="test alert", sensor_data={},
    )
    conn = database._connect()
    row = conn.execute(
        "SELECT id FROM alerts WHERE request_id = ?", ("activity-log-test-2",)
    ).fetchone()
    alert_id = row["id"]
    conn.execute("DELETE FROM alerts WHERE id = ?", (alert_id,))
    conn.commit()
    conn.close()

    logs = database.get_activity_logs(table_name="alerts", operation="DELETE", limit=500)
    matching = [l for l in logs if str(l["row_id"]) == str(alert_id)]
    assert len(matching) == 1
    assert matching[0]["changed_by"] == "operator"
    assert matching[0]["new_data"] is None
    assert matching[0]["old_data"]["request_id"] == "activity-log-test-2"
    database.set_session_context(None)


def test_immutable_log_endpoint_requires_admin(client, viewer_token, operator_token, admin_token):
    resp = client.get("/audit/immutable-log", headers=auth_headers(viewer_token))
    assert resp.status_code == 403

    resp = client.get("/audit/immutable-log", headers=auth_headers(operator_token))
    assert resp.status_code == 403

    resp = client.get("/audit/immutable-log", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert "records" in body and "count" in body


def test_immutable_log_endpoint_filters_by_username(client, admin_token):
    database.set_session_context("admin")
    database.insert_prediction(
        request_id="activity-log-test-3", prediction=0, confidence=0.1, severity="NONE",
        health_score=95.0, failure_mode="UNKNOWN", ttf_hours=50.0, latency_ms=3.0,
        model_version="test", sensor_data={}, shap_values={}, top_factors=[], anomalies=[],
    )
    database.set_session_context(None)

    resp = client.get(
        "/audit/immutable-log",
        params={"username": "admin", "table_name": "predictions", "operation": "INSERT"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    records = resp.json()["records"]
    assert all(r["changed_by"] == "admin" for r in records)
    assert any(r["new_data"] and r["new_data"].get("request_id") == "activity-log-test-3" for r in records)


def test_activity_log_endpoint_rejects_bad_operation_filter(client, admin_token):
    resp = client.get(
        "/audit/immutable-log",
        params={"operation": "TRUNCATE"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 422
