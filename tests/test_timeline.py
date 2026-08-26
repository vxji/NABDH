"""
Tests for §5: equipment timeline.

The degradation-rate/ETA projection is a pure function (project_next_maintenance)
tested directly against synthetic health_score series (steady decline, flat,
improving). The endpoint tests seed real predictions/prescriptive rows through
database.py so they exercise the full read path, including the "last actual
maintenance" lookup that needed PATCH /prescriptive/{id}/status to populate.
"""
from datetime import datetime, timedelta, timezone

import database
import timeline

from tests.conftest import auth_headers


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def test_bucket_status_thresholds():
    assert timeline.bucket_status(80) == "green"
    assert timeline.bucket_status(60) == "green"
    assert timeline.bucket_status(45) == "yellow"
    assert timeline.bucket_status(30) == "yellow"
    assert timeline.bucket_status(10) == "red"
    assert timeline.bucket_status(None) == "unknown"


def test_project_next_maintenance_steady_decline():
    predictions = [
        {"timestamp": _iso(0), "health_score": 40.0},
        {"timestamp": _iso(1), "health_score": 50.0},
        {"timestamp": _iso(2), "health_score": 60.0},
    ]
    result = timeline.project_next_maintenance(predictions, critical_threshold=20.0)
    assert result is not None
    assert result["eta_hours"] is not None
    assert result["eta_hours"] > 0


def test_project_next_maintenance_flat_health_returns_no_eta():
    predictions = [
        {"timestamp": _iso(0), "health_score": 80.0},
        {"timestamp": _iso(1), "health_score": 80.0},
        {"timestamp": _iso(2), "health_score": 80.0},
    ]
    result = timeline.project_next_maintenance(predictions)
    assert result is not None
    assert result["eta_hours"] is None


def test_project_next_maintenance_improving_health_returns_no_eta():
    predictions = [
        {"timestamp": _iso(0), "health_score": 90.0},
        {"timestamp": _iso(1), "health_score": 70.0},
        {"timestamp": _iso(2), "health_score": 50.0},
    ]
    result = timeline.project_next_maintenance(predictions)
    assert result["eta_hours"] is None


def test_project_next_maintenance_already_critical():
    predictions = [
        {"timestamp": _iso(0), "health_score": 5.0},
        {"timestamp": _iso(1), "health_score": 10.0},
    ]
    result = timeline.project_next_maintenance(predictions, critical_threshold=20.0)
    assert result["eta_hours"] == 0.0


def test_project_next_maintenance_insufficient_history_returns_none():
    assert timeline.project_next_maintenance([{"timestamp": _iso(0), "health_score": 50.0}]) is None
    assert timeline.project_next_maintenance([]) is None


def test_get_equipment_timeline_with_no_predictions_returns_empty_shape():
    result = timeline.get_equipment_timeline(equipment_id=999999)
    assert result["equipment_id"] == 999999
    assert result["current_status"] is None
    assert result["next_predicted_maintenance"] is None
    assert result["last_maintenance"] is None


def test_get_equipment_timeline_end_to_end():
    database.insert_prediction(
        request_id="timeline-test-1", prediction=1, confidence=0.9, severity="HIGH",
        health_score=15.0, failure_mode="THERMAL_OVERLOAD", ttf_hours=1.0, latency_ms=5.0,
        model_version="test", sensor_data={}, shap_values={}, top_factors=[], anomalies=[],
        equipment_id=1,
    )
    database.insert_prescriptive(
        request_id="timeline-test-1", failure_mode="THERMAL_OVERLOAD",
        actions=[{"action": "inspect"}], priority="P1", equipment_id=1,
    )
    database.update_prescriptive_status("timeline-test-1", "RESOLVED", datetime.now(timezone.utc).isoformat())

    result = timeline.get_equipment_timeline(equipment_id=1)
    assert result["current_status"]["status_color"] == "red"
    assert result["last_maintenance"] is not None
    assert result["last_maintenance"]["request_id"] == "timeline-test-1"


def test_prescriptive_status_endpoint_and_timeline_endpoint(client, operator_token, viewer_token):
    resp = client.patch(
        "/prescriptive/nonexistent-request-id/status",
        json={"status": "RESOLVED"},
        headers=auth_headers(operator_token),
    )
    assert resp.status_code == 404

    database.insert_prescriptive(
        request_id="timeline-endpoint-test", failure_mode="MECHANICAL_FAILURE",
        actions=[{"action": "align bearing"}], priority="P1", equipment_id=1,
    )
    resp = client.patch(
        "/prescriptive/timeline-endpoint-test/status",
        json={"status": "RESOLVED"},
        headers=auth_headers(operator_token),
    )
    assert resp.status_code == 200
    assert resp.json()["new_status"] == "RESOLVED"

    resp = client.get("/equipment/1/timeline", headers=auth_headers(viewer_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["equipment_id"] == 1
    assert "current_status" in body and "next_predicted_maintenance" in body


def test_prescriptive_status_endpoint_rejects_invalid_status(client, operator_token):
    resp = client.patch(
        "/prescriptive/whatever/status",
        json={"status": "CANCELLED"},
        headers=auth_headers(operator_token),
    )
    assert resp.status_code == 422
