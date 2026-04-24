# =============================================================
# config.py — Centralized Configuration
# NABDH Predictive Maintenance System v4
# =============================================================

import os

# ── API ───────────────────────────────────────────────────────
API_KEY         = os.getenv("API_KEY", "nabdh-prod-key-2024")
API_KEY_NAME    = "X-API-Key"
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# ── ML ────────────────────────────────────────────────────────
THRESHOLD         = float(os.getenv("THRESHOLD", "0.70"))
TREND_WINDOW      = 10        # rolling confidence window size
TOP_N_SHAP        = 5         # top SHAP features to surface

# ── Artifact paths ───────────────────────────────────────────
PIPELINE_PATH      = os.getenv("PIPELINE_PATH",      "pipeline.pkl")
COLUMNS_PATH       = os.getenv("COLUMNS_PATH",       "expected_columns.pkl")
MODEL_VERSION_PATH = os.getenv("MODEL_VERSION_PATH", "model_version.json")
REFERENCE_DATA_PATH= os.getenv("REFERENCE_DATA_PATH","reference_data.csv")

# ── Persistence ───────────────────────────────────────────────
DATABASE_PATH = os.getenv("DATABASE_PATH", "nabdh.db")

# ── Drift detection ───────────────────────────────────────────
DRIFT_WINDOW_SIZE   = int(os.getenv("DRIFT_WINDOW_SIZE",  "500"))
DRIFT_KS_THRESHOLD  = float(os.getenv("DRIFT_KS_THRESHOLD","0.05"))
MIN_SAMPLES_DRIFT   = int(os.getenv("MIN_SAMPLES_DRIFT",  "50"))
DRIFT_FEATURE_LIMIT = int(os.getenv("DRIFT_FEATURE_LIMIT","3"))

# ── Alerting ─────────────────────────────────────────────────
ALERT_WEBHOOK_URL     = os.getenv("ALERT_WEBHOOK_URL", "")   # Slack / Teams / custom
ALERT_MIN_CONFIDENCE  = float(os.getenv("ALERT_MIN_CONFIDENCE", "0.85"))

# ── Sensor physical metadata ──────────────────────────────────
# Used by prescriptive engine and RCA
SENSOR_META = {
    "sensor_1":  {"name": "Temperature",   "unit": "°C",   "min":  0.0, "max": 100.0, "critical_high": 85.0, "system": "thermal"},
    "sensor_2":  {"name": "Pressure",      "unit": "bar",  "min":  0.0, "max": 300.0, "critical_high": 250.0,"system": "pressure"},
    "sensor_3":  {"name": "Humidity",      "unit": "%",    "min":  0.0, "max": 100.0, "critical_high": 90.0, "system": "environment"},
    "sensor_4":  {"name": "RPM",           "unit": "rpm",  "min":  0.0, "max": 500.0, "critical_high": 450.0,"system": "mechanical"},
    "sensor_5":  {"name": "Voltage",       "unit": "V",    "min":  0.0, "max": 100.0, "critical_high": 90.0, "system": "electrical"},
    "sensor_6":  {"name": "Current",       "unit": "A",    "min":  0.0, "max": 100.0, "critical_high": 85.0, "system": "electrical"},
    "sensor_7":  {"name": "Ambient Temp",  "unit": "°C",   "min":-10.0, "max":  50.0, "critical_high": 45.0, "system": "thermal"},
    "sensor_8":  {"name": "Frequency",     "unit": "Hz",   "min":  0.0, "max": 200.0, "critical_high": 180.0,"system": "electrical"},
    "sensor_9":  {"name": "Pressure 2",    "unit": "kPa",  "min":  0.0, "max": 100.0, "critical_high": 85.0, "system": "pressure"},
    "sensor_10": {"name": "Vibration",     "unit": "mm/s", "min":  0.0, "max": 100.0, "critical_high": 70.0, "system": "mechanical"},
}

# ── Failure mode mapping ──────────────────────────────────────
FAILURE_MODE_SENSORS = {
    "THERMAL_OVERLOAD":    ["sensor_1", "sensor_7"],
    "MECHANICAL_FAILURE":  ["sensor_4", "sensor_10"],
    "ELECTRICAL_FAULT":    ["sensor_5", "sensor_6", "sensor_8"],
    "PRESSURE_ANOMALY":    ["sensor_2", "sensor_9"],
    "ENVIRONMENTAL_STRESS":["sensor_3"],
}

# ── App metadata ─────────────────────────────────────────────
APP_VERSION = "4.0.0"
APP_NAME    = "NABDH AI Maintenance Platform"
