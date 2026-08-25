# =============================================================
# database.py — SQLite Persistence Layer
# NABDH AI Maintenance Platform v4
# =============================================================

import sqlite3
import json
import threading
import logging
from datetime import datetime, timezone
from typing import Optional

import config

logger = logging.getLogger(__name__)

_lock = threading.Lock()


# ── Connection factory ────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Schema bootstrap ──────────────────────────────────────────

def init_db() -> None:
    """Create all tables if they do not exist. Idempotent."""
    ddl = """
    CREATE TABLE IF NOT EXISTS predictions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id    TEXT    NOT NULL UNIQUE,
        timestamp     TEXT    NOT NULL,
        prediction    INTEGER NOT NULL,
        confidence    REAL    NOT NULL,
        severity      TEXT    NOT NULL,
        health_score  REAL,
        failure_mode  TEXT,
        ttf_hours     REAL,
        latency_ms    REAL,
        model_version TEXT,
        sensor_data   TEXT,
        shap_values   TEXT,
        top_factors   TEXT,
        anomalies     TEXT
    );

    CREATE TABLE IF NOT EXISTS alerts (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id   TEXT    NOT NULL,
        timestamp    TEXT    NOT NULL,
        severity     TEXT    NOT NULL,
        confidence   REAL    NOT NULL,
        message      TEXT    NOT NULL,
        sensor_data  TEXT,
        acknowledged INTEGER NOT NULL DEFAULT 0,
        ack_at       TEXT
    );

    CREATE TABLE IF NOT EXISTS prescriptive_actions (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id   TEXT    NOT NULL,
        timestamp    TEXT    NOT NULL,
        failure_mode TEXT,
        actions      TEXT    NOT NULL,
        priority     TEXT    NOT NULL,
        status       TEXT    NOT NULL DEFAULT 'OPEN'
    );

    CREATE TABLE IF NOT EXISTS rca_records (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        request_id    TEXT    NOT NULL UNIQUE,
        timestamp     TEXT    NOT NULL,
        primary_cause TEXT    NOT NULL,
        causal_chain  TEXT    NOT NULL,
        failure_mode  TEXT,
        confidence    REAL
    );

    CREATE TABLE IF NOT EXISTS drift_history (
        id                     INTEGER PRIMARY KEY AUTOINCREMENT,
        checked_at             TEXT    NOT NULL,
        total_features_checked INTEGER NOT NULL,
        drifted_features       TEXT    NOT NULL,
        drift_details          TEXT    NOT NULL,
        retrain_triggered      INTEGER NOT NULL DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS audit_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp  TEXT    NOT NULL,
        method     TEXT    NOT NULL,
        path       TEXT    NOT NULL,
        status     INTEGER,
        latency_ms REAL,
        request_id TEXT,
        user_agent TEXT,
        ip_address TEXT
    );

    CREATE TABLE IF NOT EXISTS security_audit (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        trace_id   TEXT    NOT NULL,
        event_type TEXT    NOT NULL,
        username   TEXT,
        ip_address TEXT,
        user_agent TEXT,
        timestamp  TEXT    NOT NULL,
        detail     TEXT,
        severity   TEXT    NOT NULL DEFAULT 'INFO'
    );

    CREATE INDEX IF NOT EXISTS idx_predictions_timestamp ON predictions(timestamp);
    CREATE INDEX IF NOT EXISTS idx_predictions_severity  ON predictions(severity);
    CREATE INDEX IF NOT EXISTS idx_alerts_acknowledged   ON alerts(acknowledged);
    CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp   ON audit_log(timestamp);
    CREATE INDEX IF NOT EXISTS idx_sec_audit_event       ON security_audit(event_type);
    CREATE INDEX IF NOT EXISTS idx_sec_audit_username    ON security_audit(username);
    CREATE INDEX IF NOT EXISTS idx_sec_audit_timestamp   ON security_audit(timestamp);
    CREATE INDEX IF NOT EXISTS idx_sec_audit_severity    ON security_audit(severity);
    """
    with _lock:
        conn = _connect()
        try:
            conn.executescript(ddl)
            conn.commit()
            logger.info("Database schema initialised at %s", config.DATABASE_PATH)
        finally:
            conn.close()


# ── Predictions ───────────────────────────────────────────────

