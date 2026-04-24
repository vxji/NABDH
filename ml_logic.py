# =============================================================
# ml_logic.py — ML Pipeline, Prediction Engine, Prescriptive AI
# NABDH Predictive Maintenance System v4
# =============================================================

import json
import logging

import joblib
import numpy as np
import pandas as pd
import shap
from collections import deque
from sklearn.pipeline import Pipeline

import config

logger = logging.getLogger(__name__)

# ── Load artifacts once at startup ───────────────────────────

pipeline: Pipeline          = joblib.load(config.PIPELINE_PATH)
expected_columns: list[str] = joblib.load(config.COLUMNS_PATH)

with open(config.MODEL_VERSION_PATH, "r") as _f:
    _model_meta = json.load(_f)
MODEL_VERSION: str = _model_meta.get("version", "unknown")

# ── Cache SHAP explainer (expensive to create per request) ───

_classifier     = pipeline.named_steps["classifier"]
_shap_explainer = shap.TreeExplainer(_classifier)

# ── Rolling confidence window ─────────────────────────────────

_confidence_history: deque = deque(maxlen=config.TREND_WINDOW)

# ── IQR anomaly bounds (computed once from imputer medians) ──

_iqr_bounds: dict = {}

def _build_iqr_bounds() -> None:
    imputer = pipeline.named_steps.get("imputer")
    if imputer is None or not hasattr(imputer, "statistics_"):
        return
    for i, col in enumerate(expected_columns):
        median = imputer.statistics_[i]
        if median == 0:
            _iqr_bounds[col] = (0.0, 1.0)
        else:
            _iqr_bounds[col] = (median * 0.1, median * 2.5)

_build_iqr_bounds()

# =============================================================
# SECTION 1 — PREPROCESSING HELPERS
# =============================================================

def _get_preprocessor() -> Pipeline:
    steps = list(pipeline.named_steps.items())
    return Pipeline(steps[:-1])


def _get_selected_feature_names() -> list[str]:
    selector = pipeline.named_steps.get("feature_selector")
    if selector is None:
        return expected_columns
    support = selector.get_support(indices=True)
    return [expected_columns[i] for i in support]


def _compute_shap(input_transformed: np.ndarray) -> dict:
    shap_values = _shap_explainer.shap_values(input_transformed)
    if isinstance(shap_values, list):
        shap_array = np.array(shap_values[1]).flatten()
    else:
        sv = np.array(shap_values)
        shap_array = sv[0, :, 1].flatten() if sv.ndim == 3 else sv.flatten()

    selected = _get_selected_feature_names()
    min_len  = min(len(shap_array), len(selected))
    return dict(zip(selected[:min_len], shap_array[:min_len].tolist()))


# =============================================================
# SECTION 2 — DECISION ENGINE
# =============================================================

def _build_decision(confidence: float) -> dict:
    if confidence > 0.85:
        return {"severity": "HIGH",   "recommendation": "Immediate shutdown and inspection required"}
    elif confidence > 0.70:
        return {"severity": "MEDIUM", "recommendation": "Schedule maintenance within 24 hours"}
    elif confidence > 0.50:
        return {"severity": "LOW",    "recommendation": "Monitor closely — increase sensor polling frequency"}
    return {"severity": "NONE",       "recommendation": "Normal operation — no action required"}


def _estimate_ttf(confidence: float, shap_dict: dict) -> float:
    """Time-to-failure estimate in hours. Heuristic model."""
    base_ttf = (1.0 - confidence) * 72.0
    if shap_dict:
        top_impact = max(abs(v) for v in shap_dict.values())
        if top_impact > 0.5:
            base_ttf *= 0.4
        elif top_impact > 0.3:
            base_ttf *= 0.65
    return round(max(base_ttf, 0.5), 1)


def _simplify_shap(shap_dict: dict, top_n: int = None) -> list:
    n = top_n or config.TOP_N_SHAP
    return [
        {
            "feature":   k,
            "impact":    round(v, 4),
            "direction": "increases failure risk" if v > 0 else "reduces failure risk",
        }
        for k, v in sorted(shap_dict.items(), key=lambda x: abs(x[1]), reverse=True)[:n]
    ]


