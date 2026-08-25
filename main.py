# =============================================================
# main.py — FastAPI Backend
# NABDH AI Maintenance Platform v4
# =============================================================

import math
import time
import uuid
import logging
import datetime as _dt
from typing import Annotated, List, Optional

from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator, ConfigDict
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import config
import ml_logic
import monitoring
import database
import auth
from auth import User, require_viewer, require_operator, require_admin
from services.notifications import proactive_check

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

# ── Rate limiter ──────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

# ── FastAPI app ───────────────────────────────────────────────
app = FastAPI(
    title       = config.APP_NAME,
    description = "Enterprise-grade predictive & prescriptive maintenance API",
    version     = config.APP_VERSION,
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins     = config.ALLOWED_ORIGINS,
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── Auth router ───────────────────────────────────────────────
app.include_router(auth.router)

# ── Startup timestamp ─────────────────────────────────────────
_startup_time = _dt.datetime.now(_dt.timezone.utc)

# ── Proactive maintenance scheduler ────────────────────────────
_scheduler = BackgroundScheduler()


@app.on_event("startup")
def _start_scheduler():
    _scheduler.add_job(
        proactive_check.run_daily_check,
        CronTrigger.from_crontab(config.PROACTIVE_CHECK_CRON),
        id             = "proactive_maintenance_check",
        replace_existing = True,
    )
    _scheduler.start()
    logger.info("Proactive maintenance scheduler started (cron: %s)", config.PROACTIVE_CHECK_CRON)


@app.on_event("shutdown")
def _stop_scheduler():
    _scheduler.shutdown(wait=False)

# ── Audit middleware ──────────────────────────────────────────
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    t_start    = time.perf_counter()
    response   = await call_next(request)
    latency_ms = (time.perf_counter() - t_start) * 1000
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


# =============================================================
# INPUT / OUTPUT SCHEMAS
# =============================================================

class SensorInput(BaseModel):
    """
    10 industrial sensor readings.
    Pass null for any sensor to simulate a missing reading — the imputer handles it.
    Strict mode prevents string injection; range validators reject physically
    implausible values (30% margin beyond SENSOR_META bounds).
    """
    model_config = ConfigDict(strict=True, extra="forbid")

    sensor_1:  Optional[float] = Field(default=None, description="Temperature (°C)")
    sensor_2:  Optional[float] = Field(default=None, description="Pressure (bar)")
    sensor_3:  Optional[float] = Field(default=None, description="Humidity (%)")
    sensor_4:  Optional[float] = Field(default=None, description="RPM")
    sensor_5:  Optional[float] = Field(default=None, description="Voltage (V)")
    sensor_6:  Optional[float] = Field(default=None, description="Current (A)")
    sensor_7:  Optional[float] = Field(default=None, description="Ambient Temp (°C)")
    sensor_8:  Optional[float] = Field(default=None, description="Frequency (Hz)")
    sensor_9:  Optional[float] = Field(default=None, description="Pressure 2 (kPa)")
    sensor_10: Optional[float] = Field(default=None, description="Vibration (mm/s)")

    @model_validator(mode="before")
    @classmethod
    def _coerce_int_to_float(cls, data: dict) -> dict:
        # JSON sends integers for readings like {"sensor_1": 88}.
        # Coerce to float before strict-mode validation.
        if isinstance(data, dict):
            return {
                k: float(v) if isinstance(v, int) else v
                for k, v in data.items()
            }
        return data

    @model_validator(mode="after")
    def _validate_physical_ranges(self) -> "SensorInput":
        for sensor_id, meta in config.SENSOR_META.items():
            val = getattr(self, sensor_id)
            if val is None:
                continue
            if math.isnan(val) or math.isinf(val):
                raise ValueError(f"{sensor_id}: NaN and Infinity are not valid sensor readings.")
            margin = (meta["max"] - meta["min"]) * 0.3
            lo, hi = meta["min"] - margin, meta["max"] + margin
            if not (lo <= val <= hi):
                raise ValueError(
                    f"{sensor_id} value {val}{meta['unit']} is outside the plausible "
                    f"physical range [{meta['min']:.1f}, {meta['max']:.1f}]{meta['unit']}."
                )
        return self


class BatchInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    records: Annotated[
        List[SensorInput],
        Field(min_length=1, max_length=100, description="Between 1 and 100 sensor records"),
    ]


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


class NotificationSettingUpdate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    channel: str  = Field(pattern="^(email|slack|webhook)$")
    enabled: bool = True
    config:  dict = Field(default_factory=dict, description="e.g. {'email_address': '...'} or {'webhook_url': '...'}")


class BatchPredictionResponse(BaseModel):
    results:            list
    total_records:      int
    failures_detected:  int
    processing_time_ms: float


# =============================================================
# HEALTH — public, no auth, no rate limit
# =============================================================

@app.get("/health", tags=["System"])
async def health():
    return {"status": "ok", "version": config.APP_VERSION}


# =============================================================
# SYSTEM STATUS — admin only
# =============================================================

@app.get("/status", tags=["System"])
@limiter.limit(config.RATE_LIMIT)
async def status(
    request:      Request,
    current_user: User = require_admin,
):
    summary = monitoring.get_performance_summary()
    drift   = monitoring.get_drift_report()
    uptime  = int((_dt.datetime.now(_dt.timezone.utc) - _startup_time).total_seconds())
    return {
        "api_status":        "ok",
        "model_version":     ml_logic.MODEL_VERSION,
        "app_version":       config.APP_VERSION,
        "uptime_seconds":    uptime,
        "total_predictions": summary.get("total_predictions", 0),
        "failure_rate":      summary.get("failure_rate", 0.0),
        "avg_latency_ms":    summary.get("avg_latency_ms", 0.0),
        "p95_latency_ms":    summary.get("p95_latency_ms", 0.0),
        "drift_detected":    len(drift.get("drifted_features", [])) > 0,
        "drifted_features":  drift.get("drifted_features", []),
        "db_records":        database.count_predictions(),
        "operator":          current_user.username,
    }


@app.get("/metrics", tags=["System"])
@limiter.limit(config.RATE_LIMIT)
async def metrics(
    request:      Request,
    current_user: User = require_admin,
):
    return monitoring.get_performance_summary()


# =============================================================
# PREDICTION — operator + admin
# =============================================================

@app.post("/predict", response_model=PredictionResponse, tags=["Prediction"])
@limiter.limit("30/minute")  # stricter limit on compute-heavy endpoint
async def predict(
    request:      Request,
    sensor_input: SensorInput,
    current_user: User = require_operator,
) -> PredictionResponse:
    t_start    = time.perf_counter()
    request_id = str(uuid.uuid4())
    input_data = sensor_input.model_dump()

    try:
        result = ml_logic.predict(input_data)
    except AssertionError as exc:
        logger.error("[%s] Pipeline assertion: %s", request_id, exc)
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        logger.error("[%s] Prediction error: %s", request_id, exc)
        raise HTTPException(status_code=500, detail="Prediction pipeline failed.")

    latency_ms = round((time.perf_counter() - t_start) * 1000, 2)

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

    if result["alert"]:
        monitoring.log_alert(
            request_id = request_id,
            severity   = result["severity"],
            confidence = result["confidence"],
            message    = result["alert_message"],
            input_data = input_data,
        )

    if result["prescriptive_actions"]:
        database.insert_prescriptive(
            request_id   = request_id,
            failure_mode = result["failure_mode"],
            actions      = result["prescriptive_actions"],
            priority     = result["maintenance_priority"],
        )

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
@limiter.limit("10/minute")  # batch is expensive — tighter limit
async def predict_batch(
    request:     Request,
    batch_input: BatchInput,
    current_user: User = require_operator,
) -> BatchPredictionResponse:
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
        except Exception as exc:
            logger.error("Batch record error: %s", exc)
            results.append({"error": str(exc)})

    return BatchPredictionResponse(
        results            = results,
        total_records      = len(batch_input.records),
        failures_detected  = failures,
        processing_time_ms = round((time.perf_counter() - t_start) * 1000, 2),
    )


# =============================================================
# HISTORY & ANALYTICS — viewer + above
# =============================================================

@app.get("/history", tags=["Analytics"])
@limiter.limit(config.RATE_LIMIT)
async def history(
    request:      Request,
    limit:        int          = Query(default=100, ge=1, le=500),
    offset:       int          = Query(default=0,   ge=0),
    severity:     Optional[str]= Query(default=None, pattern="^(HIGH|MEDIUM|LOW|NONE)$"),
    current_user: User         = require_viewer,
):
    records = monitoring.get_history(limit=limit, offset=offset, severity=severity)
    return {"records": records, "count": len(records), "limit": limit, "offset": offset}


@app.get("/analytics", tags=["Analytics"])
@limiter.limit(config.RATE_LIMIT)
async def analytics(
    request:      Request,
    hours:        int  = Query(default=24, ge=1, le=168),
    current_user: User = require_viewer,
):
    return monitoring.get_analytics(hours=hours)


@app.get("/drift_report", tags=["Analytics"])
@limiter.limit(config.RATE_LIMIT)
async def drift_report(
    request:      Request,
    current_user: User = require_viewer,
):
    return monitoring.get_drift_report()


@app.get("/drift_history", tags=["Analytics"])
@limiter.limit(config.RATE_LIMIT)
async def drift_history(
    request:      Request,
    limit:        int  = Query(default=20, ge=1, le=100),
    current_user: User = require_viewer,
):
    return {"records": monitoring.get_drift_history(limit=limit)}


# =============================================================
# ROOT CAUSE ANALYSIS — operator + above
# =============================================================

@app.get("/rca/{request_id}", tags=["Explainability"])
@limiter.limit(config.RATE_LIMIT)
async def get_rca(
    request:      Request,
    request_id:   str,
    current_user: User = require_operator,
):
    record = database.get_prediction_by_id(request_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Prediction {request_id} not found.")

    rca = database.get_rca(request_id)
    if rca:
        return rca

    shap_dict    = record.get("shap_values", {})
    sensor_data  = record.get("sensor_data", {})
    failure_mode = record.get("failure_mode", "UNKNOWN")
    confidence   = record.get("confidence", 0.0)
    return ml_logic.root_cause_analysis(shap_dict, sensor_data, confidence, failure_mode)


# =============================================================
# PRESCRIPTIVE MAINTENANCE — operator + above
# =============================================================

@app.get("/prescriptive", tags=["Prescriptive"])
@limiter.limit(config.RATE_LIMIT)
async def prescriptive_history(
    request:      Request,
    limit:        int  = Query(default=20, ge=1, le=100),
    current_user: User = require_operator,
):
    return {"records": monitoring.get_prescriptive_history(limit=limit)}


@app.get("/prescriptive/{request_id}", tags=["Prescriptive"])
@limiter.limit(config.RATE_LIMIT)
async def get_prescriptive(
    request:      Request,
    request_id:   str,
    current_user: User = require_operator,
):
    record = database.get_prediction_by_id(request_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Prediction {request_id} not found.")

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
# ALERTS — viewer (read) / operator (acknowledge)
# =============================================================

@app.get("/alerts", tags=["Alerts"])
@limiter.limit(config.RATE_LIMIT)
async def get_alerts(
    request:      Request,
    limit:        int  = Query(default=50, ge=1, le=200),
    unack_only:   bool = Query(default=False),
    current_user: User = require_viewer,
):
    return {"alerts": monitoring.get_alert_history(limit=limit, unack_only=unack_only)}


@app.post("/alerts/{alert_id}/acknowledge", tags=["Alerts"])
@limiter.limit(config.RATE_LIMIT)
async def ack_alert(
    request:      Request,
    alert_id:     int,
    current_user: User = require_operator,
):
    ok = database.acknowledge_alert(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found.")
    logger.info("Alert #%d acknowledged by '%s'", alert_id, current_user.username)
    return {"status": "acknowledged", "alert_id": alert_id}


# =============================================================
# AUDIT LOG — admin only
# =============================================================

@app.get("/audit", tags=["Audit"])
@limiter.limit(config.RATE_LIMIT)
async def audit_log(
    request:      Request,
    limit:        int  = Query(default=200, ge=1, le=1000),
    current_user: User = require_admin,
):
    return {"records": monitoring.get_audit_log(limit=limit)}


@app.get("/audit/security", tags=["Audit"])
@limiter.limit(config.RATE_LIMIT)
async def security_audit_log(
    request:      Request,
    limit:        int           = Query(default=100, ge=1, le=500),
    offset:       int           = Query(default=0,   ge=0),
    event_type:   Optional[str] = Query(default=None, description="e.g. login_failure, token_reuse, unauthorized"),
    severity:     Optional[str] = Query(default=None, pattern="^(INFO|WARNING|CRITICAL)$"),
    username:     Optional[str] = Query(default=None),
    current_user: User          = require_admin,
):
    records = database.get_security_events(
        limit      = limit,
        offset     = offset,
        event_type = event_type,
        severity   = severity,
        username   = username,
    )
    return {"records": records, "count": len(records), "limit": limit, "offset": offset}


@app.get("/audit/immutable-log", tags=["Audit"])
@limiter.limit(config.RATE_LIMIT)
async def immutable_activity_log(
    request:      Request,
    limit:        int           = Query(default=100, ge=1, le=1000),
    offset:       int           = Query(default=0,   ge=0),
    username:     Optional[str] = Query(default=None, description="Filter by the user who made the change"),
    operation:    Optional[str] = Query(default=None, pattern="^(INSERT|UPDATE|DELETE)$"),
    table_name:   Optional[str] = Query(default=None, description="e.g. predictions, alerts"),
    start_date:   Optional[str] = Query(default=None, description="ISO timestamp lower bound"),
    end_date:     Optional[str] = Query(default=None, description="ISO timestamp upper bound"),
    current_user: User          = require_admin,
):
    """
    Append-only activity trail populated by database triggers (not application
    code) on INSERT/UPDATE/DELETE of predictions/alerts. On PostgreSQL, UPDATE
    and DELETE are REVOKEd on this table at the database level, so even a
    buggy or compromised backend cannot alter or erase these records.
    """
    records = database.get_activity_logs(
        limit      = limit,
        offset     = offset,
        username   = username,
        operation  = operation,
        table_name = table_name,
        start_date = start_date,
        end_date   = end_date,
    )
    return {"records": records, "count": len(records), "limit": limit, "offset": offset}


# =============================================================
# NOTIFICATIONS — any authenticated user manages their own settings
# =============================================================

@app.get("/notifications/settings", tags=["Notifications"])
@limiter.limit(config.RATE_LIMIT)
async def get_notification_settings(
    request:      Request,
    current_user: User = require_viewer,
):
    return {"settings": database.get_notification_settings(current_user.username)}


@app.put("/notifications/settings", tags=["Notifications"])
@limiter.limit(config.RATE_LIMIT)
async def put_notification_settings(
    request:      Request,
    body:         NotificationSettingUpdate,
    current_user: User = require_viewer,
):
    database.upsert_notification_setting(
        username = current_user.username,
        channel  = body.channel,
        enabled  = body.enabled,
        config   = body.config,
    )
    return {"status": "saved", "channel": body.channel, "enabled": body.enabled}


# =============================================================
# PERMISSIONS — extensible authorization, additive to require_role
# =============================================================

@app.get("/permissions", tags=["Permissions"])
@limiter.limit(config.RATE_LIMIT)
async def list_permissions(
    request:      Request,
    current_user: User = Depends(auth.require_permission("manage_permissions")),
):
    return {
        "permissions":      database.get_all_permissions(),
        "role_permissions": database.get_role_permissions(),
    }


@app.post("/permissions/reload", tags=["Permissions"])
@limiter.limit(config.RATE_LIMIT)
async def reload_permissions(
    request:      Request,
    current_user: User = Depends(auth.require_permission("manage_permissions")),
):
    auth.reload_permissions()
    return {"status": "reloaded", "role_permissions": database.get_role_permissions()}
