# =============================================================
# services/notifications/proactive_check.py — Daily proactive maintenance scan
# NABDH AI Maintenance Platform v4.2.0
# =============================================================
#
# Fires *before* monitoring.log_alert's reactive threshold (ALERT_MIN_CONFIDENCE)
# is crossed. Reuses already-computed health_score/confidence — no changes to
# ml_logic.py's Random Forest / SHAP pipeline.
#
# NABDH doesn't have a multi-equipment model yet (that lands with §1's
# `equipment` table). This runs against the single implicit machine the app
# monitors today; the entry point takes an `equipment_id` so wiring in
# per-equipment iteration later is additive, not a rewrite.

import asyncio
import logging
from typing import Optional

import config
import monitoring

logger = logging.getLogger(__name__)


def is_approaching_critical(health_score: Optional[float], trend: str, drift_flag: bool) -> bool:
    """
    Pure predicate — true when the equipment is heading toward failure but
    hasn't crossed ALERT_MIN_CONFIDENCE yet. Two independent signals:

      1. health_score has already dropped below PROACTIVE_HEALTH_THRESHOLD, or
      2. confidence trend is RISING, confirmed by an active drift flag as a
         secondary signal (avoids over-alerting on a single noisy reading).
    """
    if health_score is not None and health_score < config.PROACTIVE_HEALTH_THRESHOLD:
        return True
    if trend == "RISING" and drift_flag:
        return True
    return False


def _infer_trend(confidences: list) -> str:
    if len(confidences) < 3:
        return "STABLE"
    delta = confidences[-1] - confidences[-3]
    if delta > 0.05:
        return "RISING"
    if delta < -0.05:
        return "FALLING"
    return "STABLE"


def run_daily_check(equipment_id: Optional[int] = None) -> Optional[dict]:
    """
    Entry point for the APScheduler cron job. Returns the dispatched
    notification's dict of {username: {channel: bool}} if one was sent, or
    None if nothing was approaching critical.
    """
    from services.notifications import dispatcher

    history = monitoring.get_history(limit=10)
    if not history:
        return None

    latest = history[0]
    drift = monitoring.get_drift_report()
    drift_flag = bool(drift.get("drifted_features"))
    trend = _infer_trend([r["confidence"] for r in reversed(history)])

    if not is_approaching_critical(latest.get("health_score"), trend, drift_flag):
        return None

    subject = "NABDH — Proactive Maintenance Alert"
    body = (
        f"Health score is {latest.get('health_score')} "
        f"(confidence trend: {trend}, drift detected: {drift_flag}). "
        "This is a proactive warning issued before the reactive alert "
        "threshold is crossed — schedule an inspection now."
    )
    logger.warning("[proactive-check] %s", body)
    return asyncio.run(dispatcher.notify_all_enabled(subject, body))
