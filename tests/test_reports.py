"""
Tests for §6: auto-generated PDF prediction reports.

generate_prediction_report() is tested directly against a synthetic
prediction dict (no network/DB needed — a PDF is just bytes). The download
endpoint is tested through a real POST /predict call so it exercises the
actual background-task wiring (report generation + insert_report()).
Email attachment wiring is tested against a mocked aiosmtplib client.
"""
from unittest.mock import AsyncMock, patch

import reports
from tests.conftest import auth_headers

SAMPLE_PREDICTION = {
    "request_id": "report-test-1",
    "prediction": 1,
    "confidence": 0.91,
    "severity": "HIGH",
    "recommendation": "Immediate shutdown and inspection required",
    "time_to_failure_hours": 1.0,
    "health_score": 10.0,
    "failure_mode": "THERMAL_OVERLOAD",
    "top_factors": [{"feature": "sensor_1", "impact": 0.7, "direction": "increases failure risk"}],
    "prescriptive_actions": [{"priority": "P1", "action": "Inspect cooling fan", "est_fix_hours": 2}],
    "maintenance_priority": "P1",
    "rca": {
        "primary_cause": "Temperature reading is the dominant driver",
        "causal_chain": [{"narrative": "Temperature elevated, contributing +0.7"}],
    },
    "alert": True,
    "alert_message": "CRITICAL: Failure imminent.",
    "sensor_anomalies": [],
    "anomaly_warning": "",
    "confidence_trend": "STABLE",
    "trend_alert": False,
    "model_version": "test",
    "latency_ms": 5.0,
    "shap_values": {"sensor_1": 0.7, "sensor_2": -0.1},
}


def test_generate_prediction_report_produces_valid_pdf():
    pdf_bytes = reports.generate_prediction_report(SAMPLE_PREDICTION)
    assert pdf_bytes.startswith(b"%PDF-")
    assert len(pdf_bytes) > 500


def test_generate_prediction_report_handles_missing_optional_fields():
    minimal = {"request_id": "report-test-minimal", "prediction": 0, "confidence": 0.1}
    pdf_bytes = reports.generate_prediction_report(minimal)
    assert pdf_bytes.startswith(b"%PDF-")


def test_save_report_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "REPORTS_DIR", str(tmp_path))
    pdf_bytes = reports.generate_prediction_report(SAMPLE_PREDICTION)
    path = reports.save_report("report-test-save", pdf_bytes)
    with open(path, "rb") as f:
        assert f.read() == pdf_bytes


def test_report_download_404_before_generated(client, operator_token):
    resp = client.get("/predict/nonexistent-prediction-id/report", headers=auth_headers(operator_token))
    assert resp.status_code == 404


def test_report_download_requires_operator(client, viewer_token):
    resp = client.get("/predict/whatever/report", headers=auth_headers(viewer_token))
    assert resp.status_code == 403


def test_predict_generates_downloadable_report(client, operator_token, tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "REPORTS_DIR", str(tmp_path))

    resp = client.post(
        "/predict",
        json={
            "sensor_1": 88.0, "sensor_2": 270.0, "sensor_3": 60.0, "sensor_4": 430.0,
            "sensor_5": 50.0, "sensor_6": 45.0, "sensor_7": 44.0, "sensor_8": 100.0,
            "sensor_9": 82.0, "sensor_10": 72.0,
        },
        headers=auth_headers(operator_token),
    )
    assert resp.status_code == 200
    request_id = resp.json()["request_id"]

    dl = client.get(f"/predict/{request_id}/report", headers=auth_headers(operator_token))
    assert dl.status_code == 200
    assert dl.content.startswith(b"%PDF-")
    assert dl.headers["content-type"] == "application/pdf"


async def test_email_channel_attaches_pdf(monkeypatch):
    from services.notifications.email_channel import EmailChannel
    import config as nabdh_config

    monkeypatch.setattr(nabdh_config, "SMTP_HOST", "smtp.example.com")
    channel = EmailChannel()

    with patch(
        "services.notifications.email_channel.aiosmtplib.send", new=AsyncMock(return_value=None)
    ) as mock_send:
        ok = await channel.send(
            subject="Critical Alert", body="body text",
            channel_config={"email_address": "a@b.com"},
            attachment=b"%PDF-1.4 fake report bytes",
            attachment_filename="report-test-1.pdf",
        )

    assert ok is True
    mock_send.assert_awaited_once()
    sent_message = mock_send.await_args.args[0]
    assert sent_message.is_multipart()
    filenames = [part.get_filename() for part in sent_message.iter_attachments()]
    assert "report-test-1.pdf" in filenames
