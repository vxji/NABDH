"""
Tests for §1's database.py refactor onto SQLAlchemy: confirms the SQLite
path (the default, still what these tests run against) behaves identically
to the pre-refactor raw-sqlite3 implementation — same shapes, same
INSERT-OR-IGNORE-on-duplicate semantics, same row/dict access patterns —
plus the new equipment/scope helpers introduced alongside it.
"""
import database

from tests.conftest import auth_headers


def test_get_analytics_returns_expected_shape():
    database.insert_prediction(
        request_id="backend-test-1", prediction=1, confidence=0.8, severity="MEDIUM",
        health_score=50.0, failure_mode="THERMAL_OVERLOAD", ttf_hours=10.0, latency_ms=5.0,
        model_version="test", sensor_data={}, shap_values={}, top_factors=[], anomalies=[],
    )
    result = database.get_analytics(hours=24)
    for key in (
        "total", "failures", "avg_confidence", "avg_latency", "max_latency",
        "avg_health", "high_count", "medium_count", "low_count", "none_count",
        "confidence_trend", "failure_mode_distribution",
    ):
        assert key in result
    assert result["total"] >= 1


def test_insert_prediction_ignores_duplicate_request_id():
    database.insert_prediction(
        request_id="backend-test-dup", prediction=1, confidence=0.5, severity="LOW",
        health_score=70.0, failure_mode="UNKNOWN", ttf_hours=20.0, latency_ms=2.0,
        model_version="test", sensor_data={}, shap_values={}, top_factors=[], anomalies=[],
    )
    database.insert_prediction(  # same request_id — must be silently ignored
        request_id="backend-test-dup", prediction=0, confidence=0.1, severity="NONE",
        health_score=99.0, failure_mode="UNKNOWN", ttf_hours=99.0, latency_ms=1.0,
        model_version="test", sensor_data={}, shap_values={}, top_factors=[], anomalies=[],
    )
    matches = [r for r in database.get_predictions(limit=500) if r["request_id"] == "backend-test-dup"]
    assert len(matches) == 1
    assert matches[0]["severity"] == "LOW"  # first insert wins


def test_equipment_backfilled_to_default_unit():
    equipment = database.get_equipment_list()
    assert any(e["id"] == 1 and e["name"] == "Default Unit" for e in equipment)


def test_user_equipment_scope_add_and_remove():
    database.add_user_equipment_scope("scope-test-user", 1)
    assert 1 in database.get_user_equipment_scope("scope-test-user")
    removed = database.remove_user_equipment_scope("scope-test-user", 1)
    assert removed is True
    assert 1 not in database.get_user_equipment_scope("scope-test-user")


def test_row_wrapper_supports_dict_and_index_access():
    conn = database._connect()
    try:
        row = conn.execute("SELECT id, name FROM equipment WHERE id = ?", (1,)).fetchone()
        assert row["name"] == "Default Unit"
        assert row[0] == 1
        assert dict(row) == {"id": 1, "name": "Default Unit"}
    finally:
        conn.close()


def test_equipment_endpoints(client, admin_token, viewer_token):
    resp = client.get("/equipment", headers=auth_headers(viewer_token))
    assert resp.status_code == 200
    assert any(e["id"] == 1 for e in resp.json()["equipment"])

    resp = client.post(
        "/admin/user-equipment-scope",
        json={"username": "endpoint-scope-user", "equipment_id": 1},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200

    resp = client.post(
        "/admin/user-equipment-scope",
        json={"username": "endpoint-scope-user", "equipment_id": 1},
        headers=auth_headers(viewer_token),
    )
    assert resp.status_code == 403

    resp = client.request(
        "DELETE", "/admin/user-equipment-scope",
        json={"username": "endpoint-scope-user", "equipment_id": 1},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200

    resp = client.request(
        "DELETE", "/admin/user-equipment-scope",
        json={"username": "endpoint-scope-user", "equipment_id": 999},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 404