def insert_prediction(
    request_id:    str,
    prediction:    int,
    confidence:    float,
    severity:      str,
    health_score:  float,
    failure_mode:  str,
    ttf_hours:     float,
    latency_ms:    float,
    model_version: str,
    sensor_data:   dict,
    shap_values:   dict,
    top_factors:   list,
    anomalies:     list,
) -> None:
    sql = """
    INSERT OR IGNORE INTO predictions
        (request_id, timestamp, prediction, confidence, severity,
         health_score, failure_mode, ttf_hours, latency_ms, model_version,
         sensor_data, shap_values, top_factors, anomalies)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        try:
            conn.execute(sql, (
                request_id, ts, prediction, confidence, severity,
                health_score, failure_mode, ttf_hours, latency_ms, model_version,
                json.dumps(sensor_data), json.dumps(shap_values),
                json.dumps(top_factors), json.dumps(anomalies),
            ))
            conn.commit()
        finally:
            conn.close()


def get_predictions(limit: int = 100, offset: int = 0, severity: Optional[str] = None) -> list[dict]:
    where  = "WHERE severity = ?" if severity else ""
    params = (severity, limit, offset) if severity else (limit, offset)
    sql    = f"""
    SELECT id, request_id, timestamp, prediction, confidence, severity,
           health_score, failure_mode, ttf_hours, latency_ms, model_version,
           sensor_data, shap_values, top_factors, anomalies
    FROM predictions {where}
    ORDER BY timestamp DESC LIMIT ? OFFSET ?
    """
    conn = _connect()
    try:
        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for field in ("sensor_data", "shap_values", "top_factors", "anomalies"):
                try:
                    d[field] = json.loads(d[field]) if d[field] else {}
                except Exception:
                    d[field] = {}
            result.append(d)
        return result
    finally:
        conn.close()


def get_prediction_by_id(request_id: str) -> Optional[dict]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM predictions WHERE request_id = ? LIMIT 1", (request_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        for field in ("sensor_data", "shap_values", "top_factors", "anomalies"):
            try:
                d[field] = json.loads(d[field]) if d[field] else {}
            except Exception:
                d[field] = {}
        return d
    finally:
        conn.close()


def count_predictions() -> int:
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM predictions").fetchone()[0]
    finally:
        conn.close()


# ── Analytics ─────────────────────────────────────────────────

def get_analytics(hours: int = 24) -> dict:
    sql = f"""
    SELECT
        COUNT(*)                                    AS total,
        SUM(prediction)                             AS failures,
        ROUND(AVG(confidence), 4)                   AS avg_confidence,
        ROUND(AVG(latency_ms), 2)                   AS avg_latency,
        ROUND(MAX(latency_ms), 2)                   AS max_latency,
        ROUND(AVG(health_score), 2)                 AS avg_health,
        SUM(CASE WHEN severity='HIGH'   THEN 1 END) AS high_count,
        SUM(CASE WHEN severity='MEDIUM' THEN 1 END) AS medium_count,
        SUM(CASE WHEN severity='LOW'    THEN 1 END) AS low_count,
        SUM(CASE WHEN severity='NONE'   THEN 1 END) AS none_count
    FROM predictions
    WHERE timestamp >= datetime('now', '-{hours} hours')
    """
    conn = _connect()
    try:
        row = dict(conn.execute(sql).fetchone())
        trend_rows = [
            dict(r) for r in conn.execute(
                "SELECT timestamp, confidence, prediction, severity, health_score "
                "FROM predictions ORDER BY timestamp DESC LIMIT 50"
            ).fetchall()
        ]
        trend_rows.reverse()
        row["confidence_trend"] = trend_rows
        mode_sql = f"""
        SELECT failure_mode, COUNT(*) as cnt FROM predictions
        WHERE timestamp >= datetime('now', '-{hours} hours') AND failure_mode IS NOT NULL
        GROUP BY failure_mode
        """
        row["failure_mode_distribution"] = [dict(r) for r in conn.execute(mode_sql).fetchall()]
        return row
    finally:
        conn.close()


# ── Alerts ────────────────────────────────────────────────────

def insert_alert(
    request_id:  str,
    severity:    str,
    confidence:  float,
    message:     str,
    sensor_data: dict,
) -> None:
    sql = """
    INSERT INTO alerts (request_id, timestamp, severity, confidence, message, sensor_data)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        try:
            conn.execute(sql, (request_id, ts, severity, confidence, message, json.dumps(sensor_data)))
            conn.commit()
        finally:
            conn.close()


