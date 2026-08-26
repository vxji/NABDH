# =============================================================
# config.py — Centralized Configuration
# NABDH AI Maintenance Platform v4
# =============================================================

import os
import secrets
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── JWT Security ──────────────────────────────────────────────
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not JWT_SECRET_KEY:
    JWT_SECRET_KEY = secrets.token_urlsafe(64)
    logger.warning(
        "JWT_SECRET_KEY not set — using ephemeral key. "
        "All tokens will be invalidated on restart. Set JWT_SECRET_KEY in .env for production."
    )

JWT_ALGORITHM               = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS   = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "7"))

# ── Redis ─────────────────────────────────────────────────────
# Empty string = use in-memory fallback (development only).
# In production, REDIS_URL must be set.
REDIS_URL = os.getenv("REDIS_URL", "")

# ── Rate limiting ─────────────────────────────────────────────
RATE_LIMIT = os.getenv("RATE_LIMIT", "100/minute")

# ── ML ────────────────────────────────────────────────────────
THRESHOLD    = float(os.getenv("THRESHOLD", "0.70"))
TREND_WINDOW = 10
TOP_N_SHAP   = 5

# ── Artifact paths ────────────────────────────────────────────
PIPELINE_PATH       = os.getenv("PIPELINE_PATH",       "pipeline.pkl")
COLUMNS_PATH        = os.getenv("COLUMNS_PATH",        "expected_columns.pkl")
MODEL_VERSION_PATH  = os.getenv("MODEL_VERSION_PATH",  "model_version.json")
REFERENCE_DATA_PATH = os.getenv("REFERENCE_DATA_PATH", "reference_data.csv")

# ── Persistence ───────────────────────────────────────────────
DATABASE_PATH = os.getenv("DATABASE_PATH", "nabdh.db")
# Empty = SQLite (local dev only). Set to a postgresql:// DSN for production —
# enables Row-Level Security (see docs/rls_policies.md).
DATABASE_URL  = os.getenv("DATABASE_URL", "")

# ── Drift detection ───────────────────────────────────────────
DRIFT_WINDOW_SIZE   = int(os.getenv("DRIFT_WINDOW_SIZE",   "500"))
DRIFT_KS_THRESHOLD  = float(os.getenv("DRIFT_KS_THRESHOLD", "0.05"))
MIN_SAMPLES_DRIFT   = int(os.getenv("MIN_SAMPLES_DRIFT",   "50"))
DRIFT_FEATURE_LIMIT = int(os.getenv("DRIFT_FEATURE_LIMIT", "3"))

# ── Alerting ──────────────────────────────────────────────────
ALERT_WEBHOOK_URL    = os.getenv("ALERT_WEBHOOK_URL", "")
ALERT_MIN_CONFIDENCE = float(os.getenv("ALERT_MIN_CONFIDENCE", "0.85"))

# ── CORS ──────────────────────────────────────────────────────
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:8501").split(",")

# ── Sensor physical metadata ──────────────────────────────────
SENSOR_META = {
    "sensor_1":  {"name": "Temperature",  "unit": "°C",   "min":   0.0, "max": 100.0, "critical_high":  85.0, "system": "thermal"},
    "sensor_2":  {"name": "Pressure",     "unit": "bar",  "min":   0.0, "max": 300.0, "critical_high": 250.0, "system": "pressure"},
    "sensor_3":  {"name": "Humidity",     "unit": "%",    "min":   0.0, "max": 100.0, "critical_high":  90.0, "system": "environment"},
    "sensor_4":  {"name": "RPM",          "unit": "rpm",  "min":   0.0, "max": 500.0, "critical_high": 450.0, "system": "mechanical"},
    "sensor_5":  {"name": "Voltage",      "unit": "V",    "min":   0.0, "max": 100.0, "critical_high":  90.0, "system": "electrical"},
    "sensor_6":  {"name": "Current",      "unit": "A",    "min":   0.0, "max": 100.0, "critical_high":  85.0, "system": "electrical"},
    "sensor_7":  {"name": "Ambient Temp", "unit": "°C",   "min": -10.0, "max":  50.0, "critical_high":  45.0, "system": "thermal"},
    "sensor_8":  {"name": "Frequency",    "unit": "Hz",   "min":   0.0, "max": 200.0, "critical_high": 180.0, "system": "electrical"},
    "sensor_9":  {"name": "Pressure 2",   "unit": "kPa",  "min":   0.0, "max": 100.0, "critical_high":  85.0, "system": "pressure"},
    "sensor_10": {"name": "Vibration",    "unit": "mm/s", "min":   0.0, "max": 100.0, "critical_high":  70.0, "system": "mechanical"},
}

# ── Failure mode mapping ───────────────────────────────────────
FAILURE_MODE_SENSORS = {
    "THERMAL_OVERLOAD":    ["sensor_1", "sensor_7"],
    "MECHANICAL_FAILURE":  ["sensor_4", "sensor_10"],
    "ELECTRICAL_FAULT":    ["sensor_5", "sensor_6", "sensor_8"],
    "PRESSURE_ANOMALY":    ["sensor_2", "sensor_9"],
    "ENVIRONMENTAL_STRESS":["sensor_3"],
}

# ── Notifications (v4.2.0) ──────────────────────────────────────
SMTP_HOST         = os.getenv("SMTP_HOST", "")
SMTP_PORT         = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME     = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD     = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_ADDRESS = os.getenv("SMTP_FROM_ADDRESS", "nabdh-alerts@localhost")
SMTP_USE_TLS      = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

SLACK_DEFAULT_WEBHOOK_URL        = os.getenv("SLACK_DEFAULT_WEBHOOK_URL", "")
CUSTOM_NOTIFICATION_WEBHOOK_URL  = os.getenv("CUSTOM_NOTIFICATION_WEBHOOK_URL", "")

# Proactive maintenance scheduling — fires *before* ALERT_MIN_CONFIDENCE is
# crossed, distinct from the existing reactive alert path in monitoring.py.
PROACTIVE_HEALTH_THRESHOLD = float(os.getenv("PROACTIVE_HEALTH_THRESHOLD", "35.0"))
PROACTIVE_CHECK_CRON       = os.getenv("PROACTIVE_CHECK_CRON", "0 6 * * *")  # daily 06:00

# ── App metadata ──────────────────────────────────────────────
APP_VERSION = "4.2.0"
APP_NAME    = "NABDH AI Maintenance Platform"
