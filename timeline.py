# =============================================================
# timeline.py — Equipment Timeline (§5 of v4.2.0)
# NABDH AI Maintenance Platform
# =============================================================
#
# Kept separate from ml_logic.py so the Random Forest / SHAP pipeline file
# stays untouched, per the platform's explicit constraint. Everything here
# is read-only aggregation over already-persisted predictions and
# prescriptive_actions — no new model inference.

from datetime import datetime, timedelta, timezone
from typing import Optional

import database

CRITICAL_HEALTH_THRESHOLD = 20.0


def bucket_status(health_score: Optional[float]) -> str:
    """Buckets a health_score (0-100) into the traffic-light status the
    dashboard renders (green/yellow/red)."""
    if health_score is None:
        return "unknown"
    if health_score >= 60:
        return "green"
    if health_score >= 30:
        return "yellow"
    return "red"


def project_next_maintenance(
    predictions: list[dict],
    critical_threshold: float = CRITICAL_HEALTH_THRESHOLD,
) -> Optional[dict]:
    """
    Linear-slope degradation projection: fits health_score against elapsed
    hours over the equipment's recent prediction history (least-squares) and
    projects the ETA to cross `critical_threshold`.

    Returns None if there isn't enough history yet (fewer than 2 points with
    a health_score, or all points at an identical timestamp). Returns a dict
    with eta_hours=None when health is flat or improving (slope >= 0) — no
    maintenance is being projected, which is a valid, common outcome, not
    a missing-data case.
    """
    points = [
        (p["timestamp"], p["health_score"])
        for p in predictions
        if p.get("health_score") is not None and p.get("timestamp")
    ]
    if len(points) < 2:
        return None

    points.sort(key=lambda p: p[0])
    t0 = datetime.fromisoformat(points[0][0])
    xs = [(datetime.fromisoformat(ts) - t0).total_seconds() / 3600.0 for ts, _ in points]
    ys = [hs for _, hs in points]

    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None  # all points at the same timestamp — no time axis to fit against

    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom  # health-points per hour
    intercept = mean_y - slope * mean_x

    if slope >= 0:
        return {
            "eta_hours": None,
            "eta_timestamp": None,
            "message": "Health is stable or improving — no maintenance projected.",
        }

    hours_to_critical = (critical_threshold - intercept) / slope
    remaining_hours = hours_to_critical - xs[-1]

    if remaining_hours <= 0:
        return {
            "eta_hours": 0.0,
            "eta_timestamp": datetime.now(timezone.utc).isoformat(),
            "message": "Health is already at or below the critical threshold.",
        }

    eta = datetime.now(timezone.utc) + timedelta(hours=remaining_hours)
    return {
        "eta_hours": round(remaining_hours, 1),
        "eta_timestamp": eta.isoformat(),
        "message": (
            f"Projected to reach critical health (<{critical_threshold:.0f}) "
            f"in ~{round(remaining_hours, 1)}h based on the recent degradation rate."
        ),
    }


def get_equipment_timeline(equipment_id: int, history_limit: int = 20) -> dict:
    """
    Returns: last actual maintenance -> current predicted status -> projected
    next maintenance date, for one piece of equipment.
    """
    predictions = database.get_predictions_by_equipment(equipment_id, limit=history_limit)
    last_maintenance = database.get_latest_resolved_prescriptive(equipment_id)

    if not predictions:
        return {
            "equipment_id": equipment_id,
            "last_maintenance": last_maintenance,
            "current_status": None,
            "next_predicted_maintenance": None,
        }

    latest = predictions[0]  # get_predictions_by_equipment orders by timestamp DESC
    current_status = {
        "health_score": latest.get("health_score"),
        "severity": latest.get("severity"),
        "status_color": bucket_status(latest.get("health_score")),
        "as_of": latest.get("timestamp"),
    }

    return {
        "equipment_id": equipment_id,
        "last_maintenance": last_maintenance,
        "current_status": current_status,
        "next_predicted_maintenance": project_next_maintenance(predictions),
    }
