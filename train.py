# =============================================================
# train.py — Model Training Script
# NABDH Predictive Maintenance System v4
# Run once to generate: pipeline.pkl, expected_columns.pkl,
#                        model_version.json, reference_data.csv
# =============================================================

import json
import os
import numpy as np
import pandas as pd
import joblib
from datetime import datetime, timezone
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.feature_selection import SelectFromModel
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import (
    classification_report, roc_auc_score,
    confusion_matrix, f1_score,
)

# ── Reproducibility ───────────────────────────────────────────
SEED       = 42
N_SAMPLES  = 5000
np.random.seed(SEED)

# =============================================================
# REALISTIC SYNTHETIC DATA GENERATION
# Physical ranges aligned with config.py SENSOR_META
# =============================================================

def generate_data(n: int, seed: int = 42) -> tuple[pd.DataFrame, pd.Series]:
    """
    Simulate industrial sensor readings with realistic failure patterns.

    Failure modes injected:
      - THERMAL_OVERLOAD:    sensor_1 (Temp) + sensor_7 (Ambient) spike
      - MECHANICAL_FAILURE:  sensor_4 (RPM) + sensor_10 (Vibration) anomaly
      - ELECTRICAL_FAULT:    sensor_5/6 (V/A) + sensor_8 (Freq) deviation
      - PRESSURE_ANOMALY:    sensor_2/9 (Pressure) excess
      - ENVIRONMENTAL_STRESS: sensor_3 (Humidity) extreme
    """
    rng = np.random.default_rng(seed)

    # ── Normal operating baseline ─────────────────────────────
    data = {
        "sensor_1":  rng.normal(loc=55.0,  scale=10.0,  size=n),   # Temp °C
        "sensor_2":  rng.normal(loc=150.0, scale=25.0,  size=n),   # Pressure bar
        "sensor_3":  rng.normal(loc=55.0,  scale=12.0,  size=n),   # Humidity %
        "sensor_4":  rng.normal(loc=280.0, scale=50.0,  size=n),   # RPM
        "sensor_5":  rng.normal(loc=50.0,  scale=8.0,   size=n),   # Voltage V
        "sensor_6":  rng.normal(loc=45.0,  scale=7.0,   size=n),   # Current A
        "sensor_7":  rng.normal(loc=25.0,  scale=5.0,   size=n),   # Ambient °C
        "sensor_8":  rng.normal(loc=100.0, scale=12.0,  size=n),   # Frequency Hz
        "sensor_9":  rng.normal(loc=50.0,  scale=8.0,   size=n),   # Pressure 2 kPa
        "sensor_10": rng.normal(loc=25.0,  scale=8.0,   size=n),   # Vibration mm/s
    }
    df    = pd.DataFrame(data)
    y     = np.zeros(n, dtype=int)
    modes = np.array(["NORMAL"] * n)

    # ── Failure injection (25 % failure rate, multiple modes) ─
    n_fail   = int(n * 0.25)
    fail_idx = rng.choice(n, size=n_fail, replace=False)

    mode_weights = [0.30, 0.25, 0.20, 0.15, 0.10]
    mode_labels  = [
        "THERMAL_OVERLOAD",
        "MECHANICAL_FAILURE",
        "ELECTRICAL_FAULT",
        "PRESSURE_ANOMALY",
        "ENVIRONMENTAL_STRESS",
    ]
    assigned_modes = rng.choice(mode_labels, size=n_fail, p=mode_weights)

    for i, idx in enumerate(fail_idx):
        mode = assigned_modes[i]
        y[idx] = 1
        modes[idx] = mode

        if mode == "THERMAL_OVERLOAD":
            df.loc[idx, "sensor_1"]  = rng.uniform(85,  115)
            df.loc[idx, "sensor_7"]  = rng.uniform(45,   60)
            df.loc[idx, "sensor_3"]  = rng.uniform(80,  100)

        elif mode == "MECHANICAL_FAILURE":
            df.loc[idx, "sensor_4"]  = rng.uniform(420, 520)
            df.loc[idx, "sensor_10"] = rng.uniform(68,  100)
            df.loc[idx, "sensor_2"]  = rng.uniform(230, 310)

        elif mode == "ELECTRICAL_FAULT":
            df.loc[idx, "sensor_5"]  = rng.choice([rng.uniform(0, 20), rng.uniform(88, 110)])
            df.loc[idx, "sensor_6"]  = rng.uniform(82, 100)
            df.loc[idx, "sensor_8"]  = rng.choice([rng.uniform(0, 30), rng.uniform(178, 210)])

        elif mode == "PRESSURE_ANOMALY":
            df.loc[idx, "sensor_2"]  = rng.uniform(248, 320)
            df.loc[idx, "sensor_9"]  = rng.uniform(84,  110)

        elif mode == "ENVIRONMENTAL_STRESS":
            df.loc[idx, "sensor_3"]  = rng.uniform(90,  100)
            df.loc[idx, "sensor_1"]  = rng.uniform(75,   95)
            df.loc[idx, "sensor_7"]  = rng.uniform(42,   55)

    # ── Clip to plausible physical bounds ────────────────────
    clips = {
        "sensor_1":  (0,   130),
        "sensor_2":  (0,   350),
        "sensor_3":  (0,   100),
        "sensor_4":  (0,   600),
        "sensor_5":  (0,   120),
        "sensor_6":  (0,   110),
        "sensor_7":  (-15,  65),
        "sensor_8":  (0,   220),
        "sensor_9":  (0,   120),
        "sensor_10": (0,   110),
    }
    for col, (lo, hi) in clips.items():
        df[col] = df[col].clip(lo, hi)

    # ── Introduce realistic missing values (2 %) ─────────────
    for col in df.columns:
        miss_idx = rng.choice(n, size=max(1, int(n * 0.02)), replace=False)
        df.loc[miss_idx, col] = np.nan

    return df, pd.Series(y, name="failure"), pd.Series(modes, name="failure_mode")