def get_alerts(limit: int = 50, unack_only: bool = False) -> list[dict]:
    where = "WHERE acknowledged = 0" if unack_only else ""
    sql   = f"SELECT * FROM alerts {where} ORDER BY timestamp DESC LIMIT ?"
    conn  = _connect()
    try:
        rows = conn.execute(sql, (limit,)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["sensor_data"] = json.loads(d["sensor_data"]) if d["sensor_data"] else {}
            except Exception:
                d["sensor_data"] = {}
            result.append(d)
        return result
    finally:
        conn.close()


def acknowledge_alert(alert_id: int) -> bool:
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE alerts SET acknowledged=1, ack_at=? WHERE id=?", (ts, alert_id)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


# ── Prescriptive actions ──────────────────────────────────────

def insert_prescriptive(
    request_id:   str,
    failure_mode: str,
    actions:      list,
    priority:     str,
) -> None:
    sql = """
    INSERT INTO prescriptive_actions (request_id, timestamp, failure_mode, actions, priority)
    VALUES (?, ?, ?, ?, ?)
    """
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        try:
            conn.execute(sql, (request_id, ts, failure_mode, json.dumps(actions), priority))
            conn.commit()
        finally:
            conn.close()


def get_prescriptive(limit: int = 20, status: Optional[str] = None) -> list[dict]:
    where  = "WHERE status = ?" if status else ""
    params = (status, limit) if status else (limit,)
    sql    = f"SELECT * FROM prescriptive_actions {where} ORDER BY timestamp DESC LIMIT ?"
    conn   = _connect()
    try:
        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["actions"] = json.loads(d["actions"]) if d["actions"] else []
            except Exception:
                d["actions"] = []
            result.append(d)
        return result
    finally:
        conn.close()


# ── RCA records ───────────────────────────────────────────────

def insert_rca(
    request_id:    str,
    primary_cause: str,
    causal_chain:  list,
    failure_mode:  str,
    confidence:    float,
) -> None:
    sql = """
    INSERT OR IGNORE INTO rca_records
        (request_id, timestamp, primary_cause, causal_chain, failure_mode, confidence)
    VALUES (?, ?, ?, ?, ?, ?)
    """
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        try:
            conn.execute(sql, (request_id, ts, primary_cause, json.dumps(causal_chain), failure_mode, confidence))
            conn.commit()
        finally:
            conn.close()


def get_rca(request_id: str) -> Optional[dict]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM rca_records WHERE request_id = ? LIMIT 1", (request_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["causal_chain"] = json.loads(d["causal_chain"]) if d["causal_chain"] else []
        except Exception:
            d["causal_chain"] = []
        return d
    finally:
        conn.close()


# ── Drift history ─────────────────────────────────────────────

def insert_drift_check(
    total_features_checked: int,
    drifted_features:       list,
    drift_details:          list,
    retrain_triggered:      bool = False,
) -> None:
    sql = """
    INSERT INTO drift_history
        (checked_at, total_features_checked, drifted_features, drift_details, retrain_triggered)
    VALUES (?, ?, ?, ?, ?)
    """
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        try:
            conn.execute(sql, (
                ts, total_features_checked,
                json.dumps(drifted_features), json.dumps(drift_details),
                int(retrain_triggered),
            ))
            conn.commit()
        finally:
            conn.close()


def get_drift_history(limit: int = 20) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM drift_history ORDER BY checked_at DESC LIMIT ?", (limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for field in ("drifted_features", "drift_details"):
                try:
                    d[field] = json.loads(d[field]) if d[field] else []
                except Exception:
                    d[field] = []
            result.append(d)
        return result
    finally:
        conn.close()


# ── Audit log ─────────────────────────────────────────────────

def insert_audit(
    method:     str,
    path:       str,
    status:     int,
    latency_ms: float,
    request_id: Optional[str] = None,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> None:
    sql = """
    INSERT INTO audit_log (timestamp, method, path, status, latency_ms, request_id, user_agent, ip_address)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        try:
            conn.execute(sql, (ts, method, path, status, latency_ms, request_id, user_agent, ip_address))
            conn.commit()
        except Exception as exc:
            logger.warning("Audit insert failed: %s", exc)
        finally:
            conn.close()


def get_audit_log(limit: int = 200, path_filter: Optional[str] = None) -> list[dict]:
    where  = "WHERE path LIKE ?" if path_filter else ""
    params = (f"%{path_filter}%", limit) if path_filter else (limit,)
    sql    = f"SELECT * FROM audit_log {where} ORDER BY timestamp DESC LIMIT ?"
    conn   = _connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# ── Security audit ────────────────────────────────────────────

def insert_security_event(
    trace_id:   str,
    event_type: str,
    severity:   str,
    username:   Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    detail:     Optional[dict] = None,
) -> None:
    """
    Persist a security audit event.
    event_type: login_success | login_failure | token_refresh |
                token_reuse   | unauthorized
    severity:   INFO | WARNING | CRITICAL
    """
    sql = """
    INSERT INTO security_audit
        (trace_id, event_type, username, ip_address, user_agent, timestamp, detail, severity)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        try:
            conn.execute(sql, (
                trace_id, event_type, username, ip_address, user_agent,
                ts, json.dumps(detail) if detail else None, severity,
            ))
            conn.commit()
        except Exception as exc:
            logger.warning("Security audit insert failed: %s", exc)
        finally:
            conn.close()


def set_session_context(username: Optional[str]) -> None:
    """
    Records the current request's user so DB-level triggers can attribute
    activity_log rows to a human.

    SQLite (dev only): best-effort — writes to a single-row `_session_context`
    table that the activity_logs triggers read from. This is a global, not a
    per-connection, value; under concurrent SQLite requests the attribution
    can race. That's acceptable here because SQLite is documented as local
    dev only — the enforced, race-free mechanism is Postgres's per-transaction
    `SET LOCAL app.username`, wired up when the SQLAlchemy/Postgres backend
    lands.
    """
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "UPDATE _session_context SET username = ? WHERE id = 1", (username,)
            )
            conn.commit()
        except sqlite3.OperationalError:
            pass  # _session_context not present (e.g. migrations not yet applied)
        finally:
            conn.close()


# ── Activity log (append-only, DB-trigger populated) ─────────────

def get_activity_logs(
    limit:        int            = 100,
    offset:       int            = 0,
    username:     Optional[str]  = None,
    operation:    Optional[str]  = None,
    table_name:   Optional[str]  = None,
    start_date:   Optional[str]  = None,
    end_date:     Optional[str]  = None,
) -> list[dict]:
    conditions = []
    params: list = []
    if username:
        conditions.append("changed_by = ?")
        params.append(username)
    if operation:
        conditions.append("operation = ?")
        params.append(operation.upper())
    if table_name:
        conditions.append("table_name = ?")
        params.append(table_name)
    if start_date:
        conditions.append("changed_at >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("changed_at <= ?")
        params.append(end_date)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql   = f"SELECT * FROM activity_logs {where} ORDER BY changed_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = _connect()
    try:
        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for field in ("old_data", "new_data"):
                try:
                    d[field] = json.loads(d[field]) if d[field] else None
                except Exception:
                    d[field] = None
            result.append(d)
        return result
    finally:
        conn.close()


def get_notification_settings(username: str) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM notification_settings WHERE username = ? ORDER BY channel", (username,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["enabled"] = bool(d["enabled"])
            try:
                d["config"] = json.loads(d["config"]) if d["config"] else {}
            except Exception:
                d["config"] = {}
            result.append(d)
        return result
    finally:
        conn.close()


def upsert_notification_setting(
    username: str,
    channel:  str,
    enabled:  bool,
    config:   Optional[dict] = None,
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with _lock:
        conn = _connect()
        try:
            existing = conn.execute(
                "SELECT id FROM notification_settings WHERE username = ? AND channel = ?",
                (username, channel),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE notification_settings SET enabled = ?, config = ? WHERE id = ?",
                    (int(enabled), json.dumps(config or {}), existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO notification_settings (username, channel, enabled, config, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (username, channel, int(enabled), json.dumps(config or {}), ts),
                )
            conn.commit()
        finally:
            conn.close()


def get_all_enabled_notification_settings() -> list[dict]:
    """Used by the proactive maintenance scheduler to fan out to every user
    who has at least one enabled notification channel."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM notification_settings WHERE enabled = 1"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["enabled"] = bool(d["enabled"])
            try:
                d["config"] = json.loads(d["config"]) if d["config"] else {}
            except Exception:
                d["config"] = {}
            result.append(d)
        return result
    finally:
        conn.close()


def get_security_events(
    limit:      int            = 100,
    offset:     int            = 0,
    event_type: Optional[str]  = None,
    severity:   Optional[str]  = None,
    username:   Optional[str]  = None,
) -> list[dict]:
    conditions = []
    params: list = []
    if event_type:
        conditions.append("event_type = ?")
        params.append(event_type)
    if severity:
        conditions.append("severity = ?")
        params.append(severity)
    if username:
        conditions.append("username = ?")
        params.append(username)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql   = f"SELECT * FROM security_audit {where} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    conn = _connect()
    try:
        rows = conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["detail"] = json.loads(d["detail"]) if d["detail"] else None
            except Exception:
                d["detail"] = None
            result.append(d)
        return result
    finally:
        conn.close()