def _build_alert(confidence: float) -> dict:
    if confidence > config.ALERT_MIN_CONFIDENCE:
        return {"alert": True, "alert_message": "CRITICAL: Failure imminent. Immediate action required."}
    return {"alert": False, "alert_message": ""}


def _detect_sensor_anomalies(data: dict) -> tuple[list, str]:
    anomalies = []
    for sensor, value in data.items():
        if value is None or sensor not in _iqr_bounds:
            continue
        lo, hi = _iqr_bounds[sensor]
        if not (lo <= value <= hi):
            anomalies.append(sensor)
    warning = (
        f"{len(anomalies)} sensor(s) showing abnormal readings: {', '.join(anomalies)}"
        if anomalies else ""
    )
    return anomalies, warning


def _compute_confidence_trend(current_confidence: float) -> tuple[str, bool]:
    _confidence_history.append(current_confidence)
    if len(_confidence_history) < 3:
        return "STABLE", False
    history    = list(_confidence_history)
    delta      = history[-1] - history[-3]
    trend_alert = abs(delta) > 0.3
    trend = "RISING" if delta > 0.05 else "FALLING" if delta < -0.05 else "STABLE"
    return trend, trend_alert


# =============================================================
# SECTION 3 — HEALTH SCORE
# =============================================================

def compute_health_score(
    confidence: float,
    anomaly_count: int,
    trend: str,
    top_shap_magnitude: float,
) -> float:
    """
    Returns a 0–100 health index.
    100 = perfect health, 0 = imminent failure.
    """
    base  = (1.0 - confidence) * 100.0
    base -= anomaly_count * 4.0
    if trend == "RISING":
        base -= 8.0
    elif trend == "FALLING":
        base += 3.0
    if top_shap_magnitude > 0.5:
        base -= 6.0
    elif top_shap_magnitude > 0.3:
        base -= 3.0
    return round(max(0.0, min(100.0, base)), 1)


# =============================================================
# SECTION 4 — FAILURE MODE CLASSIFIER
# =============================================================

def classify_failure_mode(shap_dict: dict, sensor_data: dict) -> str:
    """
    Identifies the dominant failure mode from SHAP and sensor data.
    Returns one of the keys in config.FAILURE_MODE_SENSORS.
    """
    mode_scores: dict[str, float] = {}

    for mode, sensors in config.FAILURE_MODE_SENSORS.items():
        score = 0.0
        for s in sensors:
            shap_contrib = abs(shap_dict.get(s, 0.0))
            sensor_val   = sensor_data.get(s)
            if sensor_val is not None and s in config.SENSOR_META:
                meta  = config.SENSOR_META[s]
                range_ = meta["max"] - meta["min"] or 1
                norm   = (sensor_val - meta["min"]) / range_
                score += shap_contrib * (1 + norm)
            else:
                score += shap_contrib
        mode_scores[mode] = score

    if not mode_scores or max(mode_scores.values()) < 0.001:
        return "UNKNOWN"
    return max(mode_scores, key=mode_scores.get)


# =============================================================
# SECTION 5 — PRESCRIPTIVE MAINTENANCE ENGINE
# =============================================================

