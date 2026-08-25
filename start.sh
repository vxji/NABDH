#!/bin/bash
# =============================================================
# start.sh — NABDH AI Maintenance Platform
# Starts API backend + Streamlit dashboard (local / single-container)
# =============================================================

set -e

# ── Auto-train if artifacts are missing ──────────────────────
if [ ! -f "pipeline.pkl" ] || [ ! -f "expected_columns.pkl" ] || [ ! -f "model_version.json" ]; then
    echo "[TRAIN] Artifacts not found — running train.py..."
    python train.py
    echo "[TRAIN] Done."
fi

# ── Apply DB migrations (activity_logs, permissions, etc.) ────
echo "[DB] Applying Alembic migrations..."
alembic upgrade head

# ── Start FastAPI backend ─────────────────────────────────────
echo "[API] Starting FastAPI on port 8000..."
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 2 &
API_PID=$!

# ── Wait for API to become healthy ───────────────────────────
echo "[API] Waiting for health check..."
MAX_WAIT=30
WAITED=0
until curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; do
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo "[ERROR] API did not start within ${MAX_WAIT}s. Aborting."
        kill $API_PID 2>/dev/null
        exit 1
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done
echo "[API] Ready."

# ── Start Streamlit dashboard ─────────────────────────────────
echo "[DASHBOARD] Starting Streamlit on port 8501..."
streamlit run dashboard.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false &
DASH_PID=$!

echo ""
echo "=================================================="
echo "  NABDH AI Maintenance Platform is running"
echo "  API       →  http://localhost:8000"
echo "  Dashboard →  http://localhost:8501"
echo "  API Docs  →  http://localhost:8000/docs"
echo "=================================================="

# ── Trap signals for clean shutdown ──────────────────────────
trap "echo '[SHUTDOWN] Stopping services...'; kill $API_PID $DASH_PID 2>/dev/null; wait" SIGTERM SIGINT

wait
