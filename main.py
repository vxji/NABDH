# =============================================================
# main.py — FastAPI Backend
# NABDH Predictive Maintenance System v4
# =============================================================

import time
import uuid
import logging
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Security, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

import config
import ml_logic
import monitoring
import database

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── FastAPI app ───────────────────────────────────────────────
app = FastAPI(
    title       = config.APP_NAME,
    description = "Enterprise-grade predictive & prescriptive maintenance API",
    version     = config.APP_VERSION,
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

# ── CORS ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins     = config.ALLOWED_ORIGINS,
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Audit middleware ──────────────────────────────────────────
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    t_start    = time.perf_counter()
    response   = await call_next(request)
    latency_ms = (time.perf_counter() - t_start) * 1000

    # Non-blocking audit write (fire-and-forget)
    try:
        database.insert_audit(
            method     = request.method,
            path       = request.url.path,
            status     = response.status_code,
            latency_ms = round(latency_ms, 2),
            user_agent = request.headers.get("user-agent"),
            ip_address = request.client.host if request.client else None,
        )
    except Exception:
        pass

    return response

# ── API key auth ──────────────────────────────────────────────
_api_key_header = APIKeyHeader(name=config.API_KEY_NAME, auto_error=True)

def verify_api_key(key: str = Security(_api_key_header)) -> str:
    if key != config.API_KEY:
        logger.warning("Rejected request with invalid API key")
        raise HTTPException(status_code=403, detail="Invalid API key")
    return key

# ── Startup timestamp ─────────────────────────────────────────
import datetime as _dt
_startup_time = _dt.datetime.now(_dt.timezone.utc)

# =============================================================
# INPUT / OUTPUT SCHEMAS
# =============================================================

class SensorInput(BaseModel):
    sensor_1:  Optional[float] = Field(default=None)
    sensor_2:  Optional[float] = Field(default=None)
    sensor_3:  Optional[float] = Field(default=None)
    sensor_4:  Optional[float] = Field(default=None)
    sensor_5:  Optional[float] = Field(default=None)
    sensor_6:  Optional[float] = Field(default=None)
    sensor_7:  Optional[float] = Field(default=None)
    sensor_8:  Optional[float] = Field(default=None)
    sensor_9:  Optional[float] = Field(default=None)
    sensor_10: Optional[float] = Field(default=None)


class BatchInput(BaseModel):
    records: List[SensorInput] = Field(..., description="Up to 100 sensor records")


class PredictionResponse(BaseModel):
    request_id:              str
    prediction:              int
    confidence:              float
    severity:                str
    recommendation:          str
    time_to_failure_hours:   float
    health_score:            float
    failure_mode:            str
    top_factors:             list
    prescriptive_actions:    list
    maintenance_priority:    str
    rca:                     dict
    alert:                   bool
    alert_message:           str
    sensor_anomalies:        list
    anomaly_warning:         str
    confidence_trend:        str
    trend_alert:             bool
    model_version:           str
    latency_ms:              float
    shap_values:             dict


class BatchPredictionResponse(BaseModel):
    results:            list
    total_records:      int
    failures_detected:  int
    processing_time_ms: float


# =============================================================
# HEALTH
# =============================================================

@app.get("/health", tags=["System"])
async def health():
    """Health check — used by Docker HEALTHCHECK and load balancers."""
    return {"status": "ok", "version": config.APP_VERSION}


# =============================================================
# SYSTEM STATUS
# =============================================================

@app.get("/status", tags=["System"])
async def status(api_key: str = Security(verify_api_key)):
    """Full system health, model info, drift status, and uptime."""
    summary = monitoring.get_performance_summary()
    drift   = monitoring.get_drift_report()
    uptime  = int((_dt.datetime.now(_dt.timezone.utc) - _startup_time).total_seconds())
    return {
        "api_status":       "ok",
        "model_version":    ml_logic.MODEL_VERSION,
        "app_version":      config.APP_VERSION,
        "uptime_seconds":   uptime,
        "total_predictions": summary.get("total_predictions", 0),
        "failure_rate":      summary.get("failure_rate", 0.0),
        "avg_latency_ms":    summary.get("avg_latency_ms", 0.0),
        "p95_latency_ms":    summary.get("p95_latency_ms", 0.0),
        "drift_detected":    len(drift.get("drifted_features", [])) > 0,
        "drifted_features":  drift.get("drifted_features", []),
        "db_records":        database.count_predictions(),
    }


@app.get("/metrics", tags=["System"])
async def metrics(api_key: str = Security(verify_api_key)):
    """Rolling-window performance metrics."""
    return monitoring.get_performance_summary()


# =============================================================
# PREDICTION
# =============================================================

@app.post("/predict", response_model=PredictionResponse, tags=["Prediction"])
async def predict(
    sensor_input: SensorInput,
    api_key: str = Security(verify_api_key),
) -> PredictionResponse:
    """
    Single-record prediction.
    Returns enriched decision report: severity, RCA, prescriptive actions, health score.
    """
    t_start    = time.perf_counter()
    request_id = str(uuid.uuid4())
    input_data = sensor_input.model_dump()

    try:
        result = ml_logic.predict(input_data)
    except AssertionError as e:
        logger.error("[%s] Pipeline assertion: %s", request_id, e)
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error("[%s] Prediction error: %s", request_id, e)
        raise HTTPException(status_code=500, detail="Prediction pipeline failed")

    latency_ms = round((time.perf_counter() - t_start) * 1000, 2)

    # Persist prediction
    monitoring.log_prediction(
        request_id    = request_id,
        input_data    = input_data,
        prediction    = result["prediction"],
        confidence    = result["confidence"],
        severity      = result["severity"],
        health_score  = result["health_score"],
        failure_mode  = result["failure_mode"],
        ttf_hours     = result["time_to_failure_hours"],
        latency_ms    = latency_ms,
        model_version = result["model_version"],
        shap_values   = result["shap_values"],
        top_factors   = result["top_factors"],
        anomalies     = result["sensor_anomalies"],
    )

    # Persist alert if triggered
    if result["alert"]:
        monitoring.log_alert(
            request_id  = request_id,
            severity    = result["severity"],
            confidence  = result["confidence"],
            message     = result["alert_message"],
            input_data  = input_data,
        )

    # Persist prescriptive actions
    if result["prescriptive_actions"]:
        database.insert_prescriptive(
            request_id   = request_id,
            failure_mode = result["failure_mode"],
            actions      = result["prescriptive_actions"],
            priority     = result["maintenance_priority"],
        )

    # Persist RCA
    if result["rca"] and result["rca"].get("causal_chain"):
        database.insert_rca(
            request_id    = request_id,
            primary_cause = result["rca"]["primary_cause"],
            causal_chain  = result["rca"]["causal_chain"],
            failure_mode  = result["failure_mode"],
            confidence    = result["confidence"],
        )

    if latency_ms > 100:
        logger.warning("[%s] High latency: %.1fms", request_id, latency_ms)

    return PredictionResponse(
        request_id            = request_id,
        prediction            = result["prediction"],
        confidence            = result["confidence"],
        severity              = result["severity"],
        recommendation        = result["recommendation"],
        time_to_failure_hours = result["time_to_failure_hours"],
        health_score          = result["health_score"],
        failure_mode          = result["failure_mode"],
        top_factors           = result["top_factors"],
        prescriptive_actions  = result["prescriptive_actions"],
        maintenance_priority  = result["maintenance_priority"],
        rca                   = result["rca"],
        alert                 = result["alert"],
        alert_message         = result["alert_message"],
        sensor_anomalies      = result["sensor_anomalies"],
        anomaly_warning       = result["anomaly_warning"],
        confidence_trend      = result["confidence_trend"],
        trend_alert           = result["trend_alert"],
        model_version         = result["model_version"],
        latency_ms            = latency_ms,
        shap_values           = result["shap_values"],
    )


@app.post("/predict_batch", response_model=BatchPredictionResponse, tags=["Prediction"])
async def predict_batch(
    batch_input: BatchInput,
    api_key: str = Security(verify_api_key),
) -> BatchPredictionResponse:
    """Batch prediction — up to 100 records per call."""
    if len(batch_input.records) > 100:
        raise HTTPException(status_code=422, detail="Batch size exceeds maximum of 100")

    t_start  = time.perf_counter()
    results  = []
    failures = 0

    for record in batch_input.records:
        input_data = record.model_dump()
        try:
            r = ml_logic.predict(input_data)
            results.append(r)
            if r["prediction"] == 1:
                failures += 1
        except Exception as e:
            logger.error("Batch record error: %s", e)
            results.append({"error": str(e)})

    return BatchPredictionResponse(
        results            = results,
        total_records      = len(batch_input.records),
        failures_detected  = failures,
        processing_time_ms = round((time.perf_counter() - t_start) * 1000, 2),
    )


# =============================================================
# HISTORY & ANALYTICS
# =============================================================

@app.get("/history", tags=["Analytics"])
async def history(
    limit:    int = Query(default=100, ge=1, le=500),
    offset:   int = Query(default=0,   ge=0),
    severity: Optional[str] = Query(default=None, pattern="^(HIGH|MEDIUM|LOW|NONE)$"),
    api_key:  str = Security(verify_api_key),
):
    """
    Paginated prediction history from persistent storage.
    Filter by severity: HIGH | MEDIUM | LOW | NONE.
    """
    records = monitoring.get_history(limit=limit, offset=offset, severity=severity)
    return {
        "records": records,
        "count":   len(records),
        "limit":   limit,
        "offset":  offset,
    }


@app.get("/analytics", tags=["Analytics"])
async def analytics(
    hours:   int = Query(default=24, ge=1, le=168),
    api_key: str = Security(verify_api_key),
):
    """Aggregated analytics for the last N hours (max 7 days)."""
    return monitoring.get_analytics(hours=hours)


@app.get("/drift_report", tags=["Analytics"])
async def drift_report(api_key: str = Security(verify_api_key)):
    """Latest feature-level drift detection report."""
    return monitoring.get_drift_report()


@app.get("/drift_history", tags=["Analytics"])
async def drift_history(
    limit:   int = Query(default=20, ge=1, le=100),
    api_key: str = Security(verify_api_key),
):
    """Historical drift check results."""
    return {"records": monitoring.get_drift_history(limit=limit)}


# =============================================================
# ROOT CAUSE ANALYSIS
# =============================================================

@app.get("/rca/{request_id}", tags=["Explainability"])
async def get_rca(
    request_id: str,
    api_key: str = Security(verify_api_key),
):
    """
    Root Cause Analysis for a specific prediction.
    Returns causal chain, failure mode description, and inspection recommendation.
    """
    record = database.get_prediction_by_id(request_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Prediction {request_id} not found")

    rca = database.get_rca(request_id)
    if rca:
        return rca

    # Recompute on-the-fly if not stored (backward compat)
    shap_dict   = record.get("shap_values", {})
    sensor_data = record.get("sensor_data", {})
    failure_mode= record.get("failure_mode", "UNKNOWN")
    confidence  = record.get("confidence", 0.0)
    return ml_logic.root_cause_analysis(shap_dict, sensor_data, confidence, failure_mode)


# =============================================================
# PRESCRIPTIVE MAINTENANCE
# =============================================================

@app.get("/prescriptive", tags=["Prescriptive"])
async def prescriptive_history(
    limit:   int = Query(default=20, ge=1, le=100),
    status:  Optional[str] = Query(default=None),
    api_key: str = Security(verify_api_key),
):
    """History of prescriptive maintenance recommendations."""
    return {"records": monitoring.get_prescriptive_history(limit=limit)}


@app.get("/prescriptive/{request_id}", tags=["Prescriptive"])
async def get_prescriptive(
    request_id: str,
    api_key: str = Security(verify_api_key),
):
    """
    Prescriptive maintenance actions for a specific prediction.
    Recomputes from stored sensor data if needed.
    """
    record = database.get_prediction_by_id(request_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Prediction {request_id} not found")

    sensor_data  = record.get("sensor_data", {})
    failure_mode = record.get("failure_mode", "UNKNOWN")
    confidence   = record.get("confidence", 0.0)
    actions      = ml_logic.run_prescriptive_engine(sensor_data, failure_mode, confidence)
    return {
        "request_id":   request_id,
        "failure_mode": failure_mode,
        "confidence":   confidence,
        "actions":      actions,
        "top_priority": ml_logic.get_top_priority(actions),
    }


# =============================================================
# ALERTS
# =============================================================

@app.get("/alerts", tags=["Alerts"])
async def get_alerts(
    limit:      int  = Query(default=50, ge=1, le=200),
    unack_only: bool = Query(default=False),
    api_key:    str  = Security(verify_api_key),
):
    """Alert history. Set unack_only=true to see only unacknowledged alerts."""
    return {"alerts": monitoring.get_alert_history(limit=limit, unack_only=unack_only)}


@app.post("/alerts/{alert_id}/acknowledge", tags=["Alerts"])
async def ack_alert(
    alert_id: int,
    api_key:  str = Security(verify_api_key),
):
    """Acknowledge an alert by ID."""
    ok = database.acknowledge_alert(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return {"status": "acknowledged", "alert_id": alert_id}


# =============================================================
# AUDIT LOG
# =============================================================

@app.get("/audit", tags=["Audit"])
async def audit_log(
    limit:  int = Query(default=200, ge=1, le=1000),
    api_key: str = Security(verify_api_key),
):
    """Full API audit log — every request recorded."""
    return {"records": monitoring.get_audit_log(limit=limit)}