# Each rule: condition(sensor_data) → action payload
_PRESCRIPTIVE_RULES = [
    {
        "id":           "TEMP_HIGH",
        "failure_mode": "THERMAL_OVERLOAD",
        "priority":     "P1",
        "condition":    lambda d: (d.get("sensor_1") or 0) > config.SENSOR_META["sensor_1"]["critical_high"],
        "action":       "Reduce equipment load by 20%. Inspect cooling fan and heat exchangers.",
        "detail":       "Temperature sensor exceeds critical threshold of {threshold}°C.",
        "threshold":    config.SENSOR_META["sensor_1"]["critical_high"],
        "est_hours":    2,
        "cost_impact":  "LOW",
    },
    {
        "id":           "VIB_HIGH",
        "failure_mode": "MECHANICAL_FAILURE",
        "priority":     "P1",
        "condition":    lambda d: (d.get("sensor_10") or 0) > config.SENSOR_META["sensor_10"]["critical_high"],
        "action":       "Halt equipment for bearing alignment and balance inspection.",
        "detail":       "Vibration exceeds {threshold} mm/s — bearing wear or misalignment likely.",
        "threshold":    config.SENSOR_META["sensor_10"]["critical_high"],
        "est_hours":    4,
        "cost_impact":  "HIGH",
    },
    {
        "id":           "RPM_HIGH",
        "failure_mode": "MECHANICAL_FAILURE",
        "priority":     "P2",
        "condition":    lambda d: (d.get("sensor_4") or 0) > config.SENSOR_META["sensor_4"]["critical_high"],
        "action":       "Reduce rotational speed. Check governor and speed control system.",
        "detail":       "RPM exceeds safe limit of {threshold} rpm.",
        "threshold":    config.SENSOR_META["sensor_4"]["critical_high"],
        "est_hours":    1,
        "cost_impact":  "MEDIUM",
    },
    {
        "id":           "PRESSURE_HIGH",
        "failure_mode": "PRESSURE_ANOMALY",
        "priority":     "P1",
        "condition":    lambda d: (d.get("sensor_2") or 0) > config.SENSOR_META["sensor_2"]["critical_high"],
        "action":       "Activate pressure relief valve. Inspect seals and pressure lines immediately.",
        "detail":       "Main pressure exceeds {threshold} bar — risk of seal rupture.",
        "threshold":    config.SENSOR_META["sensor_2"]["critical_high"],
        "est_hours":    3,
        "cost_impact":  "HIGH",
    },
    {
        "id":           "VOLTAGE_HIGH",
        "failure_mode": "ELECTRICAL_FAULT",
        "priority":     "P2",
        "condition":    lambda d: (d.get("sensor_5") or 0) > config.SENSOR_META["sensor_5"]["critical_high"],
        "action":       "Inspect voltage regulator and power supply module.",
        "detail":       "Voltage above {threshold}V — risk of insulation damage.",
        "threshold":    config.SENSOR_META["sensor_5"]["critical_high"],
        "est_hours":    2,
        "cost_impact":  "MEDIUM",
    },
    {
        "id":           "CURRENT_HIGH",
        "failure_mode": "ELECTRICAL_FAULT",
        "priority":     "P2",
        "condition":    lambda d: (d.get("sensor_6") or 0) > config.SENSOR_META["sensor_6"]["critical_high"],
        "action":       "Check motor windings and circuit breakers for overload condition.",
        "detail":       "Current exceeds {threshold}A — possible motor overload.",
        "threshold":    config.SENSOR_META["sensor_6"]["critical_high"],
        "est_hours":    2,
        "cost_impact":  "MEDIUM",
    },
    {
        "id":           "FREQ_ANOMALY",
        "failure_mode": "ELECTRICAL_FAULT",
        "priority":     "P2",
        "condition":    lambda d: (d.get("sensor_8") or 0) > config.SENSOR_META["sensor_8"]["critical_high"],
        "action":       "Inspect VFD (Variable Frequency Drive) and frequency converter.",
        "detail":       "Operating frequency deviates significantly from nominal — drive instability.",
        "threshold":    config.SENSOR_META["sensor_8"]["critical_high"],
        "est_hours":    3,
        "cost_impact":  "MEDIUM",
    },
    {
        "id":           "AMBIENT_HIGH",
        "failure_mode": "THERMAL_OVERLOAD",
        "priority":     "P3",
        "condition":    lambda d: (d.get("sensor_7") or 0) > config.SENSOR_META["sensor_7"]["critical_high"],
        "action":       "Improve area ventilation. Check HVAC system and equipment enclosure cooling.",
        "detail":       "Ambient temperature exceeds {threshold}°C — thermal stress on electronics.",
        "threshold":    config.SENSOR_META["sensor_7"]["critical_high"],
        "est_hours":    1,
        "cost_impact":  "LOW",
    },
]


