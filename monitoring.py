# =============================================================
# monitoring.py — Monitoring, Drift Detection, Analytics
# NABDH Predictive Maintenance System v4
# =============================================================

import json
import logging
import os
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import ks_2samp

import config
import database

logger = logging.getLogger(__name__)

# ── Bootstrap DB on module load ───────────────────────────────
database.init_db()

# ── In-memory rolling window (for drift — fast access) ───────
_prediction_store: deque = deque(maxlen=config.DRIFT_WINDOW_SIZE)
_last_drift_report: dict = {}
_lock = threading.Lock()

# ── Reference distribution ────────────────────────────────────
_reference_data: Optional[pd.DataFrame] = None
try:
    _reference_data = pd.read_csv(config.REFERENCE_DATA_PATH)
    logger.info("Reference data loaded: %d rows from %s", len(_reference_data), config.REFERENCE_DATA_PATH)
except FileNotFoundError:
    logger.warning(
        "reference_data.csv not found — drift detection will use "
        "rolling window self-comparison as baseline"
    )

# =============================================================
# PUBLIC — PREDICTION LOGGING
# =============================================================

def log_prediction(
    request_id:    str,
    input_data:    dict,
    prediction:    int,
    confidence:    float,
    severity:      str,
    health_score:  float,
    failure_mode:  str,
    ttf_hours:     float,
    latency_ms:    float,
    model_version: str,
    shap_values:   dict,
    top_factors:   list,
    anomalies:     list,
) -> None:
    """
    Persists prediction to SQLite and updates in-memory rolling store.
    Triggers drift check every MIN_SAMPLES_DRIFT predictions.
    """
    # Persist to DB
    database.insert_prediction(
        request_id    = request_id,
        prediction    = prediction,
        confidence    = confidence,
        severity      = severity,
        health_score  = health_score,
        failure_mode  = failure_mode,
        ttf_hours     = ttf_hours,
        latency_ms    = latency_ms,
        model_version = model_version,
        sensor_data   = {k: v for k, v in input_data.items() if v is not None},
        shap_values   = shap_values,
        top_factors   = top_factors,
        anomalies     = anomalies,
    )

    # Update rolling store
    record = {
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "prediction": prediction,
        "confidence": confidence,
        "latency_ms": latency_ms,
        **{k: v for k, v in input_data.items() if v is not None},
    }
    with _lock:
        _prediction_store.append(record)
        n = len(_prediction_store)

    logger.info("[%s] pred=%d conf=%.3f sev=%s latency=%.1fms",
                request_id, prediction, confidence, severity, latency_ms)

    if n % config.MIN_SAMPLES_DRIFT == 0:
        _check_drift()


def log_alert(
    request_id: str,
    severity:   str,
    confidence: float,
    message:    str,
    input_data: dict,
) -> None:
    database.insert_alert(
        request_id  = request_id,
        severity    = severity,
        confidence  = confidence,
        message     = message,
        sensor_data = {k: v for k, v in input_data.items() if v is not None},
    )
    logger.warning("[ALERT][%s] %s conf=%.3f", request_id, message, confidence)

    # Fire webhook if configured
    if config.ALERT_WEBHOOK_URL:
        _fire_webhook(request_id, severity, confidence, message, input_data)


# =============================================================
# PUBLIC — QUERY FUNCTIONS
# =============================================================

def get_performance_summary() -> dict:
    with _lock:
        records = list(_prediction_store)
    if not records:
        return {"message": "No predictions logged yet"}

    confidences = [r["confidence"] for r in records]
    latencies   = [r["latency_ms"] for r in records]
    predictions = [r["prediction"] for r in records]

    return {
        "total_predictions":  len(records),
        "failure_rate":       round(sum(predictions) / len(predictions), 4),
        "avg_confidence":     round(float(np.mean(confidences)), 4),
        "avg_latency_ms":     round(float(np.mean(latencies)), 2),
        "max_latency_ms":     round(float(np.max(latencies)), 2),
        "p95_latency_ms":     round(float(np.percentile(latencies, 95)), 2),
        "latency_violations": sum(1 for l in latencies if l > 50),
    }


def get_drift_report() -> dict:
    return _last_drift_report if _last_drift_report else {"message": "No drift check has run yet"}


