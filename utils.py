# =============================================================
# utils.py — Helper Functions
# NABDH Predictive Maintenance System
# =============================================================

import time
import logging
from functools import wraps
from typing import Callable, Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# =============================================================
# TIMING DECORATOR
# =============================================================

def timer(func: Callable) -> Callable:
    """
    Decorator — logs execution time of any function.
    Usage:
        @timer
        def my_function(): ...
    """
    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        t0     = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(f"{func.__name__} executed in {elapsed_ms:.2f}ms")
        return result
    return wrapper

# =============================================================
# INPUT VALIDATION
# =============================================================

def validate_sensor_range(
    data: dict,
    bounds: dict[str, tuple[float, float]],
) -> list[str]:
    """
    Validates that sensor values fall within expected physical bounds.

    Args:
        data:   dict of {sensor_name: value}
        bounds: dict of {sensor_name: (min_val, max_val)}

    Returns:
        List of warning strings for any out-of-range sensors.
        Empty list = all valid.

    Usage:
        BOUNDS = {
            "sensor_1": (0.0, 100.0),
            "sensor_2": (20.0, 300.0),
        }
        warnings = validate_sensor_range(input_data, BOUNDS)
    """
    warnings = []
    for sensor, value in data.items():
        if value is None:
            continue  # NaN is valid — pipeline will impute
        if sensor in bounds:
            lo, hi = bounds[sensor]
            if not (lo <= value <= hi):
                warnings.append(
                    f"{sensor}={value} is outside expected range [{lo}, {hi}]"
                )
    return warnings


def sanitize_input(data: dict) -> dict:
    """
    Converts non-finite floats (inf, -inf) to None (→ NaN in DataFrame).
    Leaves None and valid floats unchanged.
    Does NOT replace None/NaN with 0 — that is handled by the pipeline.
    """
    sanitized = {}
    for k, v in data.items():
        if isinstance(v, float) and not np.isfinite(v):
            logger.warning(f"Non-finite value for {k}: {v} → replaced with None")
            sanitized[k] = None
        else:
            sanitized[k] = v
    return sanitized

# =============================================================
# SHAP FORMATTING
# =============================================================

def format_shap_for_display(shap_dict: dict, top_n: int = 10) -> list[dict]:
    """
    Sorts SHAP values by absolute importance and returns top N.

    Args:
        shap_dict: {feature_name: shap_value}
        top_n:     number of top features to return

    Returns:
        List of dicts sorted by |shap_value| descending:
        [{"feature": "sensor_1", "shap_value": 0.42}, ...]
    """
    sorted_items = sorted(
        shap_dict.items(),
        key=lambda x: abs(x[1]),
        reverse=True,
    )
    return [
        {"feature": k, "shap_value": round(v, 6)}
        for k, v in sorted_items[:top_n]
    ]

# =============================================================
# DATAFRAME HELPERS
# =============================================================

def safe_reindex(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """
    Reindexes DataFrame to match expected column order.
    Missing columns become NaN — NOT 0.0.
    This is the correct behavior: pipeline imputer handles NaN.
    """
    return df.reindex(columns=columns)
    # ✅ No fill_value — intentional


def describe_missing(df: pd.DataFrame) -> dict:
    """
    Returns count and percentage of missing values per column.
    Useful for debugging input quality.
    """
    total  = len(df)
    result = {}
    for col in df.columns:
        missing = int(df[col].isna().sum())
        result[col] = {
            "missing_count":   missing,
            "missing_percent": round(missing / total * 100, 2) if total > 0 else 0.0,
        }
    return result