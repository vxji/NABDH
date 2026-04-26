@echo off
REM =============================================================
REM  run_project.bat — NABDH AI Maintenance Platform (Windows)
REM =============================================================

echo.
echo ==================================================
echo   NABDH AI Maintenance Platform — Local Dev
echo ==================================================
echo.

REM ── Check .env ───────────────────────────────────────────────
if not exist ".env" (
    echo [SETUP] .env not found — creating from .env.example...
    copy .env.example .env > nul
    echo [SETUP] Created .env with default values.
    echo [SETUP] Edit .env to set your own passwords before production use.
    echo.
)

REM ── Auto-train if artifacts are missing ──────────────────────
if not exist "pipeline.pkl" (
    echo [TRAIN] pipeline.pkl not found — running train.py...
    python train.py
    if errorlevel 1 (
        echo [ERROR] Training failed. Check train.py output above.
        pause
        exit /b 1
    )
    echo [TRAIN] Done.
)

if not exist "model_version.json" (
    echo [TRAIN] model_version.json missing — running train.py...
    python train.py
    if errorlevel 1 (
        echo [ERROR] Training failed.
        pause
        exit /b 1
    )
)

REM ── Start FastAPI Backend ─────────────────────────────────────
echo [API] Starting FastAPI backend on port 8000...
start "NABDH API" cmd /k "python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload"

REM ── Brief pause to let the API initialize ─────────────────────
echo [API] Waiting for backend to initialize (8 seconds)...
timeout /t 8 /nobreak > nul

REM ── Start Streamlit Dashboard ─────────────────────────────────
echo [DASHBOARD] Starting Streamlit dashboard on port 8501...
start "NABDH Dashboard" cmd /k "python -m streamlit run dashboard.py --server.port 8501"

REM ── Open browser automatically ────────────────────────────────
echo [BROWSER] Opening dashboard...
timeout /t 3 /nobreak > nul
start http://localhost:8501

REM ── Summary ───────────────────────────────────────────────────
echo.
echo ==================================================
echo   Services started in separate windows:
echo     API        -^>  http://127.0.0.1:8000
echo     Dashboard  -^>  http://localhost:8501
echo     API Docs   -^>  http://127.0.0.1:8000/docs
echo.
echo   Default login (from .env):
echo     admin    /  ADMIN_PASSWORD
echo     operator /  OPERATOR_PASSWORD
echo     viewer   /  VIEWER_PASSWORD
echo ==================================================
echo.
echo   Press any key to close this launcher window.
echo   The API and Dashboard windows will keep running.
echo.
pause