def get_history(limit: int = 100, offset: int = 0, severity: Optional[str] = None) -> list[dict]:
    return database.get_predictions(limit=limit, offset=offset, severity=severity)


def get_analytics(hours: int = 24) -> dict:
    return database.get_analytics(hours=hours)


def get_alert_history(limit: int = 50, unack_only: bool = False) -> list[dict]:
    return database.get_alerts(limit=limit, unack_only=unack_only)


def get_prescriptive_history(limit: int = 20) -> list[dict]:
    return database.get_prescriptive(limit=limit)


def get_drift_history(limit: int = 20) -> list[dict]:
    return database.get_drift_history(limit=limit)


def get_audit_log(limit: int = 200) -> list[dict]:
    return database.get_audit_log(limit=limit)


# =============================================================
# INTERNAL — DRIFT DETECTION
# =============================================================

def _check_drift() -> None:
    global _last_drift_report
    with _lock:
        records = list(_prediction_store)

    if len(records) < config.MIN_SAMPLES_DRIFT:
        return

    recent_df = pd.DataFrame(records)

    if _reference_data is not None:
        report = _ks_test_columns(recent_df, _reference_data)
    else:
        half  = len(records) // 2
        early = pd.DataFrame(records[:half])
        late  = pd.DataFrame(records[half:])
        report = _ks_test_columns(late, early)

    _last_drift_report = report

    # Persist drift check result
    database.insert_drift_check(
        total_features_checked = report["total_features_checked"],
        drifted_features       = report["drifted_features"],
        drift_details          = report["drift_details"],
        retrain_triggered      = report.get("retrain_triggered", False),
    )


def _ks_test_columns(current: pd.DataFrame, reference: pd.DataFrame) -> dict:
    shared_cols = [
        c for c in current.columns
        if c in reference.columns
        and pd.api.types.is_numeric_dtype(current[c])
        and c not in ("prediction", "latency_ms", "timestamp")
    ]

    drift_detected = []
    checked_at     = datetime.now(timezone.utc).isoformat()

    for col in shared_cols:
        curr_vals = current[col].dropna().values
        ref_vals  = reference[col].dropna().values
        if len(curr_vals) < 10 or len(ref_vals) < 10:
            continue
        stat, p_value = ks_2samp(curr_vals, ref_vals)
        if p_value < config.DRIFT_KS_THRESHOLD:
            drift_detected.append({
                "feature": col,
                "ks_stat": round(stat, 4),
                "p_value": round(p_value, 6),
            })

    drifted_features = [d["feature"] for d in drift_detected]
    retrain_needed   = len(drift_detected) >= config.DRIFT_FEATURE_LIMIT

    if drift_detected:
        logger.warning("DATA DRIFT in %d feature(s): %s", len(drift_detected), drifted_features)
        if retrain_needed:
            _trigger_retrain_flag(drifted_features)
    else:
        logger.info("Drift check passed — no significant drift")

    return {
        "checked_at":             checked_at,
        "total_features_checked": len(shared_cols),
        "drifted_features":       drifted_features,
        "drift_details":          drift_detected,
        "retrain_triggered":      retrain_needed,
    }


def _trigger_retrain_flag(drifted_features: list) -> None:
    flag_path = "retrain_needed.flag"
    with open(flag_path, "w") as f:
        json.dump({
            "triggered_at":     datetime.now(timezone.utc).isoformat(),
            "drifted_features": drifted_features,
            "action_required":  "Retrain model on fresh data",
        }, f, indent=2)
    logger.warning("RETRAIN FLAG written — drifted features: %s", drifted_features)


# =============================================================
# INTERNAL — ALERTING WEBHOOK
# =============================================================

def _fire_webhook(
    request_id: str,
    severity:   str,
    confidence: float,
    message:    str,
    sensor_data: dict,
) -> None:
    """Fire alert to configured webhook URL (Slack/Teams/custom HTTP)."""
    try:
        import requests as _req
        payload = {
            "text":        f"[NABDH ALERT] {severity} — {message}",
            "request_id":  request_id,
            "confidence":  confidence,
            "sensor_data": {k: v for k, v in sensor_data.items() if v is not None},
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        }
        resp = _req.post(config.ALERT_WEBHOOK_URL, json=payload, timeout=5)
        logger.info("Alert webhook fired: status %d", resp.status_code)
    except Exception as exc:
        logger.warning("Alert webhook failed: %s", exc)
