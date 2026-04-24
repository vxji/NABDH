# =============================================================
# Dockerfile — NABDH AI Maintenance Platform (API service)
# =============================================================

FROM python:3.10-slim

# ── System deps ───────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python deps (cached layer) ────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────
COPY . .

# ── Train model if artifacts are missing ──────────────────────
RUN python -c "\
import os; \
missing = not (os.path.exists('pipeline.pkl') and \
               os.path.exists('expected_columns.pkl') and \
               os.path.exists('model_version.json')); \
print('Artifacts present — skipping training.' if not missing else 'Artifacts missing — training now...'); \
missing and __import__('subprocess').run(['python', 'train.py'], check=True)"

# ── Healthcheck ───────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