# =============================================================
# GENERATE DATASETS
# =============================================================

print("=" * 60)
print("  NABDH AI Maintenance — Model Training")
print("=" * 60)
print(f"\n[1/6] Generating {N_SAMPLES} synthetic sensor records...")
X, y, modes = generate_data(N_SAMPLES, seed=SEED)

# Reference data: 2000 normal-only samples for drift detection baseline
print("[2/6] Generating reference dataset (normal operations only)...")
X_ref, y_ref, _ = generate_data(2000, seed=SEED + 99)
X_ref = X_ref[y_ref == 0].reset_index(drop=True)   # keep only normal

# ── Train / test split ────────────────────────────────────────
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.20, random_state=SEED, stratify=y,
)
print(f"   Train: {len(X_train)}  Test: {len(X_test)}")
print(f"   Failure rate (train): {y_train.mean()*100:.1f}%")

# =============================================================
# BUILD & TRAIN PIPELINE
# =============================================================

print("\n[3/6] Building sklearn pipeline...")
pipeline = Pipeline([
    ("imputer", SimpleImputer(strategy="median")),
    ("scaler",  StandardScaler()),
    ("feature_selector", SelectFromModel(
        RandomForestClassifier(n_estimators=50, random_state=SEED),
        threshold="median",
    )),
    ("classifier", RandomForestClassifier(
        n_estimators     = 200,
        max_depth        = 14,
        min_samples_leaf = 4,
        max_features     = "sqrt",
        class_weight     = "balanced",
        random_state     = SEED,
        n_jobs           = -1,
    )),
])

print("[4/6] Training model (this may take ~30 s)...")
pipeline.fit(X_train, y_train)

# =============================================================
# EVALUATION
# =============================================================

print("\n[5/6] Evaluating model...")
y_pred     = pipeline.predict(X_test)
y_prob     = pipeline.predict_proba(X_test)[:, 1]
auc        = roc_auc_score(y_test, y_prob)
f1         = f1_score(y_test, y_pred)
cv_scores  = cross_val_score(pipeline, X_train, y_train, cv=5, scoring="roc_auc", n_jobs=-1)
cm         = confusion_matrix(y_test, y_pred)

print("\n  Classification Report:")
print(classification_report(y_test, y_pred, target_names=["Normal", "Failure"]))
print(f"  ROC-AUC : {auc:.4f}")
print(f"  F1 Score: {f1:.4f}")
print(f"  CV AUC  : {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")
print(f"  Confusion Matrix:\n  {cm}")

# =============================================================
# SAVE ARTIFACTS
# =============================================================

print("\n[6/6] Saving artifacts...")

# pipeline.pkl
joblib.dump(pipeline, "pipeline.pkl")
print("  ✔ pipeline.pkl")

# expected_columns.pkl
joblib.dump(X.columns.tolist(), "expected_columns.pkl")
print("  ✔ expected_columns.pkl")

# reference_data.csv  (used by drift detection in monitoring.py)
X_ref.to_csv("reference_data.csv", index=False)
print(f"  ✔ reference_data.csv  ({len(X_ref)} rows)")

# model_version.json
version_info = {
    "version":          "1.0.0",
    "trained_at":       datetime.now(timezone.utc).isoformat(),
    "n_train_samples":  int(len(X_train)),
    "n_features":       int(X.shape[1]),
    "roc_auc":          round(float(auc), 4),
    "f1_score":         round(float(f1), 4),
    "cv_auc_mean":      round(float(cv_scores.mean()), 4),
    "cv_auc_std":       round(float(cv_scores.std()), 4),
    "algorithm":        "RandomForestClassifier",
    "n_estimators":     200,
    "failure_rate_pct": round(float(y.mean() * 100), 2),
    "features":         X.columns.tolist(),
}
with open("model_version.json", "w") as f:
    json.dump(version_info, f, indent=2)
print("  ✔ model_version.json")

# =============================================================
# SUMMARY
# =============================================================

print("\n" + "=" * 60)
print("  Training Complete!")
print("=" * 60)
print(f"  Model version : {version_info['version']}")
print(f"  ROC-AUC       : {auc:.4f}")
print(f"  F1 Score      : {f1:.4f}")
print(f"  Artifacts     : pipeline.pkl, expected_columns.pkl,")
print(f"                  reference_data.csv, model_version.json")
print("\n  Run the API:  uvicorn main:app --reload --port 8000")
print("  Run the UI:   streamlit run dashboard.py")