def run_prescriptive_engine(sensor_data: dict, failure_mode: str, confidence: float) -> list[dict]:
    """
    Evaluates all prescriptive rules against current sensor readings.
    Returns ranked list of maintenance actions.
    """
    triggered = []
    for rule in _PRESCRIPTIVE_RULES:
        try:
            if rule["condition"](sensor_data):
                triggered.append({
                    "rule_id":       rule["id"],
                    "failure_mode":  rule["failure_mode"],
                    "priority":      rule["priority"],
                    "action":        rule["action"],
                    "detail":        rule["detail"].format(threshold=rule["threshold"]),
                    "est_fix_hours": rule["est_hours"],
                    "cost_impact":   rule["cost_impact"],
                })
        except Exception:
            pass

    # If no specific rule triggered but confidence is high, add a generic action
    if not triggered and confidence > config.THRESHOLD:
        triggered.append({
            "rule_id":       "GENERAL",
            "failure_mode":  failure_mode,
            "priority":      "P2",
            "action":        "Perform full equipment inspection. Review maintenance log and last service date.",
            "detail":        f"Failure probability {confidence*100:.1f}% — no single sensor crossed threshold but combined pattern suggests risk.",
            "est_fix_hours": 4,
            "cost_impact":   "MEDIUM",
        })

    # Sort by priority: P1 first
    triggered.sort(key=lambda x: x["priority"])
    return triggered


def get_top_priority(actions: list[dict]) -> str:
    if not actions:
        return "P3"
    return actions[0]["priority"]


# =============================================================
# SECTION 6 — ROOT CAUSE ANALYSIS
# =============================================================

def root_cause_analysis(
    shap_dict:   dict,
    sensor_data: dict,
    confidence:  float,
    failure_mode: str,
) -> dict:
    """
    Builds a multi-step causal chain from SHAP values and sensor context.
    Returns a structured RCA report.
    """
    if not shap_dict:
        return {"primary_cause": "Insufficient data", "causal_chain": []}

    # Primary driver = highest absolute SHAP feature
    top_items   = sorted(shap_dict.items(), key=lambda x: abs(x[1]), reverse=True)
    primary_key = top_items[0][0]
    primary_val = sensor_data.get(primary_key)
    primary_meta= config.SENSOR_META.get(primary_key, {})

    primary_cause = (
        f"{primary_meta.get('name', primary_key)} reading "
        f"{'of ' + str(round(primary_val,1)) + primary_meta.get('unit','') if primary_val is not None else '(missing/imputed)'} "
        f"is the dominant driver (SHAP={top_items[0][1]:+.4f})"
    )

    causal_chain = []
    for i, (feat, shap_val) in enumerate(top_items[:5]):
        meta  = config.SENSOR_META.get(feat, {})
        val   = sensor_data.get(feat)
        system = meta.get("system", "unknown")
        crit  = meta.get("critical_high")
        above_crit = (val is not None and crit is not None and val > crit)

        step = {
            "step":       i + 1,
            "feature":    feat,
            "name":       meta.get("name", feat),
            "system":     system,
            "shap_value": round(shap_val, 4),
            "direction":  "risk-increasing" if shap_val > 0 else "risk-reducing",
            "value":      round(val, 2) if val is not None else None,
            "unit":       meta.get("unit", ""),
            "above_critical": above_crit,
            "narrative":  _build_rca_narrative(feat, val, shap_val, meta, above_crit),
        }
        causal_chain.append(step)

    # Failure mode explanation
    mode_desc = {
        "THERMAL_OVERLOAD":    "Heat accumulation exceeding equipment design limits",
        "MECHANICAL_FAILURE":  "Mechanical stress, wear, or misalignment in rotating components",
        "ELECTRICAL_FAULT":    "Electrical parameter deviation — power supply or motor drive anomaly",
        "PRESSURE_ANOMALY":    "Pressure system imbalance — potential seal or valve issue",
        "ENVIRONMENTAL_STRESS":"Environmental conditions degrading component performance",
        "UNKNOWN":             "No dominant single system — multi-factor degradation pattern",
    }

    return {
        "primary_cause":      primary_cause,
        "causal_chain":       causal_chain,
        "failure_mode":       failure_mode,
        "mode_description":   mode_desc.get(failure_mode, ""),
        "confidence":         round(confidence, 4),
        "chain_depth":        len(causal_chain),
        "recommendation":     _rca_recommendation(failure_mode, causal_chain),
    }


def _build_rca_narrative(feat: str, val, shap_val: float, meta: dict, above_crit: bool) -> str:
    name  = meta.get("name", feat)
    unit  = meta.get("unit", "")
    val_s = f"{round(val,1)}{unit}" if val is not None else "missing"
    direc = "elevated" if shap_val > 0 else "suppressed"
    crit  = " — ABOVE CRITICAL LIMIT" if above_crit else ""
    return f"{name} ({val_s}) is {direc}, contributing {shap_val:+.4f} to failure probability{crit}."


def _rca_recommendation(failure_mode: str, chain: list) -> str:
    above_crit = [s for s in chain if s.get("above_critical")]
    if above_crit:
        sensors = ", ".join(s["name"] for s in above_crit)
        return f"Immediate inspection of {failure_mode.replace('_',' ').title()} system. Sensors above critical: {sensors}."
    return f"Schedule {failure_mode.replace('_',' ').title()} system diagnostic within 24 hours."


# =============================================================
# SECTION 7 — PUBLIC API
# =============================================================

def predict(data: dict) -> dict:
    """
    Full prediction pipeline.
    Returns enriched decision report including RCA, prescriptive actions,
    health score, failure mode classification.
    """
    # Step 1: Build DataFrame
    input_df = pd.DataFrame([data]).reindex(columns=expected_columns)

    # Step 2: Safety check
    imputer = pipeline.named_steps.get("imputer")
    assert imputer is not None and hasattr(imputer, "transform"), \
        "Pipeline missing 'imputer' step"

    # Step 3: Predict probability
    proba      = pipeline.predict_proba(input_df)
    confidence = float(proba[0][1])
    prediction = int(confidence >= config.THRESHOLD)

    # Step 4: SHAP
    preprocessor      = _get_preprocessor()
    input_transformed = preprocessor.transform(input_df)
    shap_dict         = _compute_shap(input_transformed)

    # Step 5: Core decision
    decision    = _build_decision(confidence)
    ttf         = _estimate_ttf(confidence, shap_dict)
    top_factors = _simplify_shap(shap_dict)
    alert       = _build_alert(confidence)
    anomalies, anomaly_warning = _detect_sensor_anomalies(data)
    trend, trend_alert         = _compute_confidence_trend(confidence)

    # Step 6: Advanced analytics
    top_shap_mag  = max((abs(v) for v in shap_dict.values()), default=0.0)
    health_score  = compute_health_score(confidence, len(anomalies), trend, top_shap_mag)
    failure_mode  = classify_failure_mode(shap_dict, data)
    prescriptive  = run_prescriptive_engine(data, failure_mode, confidence)
    top_priority  = get_top_priority(prescriptive)
    rca           = root_cause_analysis(shap_dict, data, confidence, failure_mode)

    return {
        "prediction":            prediction,
        "confidence":            round(confidence, 4),
        "severity":              decision["severity"],
        "recommendation":        decision["recommendation"],
        "time_to_failure_hours": ttf,
        "health_score":          health_score,
        "failure_mode":          failure_mode,
        "top_factors":           top_factors,
        "alert":                 alert["alert"],
        "alert_message":         alert["alert_message"],
        "sensor_anomalies":      anomalies,
        "anomaly_warning":       anomaly_warning,
        "confidence_trend":      trend,
        "trend_alert":           trend_alert,
        "prescriptive_actions":  prescriptive,
        "maintenance_priority":  top_priority,
        "rca":                   rca,
        "model_version":         MODEL_VERSION,
        "shap_values":           shap_dict,
    }
