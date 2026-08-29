# =============================================================
# dashboard.py — NABDH AI Maintenance Platform
# Apple × Mercedes Luxury UI · v5
# =============================================================

import math
import os
import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

APP_VERSION = "4.2.0"

# ── Endpoints ────────────────────────────────────────────────
BACKEND_HOST  = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
LOGIN_URL     = f"{BACKEND_HOST}/auth/login"
REFRESH_URL   = f"{BACKEND_HOST}/auth/refresh"
API_URL       = f"{BACKEND_HOST}/predict"
STATUS_URL    = f"{BACKEND_HOST}/status"
DRIFT_URL     = f"{BACKEND_HOST}/drift_report"
HISTORY_URL   = f"{BACKEND_HOST}/history"
ANALYTICS_URL = f"{BACKEND_HOST}/analytics"
ALERTS_URL    = f"{BACKEND_HOST}/alerts"
EQUIPMENT_URL = f"{BACKEND_HOST}/equipment"


def timeline_url(equipment_id: int) -> str:
    return f"{BACKEND_HOST}/equipment/{equipment_id}/timeline"


def _expire_session() -> None:
    """Clear all session state and redirect to login with a clean message."""
    st.session_state.clear()
    st.session_state["_session_expired"] = True
    st.rerun()


def _auth_headers() -> dict:
    """Return Bearer auth headers, silently refreshing the access token when < 5 min remain."""
    token = st.session_state.get("access_token")
    if not token:
        _expire_session()

    expires_at = st.session_state.get("token_expires_at")
    if expires_at and datetime.utcnow() + timedelta(minutes=5) >= expires_at:
        refresh_token = st.session_state.get("refresh_token")
        if refresh_token:
            try:
                resp = requests.post(
                    REFRESH_URL,
                    json    = {"refresh_token": refresh_token},
                    timeout = 8,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    st.session_state["access_token"]     = data["access_token"]
                    st.session_state["refresh_token"]    = data["refresh_token"]
                    st.session_state["token_expires_at"] = (
                        datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))
                    )
                    token = data["access_token"]
                else:
                    _expire_session()
            except Exception:
                _expire_session()
        else:
            _expire_session()

    return {"Authorization": f"Bearer {token}"}


def _on_http_error(e: requests.exceptions.HTTPError) -> None:
    """Intercept 401 responses and convert them to a clean session-expired redirect."""
    if e.response is not None and e.response.status_code == 401:
        _expire_session()


_MAIL_ICON_ROW = (
    '<div style="display:flex;align-items:center;gap:6px;margin:0 0 6px;">'
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.45)" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 5L2 7"/></svg>'
    '<span style="font:500 11px/1 Inter,sans-serif;color:rgba(255,255,255,0.45);'
    'letter-spacing:0.3px;text-transform:uppercase;">Username</span></div>'
)
_LOCK_ICON_ROW = (
    '<div style="display:flex;align-items:center;gap:6px;margin:14px 0 6px;">'
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="rgba(255,255,255,0.45)" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
    '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
    '<span style="font:500 11px/1 Inter,sans-serif;color:rgba(255,255,255,0.45);'
    'letter-spacing:0.3px;text-transform:uppercase;">Password</span></div>'
)


def _login_screen() -> None:
    """Render the login screen and handle authentication.

    This is the true first Streamlit command in this run (the auth guard
    below calls st.stop() before the app's own set_page_config/theme CSS
    ever executes), so this function owns its own page config + styling.
    """
    st.set_page_config(
        page_title            = "NABDH · Sign In",
        page_icon             = "◈",
        layout                = "centered",
        initial_sidebar_state = "collapsed",
    )

    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
*, *::before, *::after { box-sizing: border-box; }
html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background: #000 !important;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif !important;
}
#MainMenu, footer, header               { visibility: hidden !important; }
section[data-testid="stSidebar"]        { display: none !important; }

@keyframes loginGlow { 0%, 100% { opacity: 0.55; } 50% { opacity: 0.95; } }
.login-glow {
  position: fixed; top: -12%; left: 50%; transform: translateX(-50%);
  width: 70vw; height: 42vh; border-radius: 50%;
  background: radial-gradient(ellipse at center, rgba(168,85,247,0.35), transparent 70%);
  filter: blur(70px);
  animation: loginGlow 6s ease-in-out infinite;
  pointer-events: none; z-index: 0;
}

.block-container { max-width: 400px !important; padding-top: 9vh !important; position: relative; z-index: 1; }

.login-card {
  background: rgba(20,20,24,0.55);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 20px;
  padding: 32px 28px 8px;
  box-shadow: 0 8px 40px rgba(0,0,0,0.55);
}
.login-logo {
  width: 44px; height: 44px; border-radius: 50%;
  border: 1px solid rgba(255,255,255,0.12);
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 16px;
  background: linear-gradient(135deg, rgba(168,85,247,0.30), rgba(255,255,255,0.02));
  font: 700 18px/1 Inter, sans-serif; color: #f5f5f7;
}
.login-title    { text-align: center; font: 700 22px/1.2 Inter, sans-serif; color: #f5f5f7; margin-bottom: 4px; }
.login-subtitle { text-align: center; font: 400 13px/1.4 Inter, sans-serif; color: rgba(255,255,255,0.5); margin-bottom: 26px; }

[data-testid="stWidgetLabel"] { display: none !important; }
[data-testid="stTextInput"] input {
  background: rgba(255,255,255,0.05) !important;
  border: 1px solid rgba(255,255,255,0.10) !important;
  color: #f5f5f7 !important;
  border-radius: 10px !important;
  height: 42px !important;
}
[data-testid="stTextInput"] input:focus {
  border-color: rgba(168,85,247,0.55) !important;
  box-shadow: 0 0 0 3px rgba(168,85,247,0.15) !important;
}
[data-testid="stTextInput"] input::placeholder { color: rgba(255,255,255,0.28) !important; }

div[data-testid="stFormSubmitButton"] { margin-top: 22px; }
div[data-testid="stFormSubmitButton"] button {
  background: linear-gradient(135deg, #a855f7, #7c3aed) !important;
  color: #fff !important;
  border: none !important;
  border-radius: 10px !important;
  height: 42px !important;
  font-weight: 600 !important;
  box-shadow: 0 4px 20px rgba(168,85,247,0.35) !important;
  transition: transform 0.15s ease, box-shadow 0.15s ease !important;
}
div[data-testid="stFormSubmitButton"] button:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 26px rgba(168,85,247,0.50) !important;
}
</style>
<div class="login-glow"></div>
""", unsafe_allow_html=True)

    st.markdown('<div class="login-card">', unsafe_allow_html=True)
    st.markdown(
        '<div class="login-logo">N</div>'
        '<div class="login-title">Welcome Back</div>'
        '<div class="login-subtitle">Sign in to continue to NABDH</div>',
        unsafe_allow_html=True,
    )

    with st.form("login_form"):
        st.markdown(_MAIL_ICON_ROW, unsafe_allow_html=True)
        username = st.text_input("Username", placeholder="Enter your username", label_visibility="collapsed")
        st.markdown(_LOCK_ICON_ROW, unsafe_allow_html=True)
        password = st.text_input("Password", type="password", placeholder="Enter your password", label_visibility="collapsed")
        submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

    st.markdown("</div>", unsafe_allow_html=True)

    if submitted:
        try:
            resp = requests.post(
                LOGIN_URL,
                data    = {"username": username, "password": password},
                timeout = 8,
            )
            if resp.status_code == 200:
                data = resp.json()
                st.session_state["access_token"]     = data["access_token"]
                st.session_state["refresh_token"]    = data["refresh_token"]
                st.session_state["username"]         = username
                st.session_state["token_expires_at"] = (
                    datetime.utcnow() + timedelta(seconds=data.get("expires_in", 3600))
                )
                st.rerun()
            else:
                st.error("Incorrect username or password.")
        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to the API server — make sure it is running on port 8000.")

    st.stop()


# ── Guard: show login screen if not authenticated ─────────────
if "access_token" not in st.session_state:
    if st.session_state.pop("_session_expired", False):
        st.error("Session expired. Please log in again.")
    _login_screen()

HEADERS = _auth_headers()

# ── Sensor definitions ────────────────────────────────────────
SENSORS = {
    "sensor_1":  {"min":  0.0, "max": 100.0, "default":  50.0, "label": "Temperature",  "unit": "°C",   "tag": "TEMP"},
    "sensor_2":  {"min":  0.0, "max": 300.0, "default": 150.0, "label": "Pressure",     "unit": "bar",  "tag": "PRES"},
    "sensor_3":  {"min":  0.0, "max": 100.0, "default":  50.0, "label": "Humidity",     "unit": "%",    "tag": "HUMD"},
    "sensor_4":  {"min":  0.0, "max": 500.0, "default": 250.0, "label": "RPM",          "unit": "rpm",  "tag": "RPM"},
    "sensor_5":  {"min":  0.0, "max": 100.0, "default":  50.0, "label": "Voltage",      "unit": "V",    "tag": "VOLT"},
    "sensor_6":  {"min":  0.0, "max": 100.0, "default":  50.0, "label": "Current",      "unit": "A",    "tag": "CURR"},
    "sensor_7":  {"min":-10.0, "max":  50.0, "default":  20.0, "label": "Ambient",      "unit": "°C",   "tag": "AMBT"},
    "sensor_8":  {"min":  0.0, "max": 200.0, "default": 100.0, "label": "Frequency",    "unit": "Hz",   "tag": "FREQ"},
    "sensor_9":  {"min":  0.0, "max": 100.0, "default":  50.0, "label": "Pressure 2",   "unit": "kPa",  "tag": "PRS2"},
    "sensor_10": {"min":  0.0, "max": 100.0, "default":  50.0, "label": "Vibration",    "unit": "mm/s", "tag": "VIB"},
}

# Groups the 10-slider control panel into scannable clusters instead of one
# flat list — purely a left-panel presentation grouping, doesn't touch the
# sensor_N keys the backend/model expect.
SENSOR_GROUPS = [
    ("Thermal & Pressure", ["sensor_1", "sensor_2", "sensor_9"]),
    ("Electrical",         ["sensor_5", "sensor_6", "sensor_8"]),
    ("Mechanical",         ["sensor_4", "sensor_10"]),
    ("Environment",        ["sensor_3", "sensor_7"]),
]


def _sync_slider_from_num(sid: str) -> None:
    st.session_state[sid] = st.session_state[f"{sid}_num"]


def _sync_num_from_slider(sid: str) -> None:
    st.session_state[f"{sid}_num"] = st.session_state[sid]

# ── Semantic colors — fixed across all themes ─────────────────
_BLU = "#0071e3"          # Apple blue — action accent
_GRN = "#30d158"          # Apple green — healthy / normal
_RED = "#ff3b30"          # Apple red   — failure / danger
_ORG = "#ff9500"          # Apple orange — warning
# Visual tokens are set after set_page_config (theme-aware)
_T1 = _T2 = _T3 = _BDR = _BDR2 = _SRF = _SRF2 = ""  # populated below

SEVERITY = {
    "HIGH":   {"c": _RED, "label": "Critical Failure", "bg": "rgba(255,59,48,0.09)",  "bd": "rgba(255,59,48,0.22)"},
    "MEDIUM": {"c": _ORG, "label": "Warning",          "bg": "rgba(255,149,0,0.09)",  "bd": "rgba(255,149,0,0.22)"},
    "LOW":    {"c": _GRN, "label": "Advisory",         "bg": "rgba(48,209,88,0.09)",  "bd": "rgba(48,209,88,0.22)"},
    "NONE":   {"c": _BLU, "label": "Nominal",          "bg": "rgba(0,113,227,0.09)",  "bd": "rgba(0,113,227,0.22)"},
}

PRIO_C = {"CRITICAL": _RED, "HIGH": _ORG, "MEDIUM": _BLU, "LOW": _GRN}

# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════════

st.set_page_config(
    page_title            = "NABDH · AI Maintenance",
    page_icon             = "◈",
    layout                = "wide",
    initial_sidebar_state = "collapsed",
)

# ═══════════════════════════════════════════════════════════════
# THEME — detect & set visual tokens
# ═══════════════════════════════════════════════════════════════

if "theme" not in st.session_state:
    st.session_state["theme"] = "dark"
_THEME = st.session_state["theme"]

if _THEME == "light":
    _BG   = "#f5f5f7"
    _T1   = "#1d1d1f"
    _T2   = "#6e6e73"
    _T3   = "#aeaeb2"
    _BDR  = "rgba(0,0,0,0.08)"
    _BDR2 = "rgba(0,0,0,0.14)"
    _SRF  = "rgba(255,255,255,0.80)"
    _SRF2 = "rgba(255,255,255,0.95)"
    _SCR  = "#c7c7cc"
else:
    _BG   = "#000000"
    _T1   = "#f5f5f7"
    _T2   = "#86868b"
    _T3   = "#48484a"
    _BDR  = "rgba(255,255,255,0.08)"
    _BDR2 = "rgba(255,255,255,0.14)"
    _SRF  = "rgba(255,255,255,0.04)"
    _SRF2 = "rgba(255,255,255,0.07)"
    _SCR  = "#2c2c2e"

# ═══════════════════════════════════════════════════════════════
# GLOBAL CSS — Apple × Mercedes Luxury
# ═══════════════════════════════════════════════════════════════

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:ital,opsz,wght@0,14..32,300;0,14..32,400;0,14..32,500;0,14..32,600;0,14..32,700;1,14..32,300&family=JetBrains+Mono:wght@400;500;700&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, .stApp {
  background: #000 !important;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif !important;
  color: #f5f5f7 !important;
  -webkit-font-smoothing: antialiased !important;
  -moz-osx-font-smoothing: grayscale !important;
}

.block-container {
  padding: 1rem 2.5rem 6rem !important;
  max-width: 1440px !important;
}

/* Hide all Streamlit chrome */
#MainMenu, footer, header               { visibility: hidden !important; }
[data-testid="collapsedControl"]        { display: none !important; }
[data-testid="stSidebarCollapseButton"] { display: none !important; }
section[data-testid="stSidebar"]        { display: none !important; }

/* ── SIDEBAR ── */
section[data-testid="stSidebar"] {
  background: #080808 !important;
  border-right: 1px solid rgba(255,255,255,0.06) !important;
}
section[data-testid="stSidebar"] label {
  font-family: 'Inter', sans-serif !important;
  font-size: 11px !important;
  font-weight: 400 !important;
  color: #86868b !important;
  letter-spacing: 0 !important;
}
section[data-testid="stSidebar"] .stMarkdown p {
  font-family: 'Inter', sans-serif !important;
  font-size: 11px !important;
  color: #48484a !important;
}

/* ── SLIDER ── */
[data-testid="stSlider"] [role="slider"] {
  background: #f5f5f7 !important;
  border: 2px solid #f5f5f7 !important;
  box-shadow: 0 0 0 3px rgba(255,255,255,0.08) !important;
}
[data-testid="stSlider"] > div > div > div:first-child {
  background: rgba(255,255,255,0.1) !important;
}
[data-testid="stSlider"] [data-testid="stSliderThumb"] {
  background: #f5f5f7 !important;
}
[data-testid="stSlider"] span,
[data-testid="stSlider"] p {
  color: #a1a1a6 !important;
  font-family: 'Inter', sans-serif !important;
  font-size: 12px !important;
}

/* ── WIDGET LABELS (slider/checkbox titles — Streamlit's own text,
   not covered by the .stCheckbox/.stSlider rules above, which is what
   made these unreadable in light mode: they kept this dark-mode color
   even after switching themes) ── */
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] span,
[data-testid="stWidgetLabel"] div {
  color: #c7c7cc !important;
  font-family: 'Inter', sans-serif !important;
  font-size: 13px !important;
}
[data-testid="stCheckbox"] label,
[data-testid="stCheckbox"] p,
[data-testid="stCheckbox"] span {
  color: #c7c7cc !important;
  font-family: 'Inter', sans-serif !important;
  font-size: 13px !important;
}

/* ── SENSOR CONTROL ROWS — compact label + value box + reset, scoped to
   the sticky first column only (other sliders elsewhere keep tick labels) ── */
[data-testid="column"]:first-child [data-testid="stTickBarMin"],
[data-testid="column"]:first-child [data-testid="stTickBarMax"] {
  display: none !important;
}
/* Force every wrapper level transparent first — Streamlit's own native
   theme (independent of this app's light/dark toggle) puts a dark
   background on one of these ancestor divs; which exact one carries it
   isn't reliably documented across versions, so neutralize them all and
   let only the input's own background (set below, per-theme) show. */
[data-testid="column"]:first-child [data-testid="stNumberInput"],
[data-testid="column"]:first-child [data-testid="stNumberInput"] > div,
[data-testid="column"]:first-child [data-testid="stNumberInput"] > div > div,
[data-testid="column"]:first-child [data-testid="stNumberInput"] [data-baseweb="base-input"],
[data-testid="column"]:first-child [data-testid="stNumberInput"] [data-baseweb="input"],
[data-testid="column"]:first-child [data-testid="stNumberInputContainer"] {
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}
[data-testid="column"]:first-child [data-testid="stNumberInput"] input {
  background: rgba(255,255,255,0.06) !important;
  border: 1px solid rgba(255,255,255,0.10) !important;
  color: #f5f5f7 !important;
  border-radius: 8px !important;
  height: 28px !important;
  font-size: 12px !important;
  font-family: 'JetBrains Mono', monospace !important;
  text-align: center !important;
  padding: 0 4px !important;
}
[data-testid="column"]:first-child [data-testid="stNumberInput"] button {
  display: none !important; /* hide the +/- steppers for a compact box */
}
[data-testid="column"]:first-child [data-testid="stHorizontalBlock"] [data-testid="column"]:last-child button {
  height: 28px !important;
  width: 28px !important;
  min-width: 28px !important;
  padding: 0 !important;
  border-radius: 8px !important;
  border-bottom: none !important;
  background: rgba(255,255,255,0.05) !important;
}
[data-testid="column"]:first-child [data-testid="stHorizontalBlock"] [data-testid="column"]:last-child button:hover {
  background: rgba(255,255,255,0.1) !important;
}
.reset-btn-spacer {
  /* Pushes the reset button down past the number_input's own label row,
     so it lines up with the input box, not the label text above it. */
  height: 29px;
}

/* ── LAYOUT — sticky control panel ── */
[data-testid="stHorizontalBlock"] { align-items: flex-start !important; }
[data-testid="column"]:first-child {
  position: sticky !important;
  top: 1rem !important;
  align-self: flex-start !important;
  max-height: calc(100vh - 2rem) !important;
  overflow-y: auto !important;
  scrollbar-width: none !important;
}
[data-testid="column"]:first-child::-webkit-scrollbar { display: none !important; }

/* ── BUTTONS — PRIMARY (blue pill) ── */
button[kind="primary"],
[data-testid="stBaseButton-primary"] {
  background: #0071e3 !important;
  color: #fff !important;
  border: none !important;
  border-radius: 980px !important;
  font-family: 'Inter', sans-serif !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  letter-spacing: -0.1px !important;
  padding: 11px 22px !important;
  transition: background 0.18s ease, transform 0.1s ease !important;
  width: 100% !important;
  box-shadow: 0 1px 6px rgba(0,113,227,0.28) !important;
}
button[kind="primary"]:hover,
[data-testid="stBaseButton-primary"]:hover {
  background: #0077ed !important;
  box-shadow: 0 2px 12px rgba(0,113,227,0.40) !important;
}
button[kind="primary"]:active,
[data-testid="stBaseButton-primary"]:active {
  background: #006bce !important;
  transform: scale(0.97) !important;
  box-shadow: none !important;
}

/* ── BUTTONS — SECONDARY (Apple-style nav list) ── */
button[kind="secondary"],
[data-testid="stBaseButton-secondary"] {
  background: transparent !important;
  color: #86868b !important;
  border: none !important;
  border-bottom: 1px solid rgba(255,255,255,0.05) !important;
  border-radius: 0 !important;
  font-family: 'Inter', sans-serif !important;
  font-size: 12px !important;
  font-weight: 400 !important;
  letter-spacing: 0 !important;
  padding: 13px 2px !important;
  text-align: left !important;
  transition: color 0.15s ease !important;
  width: 100% !important;
  box-shadow: none !important;
  justify-content: flex-start !important;
}
button[kind="secondary"] p,
[data-testid="stBaseButton-secondary"] p {
  text-align: left !important;
}
button[kind="secondary"]:hover,
[data-testid="stBaseButton-secondary"]:hover {
  background: transparent !important;
  color: #f5f5f7 !important;
  box-shadow: none !important;
}
button[kind="secondary"]:active,
[data-testid="stBaseButton-secondary"]:active {
  background: transparent !important;
  color: #f5f5f7 !important;
}

/* ── SELECT SLIDER ── */
[data-testid="stSlider"] [data-testid="stTickBarMin"],
[data-testid="stSlider"] [data-testid="stTickBarMax"] {
  color: #98989d !important;
  font-size: 12px !important;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}

/* ── TABS ── */
.stTabs [data-baseweb="tab-list"] {
  background: transparent !important;
  border-bottom: 1px solid rgba(255,255,255,0.07) !important;
  gap: 0 !important;
  padding: 0 !important;
}
.stTabs [data-baseweb="tab"] {
  background: transparent !important;
  border: none !important;
  border-bottom: 1.5px solid transparent !important;
  color: #86868b !important;
  font-family: 'Inter', sans-serif !important;
  font-size: 12px !important;
  font-weight: 500 !important;
  letter-spacing: 0 !important;
  padding: 14px 22px !important;
  border-radius: 0 !important;
  transition: color 0.15s ease !important;
}
.stTabs [data-baseweb="tab"]:hover    { color: #d1d1d6 !important; }
.stTabs [aria-selected="true"]         { color: #f5f5f7 !important; border-bottom: 1.5px solid #f5f5f7 !important; }
.stTabs [data-baseweb="tab-panel"]     { padding: 2.2rem 0 0 !important; }
.stTabs [data-baseweb="tab-highlight"] { display: none !important; }

/* ── MISC ── */
.stAlert  { border-radius: 14px !important; }
.stJson   { background: #0d0d0d !important; border-radius: 14px !important; }
.element-container .stDataFrame { background: transparent !important; }

/* ── DATAFRAME — wrap tables in the same rounded/bordered card language
   as everything else, so History/Drift tables don't look like a bare
   Streamlit default dropped into a otherwise fully custom UI ── */
[data-testid="stDataFrame"] {
  border: 1px solid rgba(255,255,255,0.08) !important;
  border-radius: 14px !important;
  overflow: hidden !important;
}

/* ── SCROLLBAR ── */
::-webkit-scrollbar       { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #2c2c2e; border-radius: 99px; }

/* ── EXPANDER ── */
.streamlit-expanderHeader {
  background: rgba(255,255,255,0.04) !important;
  border: 1px solid rgba(255,255,255,0.08) !important;
  border-radius: 12px !important;
  color: #86868b !important;
  font-family: 'Inter', sans-serif !important;
  font-size: 12px !important;
}

/* ── ANIMATIONS ── */
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(5px); }
  to   { opacity: 1; transform: translateY(0);   }
}
@keyframes liveDot {
  0%, 100% { opacity: 1;   }
  50%       { opacity: 0.2; }
}
.fade-in { animation: fadeIn 0.35s cubic-bezier(0.25,0.46,0.45,0.94) both; }
</style>
""", unsafe_allow_html=True)

# ── Light mode CSS overrides ──────────────────────────────────
if _THEME == "light":
    st.markdown("""
<style>
html, body, .stApp,
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
section.main,
.main > .block-container {
  background: #f5f5f7 !important;
  color: #1d1d1f !important;
}
.block-container { background: #f5f5f7 !important; }

.stTabs [data-baseweb="tab-list"]  { border-bottom-color: rgba(0,0,0,0.08) !important; }
.stTabs [data-baseweb="tab"]       { color: #6e6e73 !important; }
.stTabs [aria-selected="true"]     { color: #1d1d1f !important; border-bottom-color: #1d1d1f !important; }
.stTabs [data-baseweb="tab-panel"] { background: #f5f5f7 !important; }

[data-testid="stCheckbox"] label,
[data-testid="stCheckbox"] p,
[data-testid="stCheckbox"] span { color: #48484a !important; font-size: 13px !important; }
[data-testid="stSlider"] span,
[data-testid="stSlider"] p     { color: #48484a !important; font-size: 12px !important; }
[data-testid="stWidgetLabel"],
[data-testid="stWidgetLabel"] p,
[data-testid="stWidgetLabel"] span,
[data-testid="stWidgetLabel"] div { color: #48484a !important; font-size: 13px !important; }
[data-testid="stSlider"] [data-testid="stTickBarMin"],
[data-testid="stSlider"] [data-testid="stTickBarMax"] {
  color: #6e6e73 !important;
  font-size: 12px !important;
  background: transparent !important;
  border: none !important;
  box-shadow: none !important;
}
[data-testid="stSlider"] [role="slider"] {
  background: #1d1d1f !important;
  border-color: #1d1d1f !important;
}
[data-testid="stSlider"] > div > div > div:first-child {
  background: rgba(0,0,0,0.12) !important;
}

/* .stApp-qualified so this reliably outranks the dark rule above on
   specificity, instead of depending on which <style> block Streamlit
   happens to place later in the DOM on a given rerun (unreliable — this
   is what caused the light-mode box to stay dark before). */
.stApp [data-testid="column"]:first-child [data-testid="stNumberInput"],
.stApp [data-testid="column"]:first-child [data-testid="stNumberInput"] [data-baseweb="base-input"],
.stApp [data-testid="column"]:first-child [data-testid="stNumberInput"] [data-baseweb="input"] {
  background: transparent !important;
}
.stApp [data-testid="column"]:first-child [data-testid="stNumberInput"] input {
  background: rgba(0,0,0,0.04) !important;
  border: 1px solid rgba(0,0,0,0.10) !important;
  color: #1d1d1f !important;
}
[data-testid="column"]:first-child [data-testid="stHorizontalBlock"] [data-testid="column"]:last-child button {
  background: rgba(0,0,0,0.04) !important;
}
[data-testid="column"]:first-child [data-testid="stHorizontalBlock"] [data-testid="column"]:last-child button:hover {
  background: rgba(0,0,0,0.08) !important;
}

button[kind="secondary"],
[data-testid="stBaseButton-secondary"] {
  color: #6e6e73 !important;
  border-bottom-color: rgba(0,0,0,0.08) !important;
}
button[kind="secondary"]:hover,
[data-testid="stBaseButton-secondary"]:hover { color: #1d1d1f !important; }

.streamlit-expanderHeader {
  background: rgba(0,0,0,0.03) !important;
  border-color: rgba(0,0,0,0.08) !important;
  color: #6e6e73 !important;
}
.stJson   { background: #ffffff !important; }
.stAlert  { background: rgba(0,0,0,0.04) !important; }
[data-testid="stDataFrame"] { border-color: rgba(0,0,0,0.10) !important; }
::-webkit-scrollbar-thumb { background: #c7c7cc !important; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
# PRIMITIVES
# ═══════════════════════════════════════════════════════════════

def _ring(pct: float, color: str, size: int = 64) -> str:
    """Apple Watch–style thin SVG arc ring."""
    r    = (size - 8) // 2
    cx   = cy = size // 2
    circ = 2 * math.pi * r
    dash = (max(0, min(100, pct)) / 100) * circ
    gap  = circ - dash
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" '
        f'style="display:block;margin:0 auto 10px;">'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="{_BDR}" stroke-width="2.5"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="{color}" stroke-width="2.5" stroke-linecap="round" '
        f'stroke-dasharray="{dash:.2f} {gap:.2f}" '
        f'transform="rotate(-90 {cx} {cy})"/>'
        f'<text x="{cx}" y="{cy+1}" text-anchor="middle" dominant-baseline="middle" '
        f'font-family="JetBrains Mono,monospace" font-size="11" font-weight="700" '
        f'fill="{color}">{pct:.0f}</text>'
        f'</svg>'
    )


def _pill(text: str, color: str) -> str:
    """Compact status pill — Apple badge style."""
    return (
        f'<span style="display:inline-flex;align-items:center;'
        f'background:rgba({_rgb(color)},0.12);color:{color};'
        f'font:600 10px/1 Inter,sans-serif;letter-spacing:0.3px;'
        f'padding:3px 10px;border-radius:980px;">{text}</span>'
    )


def _rgb(hex_color: str) -> str:
    """Convert #rrggbb to 'r,g,b' string for rgba()."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    return f"{r},{g},{b}"


def _sep() -> None:
    st.markdown(
        f'<div style="border-top:1px solid {_BDR};margin:28px 0;"></div>',
        unsafe_allow_html=True,
    )


def _label(text: str) -> None:
    st.markdown(
        f'<div style="font:500 11px/1 Inter,sans-serif;color:{_T2};'
        f'letter-spacing:0.3px;text-transform:uppercase;'
        f'padding-bottom:16px;border-bottom:1px solid {_BDR};'
        f'margin-bottom:20px;">{text}</div>',
        unsafe_allow_html=True,
    )


_ALERT_KIND = {
    "error":   {"c": _RED, "label": "Error"},
    "warning": {"c": _ORG, "label": "Warning"},
    "success": {"c": _GRN, "label": "Success"},
    "info":    {"c": _BLU, "label": "Info"},
}


def _alert(kind: str, message: str) -> None:
    """Theme-matched replacement for st.error/warning/success/info — the
    native Streamlit alerts render a fixed light-red/etc. box that clashes
    with this app's dark/glass surfaces in dark mode."""
    k = _ALERT_KIND.get(kind, _ALERT_KIND["info"])
    st.markdown(
        f'<div class="fade-in" style="display:flex;align-items:center;gap:12px;'
        f'background:rgba({_rgb(k["c"])},0.09);border:1px solid rgba({_rgb(k["c"])},0.25);'
        f'border-radius:14px;padding:14px 20px;margin:6px 0 20px;">'
        f'{_pill(k["label"].upper(), k["c"])}'
        f'<span style="font:400 13px/1.5 Inter,sans-serif;color:{k["c"]};">{message}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _empty_state(icon: str, hint: str, action: str = "") -> None:
    """Shared empty/idle placeholder for every tab — mirrors the Prediction
    tab's own idle screen so all seven tabs feel like one interface instead
    of the first being 'designed' and the rest left as bare text."""
    action_html = (
        f'<div style="font:400 13px/1 Inter,sans-serif;color:{_T3};margin-top:8px;">'
        f'<span style="color:{_BLU};font-weight:500;">{action}</span></div>'
        if action else ""
    )
    st.markdown(
        f'<div class="fade-in" style="text-align:center;padding:60px 0 40px;">'
        f'<div style="font:300 48px/1 Inter,sans-serif;color:{_BDR};'
        f'letter-spacing:-2px;margin-bottom:20px;">{icon}</div>'
        f'<div style="font:400 13px/1 Inter,sans-serif;color:{_T3};margin-bottom:8px;">{hint}</div>'
        f'{action_html}</div>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════
# COMPONENTS
# ═══════════════════════════════════════════════════════════════

def render_header() -> None:
    now = datetime.now().strftime("%B %d, %Y  %H:%M")
    st.markdown(
        f'<div class="fade-in" style="display:flex;align-items:center;justify-content:space-between;'
        f'padding:32px 0 26px;border-bottom:1px solid {_BDR};margin-bottom:0;">'
        f'<div>'
        f'<div style="font:700 26px/1 Inter,sans-serif;color:{_T1};letter-spacing:-0.6px;margin-bottom:6px;">'
        f'NABDH<span style="font-weight:300;color:{_T2};"> · AI Maintenance</span></div>'
        f'<div style="font:400 12px/1 Inter,sans-serif;color:{_T3};">Predictive & Prescriptive Industrial AI Platform</div>'
        f'</div>'
        f'<div style="display:flex;align-items:center;gap:18px;">'
        f'<div style="display:flex;align-items:center;gap:7px;">'
        f'<div style="width:6px;height:6px;border-radius:50%;background:{_GRN};'
        f'animation:liveDot 2s ease-in-out infinite;flex-shrink:0;"></div>'
        f'<span style="font:500 12px/1 Inter,sans-serif;color:{_GRN};">Live</span>'
        f'</div>'
        f'<div style="width:1px;height:16px;background:{_BDR2};"></div>'
        f'<span style="font:400 12px/1 Inter,sans-serif;color:{_T3};">{now}</span>'
        f'<div style="background:{_SRF};border:1px solid {_BDR};'
        f'border-radius:20px;padding:7px 16px;">'
        f'<span style="font:500 11px/1 Inter,sans-serif;color:{_T2};">10 Sensors Active</span>'
        f'</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def render_hero() -> None:
    """SaaS-landing-style banner: badge pill + big gradient headline +
    subtitle, over a soft scoped glow. No fake nav/CTA/screenshot — those
    don't map to an already-authenticated internal tool."""
    grad_from = "#f5f5f7" if _THEME == "dark" else "#1d1d1f"
    grad_to   = "rgba(0,113,227,0.65)"
    st.markdown(
        f'<div class="fade-in" style="position:relative;overflow:hidden;'
        f'padding:40px 0 36px;text-align:center;">'
        f'<div style="position:absolute;top:-60%;left:50%;transform:translateX(-50%);'
        f'width:70%;height:220px;border-radius:50%;'
        f'background:radial-gradient(ellipse at center, rgba(0,113,227,0.22), transparent 70%);'
        f'filter:blur(50px);pointer-events:none;z-index:0;"></div>'

        f'<div style="position:relative;z-index:1;">'
        f'<div style="display:inline-flex;align-items:center;gap:8px;padding:7px 16px;'
        f'border-radius:999px;border:1px solid {_BDR};background:{_SRF};margin-bottom:22px;">'
        f'<div style="width:6px;height:6px;border-radius:50%;background:{_GRN};'
        f'animation:liveDot 2s ease-in-out infinite;flex-shrink:0;"></div>'
        f'<span style="font:500 11px/1 Inter,sans-serif;color:{_T2};">'
        f'v{APP_VERSION} — Equipment Timeline is here</span>'
        f'</div>'

        f'<div style="font:600 40px/1.15 Inter,sans-serif;letter-spacing:-1.2px;'
        f'background:linear-gradient(180deg, {grad_from}, {grad_to});'
        f'-webkit-background-clip:text;-webkit-text-fill-color:transparent;'
        f'background-clip:text;margin-bottom:14px;">'
        f'Know about failures<br/>before they happen</div>'

        f'<div style="font:400 14px/1.5 Inter,sans-serif;color:{_T2};'
        f'max-width:520px;margin:0 auto;">'
        f'Predictive &amp; prescriptive maintenance, root-cause analysis, and live '
        f'drift monitoring — for every piece of equipment you run.</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def kpi(label: str, value: str, color: str = "", sub: str = "") -> None:
    val_color = color or _T1
    sub_block = (
        f'<div style="font:400 11px/1 Inter,sans-serif;color:{_T3};margin-top:8px;">{sub}</div>'
        if sub else ""
    )
    st.markdown(
        f'<div style="background:{_SRF};border:1px solid {_BDR};border-radius:18px;'
        f'padding:24px 22px;height:100%;">'
        f'<div style="font:500 10px/1 Inter,sans-serif;color:{_T2};'
        f'letter-spacing:0.4px;text-transform:uppercase;margin-bottom:14px;">{label}</div>'
        f'<div style="font:700 34px/1 JetBrains Mono,monospace;color:{val_color};'
        f'letter-spacing:-1px;">{value}</div>'
        f'{sub_block}</div>',
        unsafe_allow_html=True,
    )


def render_banner(severity: str, recommendation: str, confidence: float) -> None:
    c   = SEVERITY.get(severity, SEVERITY["NONE"])
    pct = confidence * 100
    st.markdown(
        f'<div class="fade-in" style="background:{c["bg"]};border:1px solid {c["bd"]};'
        f'border-radius:18px;padding:24px 28px;margin-bottom:28px;">'
        f'<div style="display:flex;align-items:center;gap:16px;margin-bottom:14px;">'
        f'{_pill(c["label"].upper(), c["c"])}'
        f'<div style="flex:1;font:400 14px/1.5 Inter,sans-serif;color:{c["c"]};'
        f'letter-spacing:-0.1px;">{recommendation}</div>'
        f'<div style="text-align:right;flex-shrink:0;">'
        f'<div style="font:700 40px/1 JetBrains Mono,monospace;color:{c["c"]};'
        f'letter-spacing:-2px;">{pct:.1f}<span style="font-size:18px;">%</span></div>'
        f'<div style="font:400 10px/1 Inter,sans-serif;color:{c["c"]};'
        f'opacity:0.5;letter-spacing:0.5px;text-transform:uppercase;margin-top:4px;">Confidence</div>'
        f'</div></div>'
        f'<div style="background:rgba(0,0,0,0.3);border-radius:4px;height:2px;overflow:hidden;">'
        f'<div style="width:{pct:.1f}%;height:100%;background:{c["c"]};'
        f'border-radius:4px;transition:width 0.4s ease;"></div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def render_sensor_grid(sensor_vals: dict, anomalies: list = None) -> None:
    if anomalies is None:
        anomalies = []
    cols = st.columns(5)
    for idx, (sid, cfg) in enumerate(SENSORS.items()):
        val        = sensor_vals.get(sid)
        is_anomaly = sid in anomalies
        is_missing = val is None
        span       = cfg["max"] - cfg["min"] or 1

        if is_missing:
            pct, val_txt, ring_c, bdr = 0.0, "—", _T3, _BDR
        elif is_anomaly:
            pct     = max(0, min(100, (val - cfg["min"]) / span * 100))
            val_txt = f"{val:.1f}"
            ring_c  = _RED
            bdr     = "rgba(255,59,48,0.3)"
        else:
            pct     = max(0, min(100, (val - cfg["min"]) / span * 100))
            val_txt = f"{val:.1f}"
            ring_c  = _GRN if pct < 75 else _ORG
            bdr     = _BDR

        anom_tag = (
            f'<div style="font:600 9px/1 Inter,sans-serif;color:{_RED};'
            f'letter-spacing:0.4px;text-transform:uppercase;margin-top:8px;">⚠ Anomaly</div>'
            if is_anomaly else ""
        )

        with cols[idx % 5]:
            st.markdown(
                f'<div style="background:{_SRF};border:1px solid {bdr};'
                f'border-radius:16px;padding:20px 14px 16px;margin-bottom:8px;text-align:center;">'
                f'<div style="font:600 9px/1 Inter,sans-serif;color:{_T3};'
                f'letter-spacing:0.6px;text-transform:uppercase;margin-bottom:12px;">{cfg["tag"]}</div>'
                f'{_ring(pct, ring_c)}'
                f'<div style="font:700 18px/1 JetBrains Mono,monospace;color:{_T1};'
                f'letter-spacing:-0.5px;margin-bottom:4px;">{val_txt}</div>'
                f'<div style="font:400 11px/1 Inter,sans-serif;color:{_T2};">{cfg["unit"]}</div>'
                f'<div style="font:400 10px/1 Inter,sans-serif;color:{_T3};margin-top:3px;">{cfg["label"]}</div>'
                f'{anom_tag}</div>',
                unsafe_allow_html=True,
            )


def render_factors(factors: list) -> None:
    for i, f in enumerate(factors):
        impact = f.get("impact", 0)
        color  = _RED if impact > 0 else _BLU
        bar_w  = min(abs(impact) * 300, 100)
        lbl    = "Raises Risk" if impact > 0 else "Lowers Risk"
        st.markdown(
            f'<div style="padding:14px 0;border-bottom:1px solid {_BDR};">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">'
            f'<div style="display:flex;align-items:center;gap:10px;">'
            f'<div style="width:20px;height:20px;background:{_SRF};'
            f'border-radius:6px;display:flex;align-items:center;justify-content:center;'
            f'font:600 9px/1 Inter,sans-serif;color:{_T3};flex-shrink:0;">{i+1}</div>'
            f'<div style="font:600 12px/1 Inter,sans-serif;color:{_T1};'
            f'letter-spacing:-0.1px;">{f.get("feature","—").replace("_"," ").title()}</div>'
            f'</div>'
            f'<div style="font:700 13px/1 JetBrains Mono,monospace;color:{color};">{impact:+.4f}</div>'
            f'</div>'
            f'<div style="background:{_SRF2};border-radius:2px;height:1.5px;overflow:hidden;">'
            f'<div style="width:{bar_w:.1f}%;height:100%;background:{color};border-radius:2px;'
            f'transition:width 0.4s ease;"></div>'
            f'</div>'
            f'<div style="font:400 10px/1 Inter,sans-serif;color:{color};opacity:0.6;'
            f'margin-top:6px;letter-spacing:0.3px;">{lbl}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def render_gauge(confidence: float, prediction: int) -> None:
    color = _RED if prediction == 1 else _GRN
    fig   = go.Figure(go.Indicator(
        mode   = "gauge+number",
        value  = confidence * 100,
        number = dict(
            suffix   = "%",
            font     = dict(family="JetBrains Mono", color=color, size=38),
            valueformat=".1f",
        ),
        gauge = dict(
            axis      = dict(
                range=[0,100], tickwidth=0,
                tickcolor="rgba(0,0,0,0)",
                tickfont=dict(color="rgba(0,0,0,0)", size=1),
            ),
            bar       = dict(color=color, thickness=0.10),
            bgcolor   = "rgba(0,0,0,0)",
            borderwidth=0,
            steps=[dict(range=[0,100], color=_SRF)],
            threshold = dict(
                line=dict(color=_ORG, width=1),
                thickness=0.55, value=70,
            ),
        ),
    ))
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter", color=_T2),
        height=185, margin=dict(l=20,r=20,t=16,b=0),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False}, key="gauge_chart")


def render_shap(shap_values: dict) -> None:
    if not shap_values:
        _alert("info", "No SHAP data available.")
        return
    df      = pd.DataFrame(list(shap_values.items()), columns=["Feature","SHAP"])
    df      = df.sort_values("SHAP", key=abs, ascending=True)
    colors  = [_RED if v > 0 else _BLU for v in df["SHAP"]]
    max_abs = df["SHAP"].abs().max() or 1

    fig = go.Figure(go.Bar(
        x=df["SHAP"], y=df["Feature"].str.replace("_"," ").str.title(),
        orientation="h",
        marker=dict(color=colors, line=dict(width=0)),
        hovertemplate="<b>%{y}</b>  %{x:+.5f}<extra></extra>",
    ))
    fig.add_vline(x=0, line_color=_BDR, line_width=1)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor ="rgba(0,0,0,0)",
        font=dict(family="Inter", color=_T2, size=10),
        xaxis=dict(
            range=[-max_abs*1.25, max_abs*1.25],
            gridcolor=_BDR,
            zerolinecolor="rgba(0,0,0,0)",
            tickfont=dict(color=_T3, size=9),
            title=dict(
                text="← Lowers Risk   ·   SHAP   ·   Raises Risk →",
                font=dict(color=_T3, size=9),
            ),
        ),
        yaxis=dict(
            gridcolor="rgba(0,0,0,0)",
            tickfont=dict(color=_T1, size=11),
        ),
        height=300, margin=dict(l=8,r=8,t=8,b=40),
        bargap=0.38,
        hoverlabel=dict(
            bgcolor="#111" if _THEME=="dark" else "#fff",
            bordercolor=_BDR,
            font=dict(family="Inter", color=_T1, size=11),
        ),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar":False}, key="shap_chart")


def render_health_ring(score: float, failure_mode: str) -> None:
    if score >= 80:
        hc, hs = _GRN, "Healthy"
    elif score >= 60:
        hc, hs = _ORG, "Degraded"
    else:
        hc, hs = _RED, "Critical"
    big_ring = _ring(score, hc, size=88)
    st.markdown(
        f'<div style="background:{_SRF};border:1px solid {_BDR};border-radius:18px;'
        f'padding:24px 18px;text-align:center;">'
        f'<div style="font:500 10px/1 Inter,sans-serif;color:{_T2};'
        f'letter-spacing:0.4px;text-transform:uppercase;margin-bottom:18px;">Asset Health</div>'
        f'{big_ring}'
        f'<div style="font:600 13px/1 Inter,sans-serif;color:{hc};margin-bottom:8px;">{hs}</div>'
        f'<div style="display:inline-block;background:{_SRF2};'
        f'border-radius:980px;padding:4px 12px;">'
        f'<span style="font:500 10px/1 Inter,sans-serif;color:{_T2};">{failure_mode}</span>'
        f'</div></div>',
        unsafe_allow_html=True,
    )


def render_prescriptive(actions: list, priority: str) -> None:
    if not actions:
        return
    pc = PRIO_C.get(priority, _BLU)
    _label(f"Prescriptive Actions   {_pill(priority, pc)}")
    for i, act in enumerate(actions):
        ac   = PRIO_C.get(act.get("priority","LOW"), _BLU)
        last = i == len(actions) - 1
        bdr  = "" if last else f"border-bottom:1px solid {_BDR};"
        st.markdown(
            f'<div style="display:flex;align-items:flex-start;gap:14px;'
            f'padding:14px 0;{bdr}">'
            f'<div style="min-width:24px;height:24px;border-radius:8px;'
            f'background:rgba({_rgb(ac)},0.12);display:flex;align-items:center;'
            f'justify-content:center;margin-top:1px;">'
            f'<span style="font:700 10px/1 Inter,sans-serif;color:{ac};">{i+1}</span>'
            f'</div>'
            f'<div style="flex:1;">'
            f'<div style="font:400 13px/1.5 Inter,sans-serif;color:{_T1};'
            f'margin-bottom:5px;">{act.get("action","—")}</div>'
            f'<div style="font:400 10px/1 Inter,sans-serif;color:{_T2};">'
            f'{act.get("sensor","—").upper()} · {act.get("system","—").title()}'
            f'</div></div>'
            f'<div>{_pill(act.get("priority","—"), ac)}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )


def render_rca(rca: dict) -> None:
    if not rca or not rca.get("causal_chain"):
        return
    _label("Root Cause Analysis")
    primary = rca.get("primary_cause","—")
    mode    = rca.get("failure_mode","—")
    note    = rca.get("inspection_recommendation","")
    raw_chain = rca.get("causal_chain",[])
    chain = [s.get("narrative", str(s)) if isinstance(s, dict) else str(s) for s in raw_chain]

    st.markdown(
        f'<div style="background:rgba(255,149,0,0.06);border:1px solid rgba(255,149,0,0.18);'
        f'border-radius:16px;padding:20px;margin-bottom:10px;">'
        f'<div style="font:500 10px/1 Inter,sans-serif;color:{_T2};'
        f'letter-spacing:0.4px;text-transform:uppercase;margin-bottom:10px;">Primary Cause</div>'
        f'<div style="font:600 14px/1.5 Inter,sans-serif;color:{_ORG};margin-bottom:10px;">{primary}</div>'
        f'{_pill(mode, _ORG)}'
        f'</div>',
        unsafe_allow_html=True,
    )
    if note:
        st.markdown(
            f'<div style="background:{_SRF};border:1px solid {_BDR};border-radius:14px;padding:16px;margin-bottom:10px;">'
            f'<div style="font:500 10px/1 Inter,sans-serif;color:{_T2};'
            f'letter-spacing:0.4px;text-transform:uppercase;margin-bottom:8px;">Inspection Note</div>'
            f'<div style="font:400 12px/1.6 Inter,sans-serif;color:{_T2};">{note}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    if chain:
        st.markdown(
            f'<div style="font:500 10px/1 Inter,sans-serif;color:{_T2};'
            f'letter-spacing:0.4px;text-transform:uppercase;margin-bottom:14px;">Causal Chain</div>',
            unsafe_allow_html=True,
        )
        for j, step in enumerate(chain):
            is_last = j == len(chain) - 1
            dot_c   = _RED if is_last else _T3
            conn    = (
                f'<div style="width:1px;height:14px;background:{_BDR};'
                f'margin:2px 0 2px 7px;"></div>'
                if not is_last else ""
            )
            st.markdown(
                f'<div style="display:flex;align-items:flex-start;gap:12px;">'
                f'<div style="display:flex;flex-direction:column;align-items:center;flex-shrink:0;">'
                f'<div style="width:8px;height:8px;border-radius:50%;background:{dot_c};margin-top:4px;"></div>'
                f'{conn}</div>'
                f'<div style="font:400 12px/1.6 Inter,sans-serif;color:{_T2};'
                f'padding-bottom:4px;">{step}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )


# ═══════════════════════════════════════════════════════════════
# PLOTLY CHART HELPERS
# ═══════════════════════════════════════════════════════════════

_LAY = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor ="rgba(0,0,0,0)",
    font=dict(family="Inter", color=_T2, size=10),
    margin=dict(l=8,r=8,t=28,b=8),
    hoverlabel=dict(bgcolor="#111" if _THEME=="dark" else "#fff", bordercolor=_BDR,
                    font=dict(family="Inter", color=_T1, size=11)),
)
_AX = dict(gridcolor=_BDR, zerolinecolor="rgba(0,0,0,0)",
           tickfont=dict(color=_T3, size=9))


def _conf_timeline(records: list) -> go.Figure:
    df = pd.DataFrame(records)
    if df.empty or "timestamp" not in df.columns:
        return go.Figure()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")
    mc = [_RED if p == 1 else _GRN for p in df.get("prediction", [0]*len(df))]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df["confidence"],
        mode="lines+markers",
        line=dict(color=_BLU, width=1.5),
        marker=dict(color=mc, size=5, line=dict(width=0)),
        hovertemplate="<b>%{x|%H:%M}</b><br>Confidence: %{y:.3f}<extra></extra>",
    ))
    fig.add_hline(y=0.70, line_color=_ORG, line_dash="dot", line_width=1,
                  annotation_text="Threshold", annotation_font=dict(color=_ORG, size=9))
    fig.update_layout(**_LAY, height=240,
                      xaxis={**_AX},
                      yaxis={**_AX, "range":[0,1]},
                      showlegend=False,
                      title=dict(text="Confidence Timeline",font=dict(color="#86868b",size=11),x=0))
    return fig


def _sev_donut(records: list) -> go.Figure:
    df = pd.DataFrame(records)
    if df.empty or "severity" not in df.columns:
        return go.Figure()
    counts = df["severity"].value_counts()
    cmap   = {"HIGH":_RED,"MEDIUM":_ORG,"LOW":_GRN,"NONE":_BLU}
    colors = [cmap.get(s,"#555") for s in counts.index]
    fig = go.Figure(go.Pie(
        labels=counts.index, values=counts.values, hole=0.65,
        marker=dict(colors=colors, line=dict(color="#000", width=2)),
        textfont=dict(family="Inter", size=10),
        hovertemplate="<b>%{label}</b>: %{value} (%{percent})<extra></extra>",
    ))
    fig.update_layout(**_LAY, height=230,
                      showlegend=True,
                      legend=dict(font=dict(color="#86868b",size=10),bgcolor="rgba(0,0,0,0)"),
                      title=dict(text="Severity Split",font=dict(color="#86868b",size=11),x=0))
    return fig


def _health_trend(rows: list) -> go.Figure:
    if not rows:
        return go.Figure()
    df = pd.DataFrame(rows)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")
    mc = df["health_score"].apply(lambda s: _GRN if s>=80 else _ORG if s>=60 else _RED) if "health_score" in df.columns else [_BLU]*len(df)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["timestamp"], y=df.get("health_score", df.get("confidence")),
        mode="lines+markers",
        line=dict(color=_GRN, width=1.5),
        marker=dict(color=list(mc), size=4, line=dict(width=0)),
        fill="tozeroy", fillcolor="rgba(48,209,88,0.04)",
        hovertemplate="<b>%{x|%H:%M}</b><br>%{y:.1f}<extra></extra>",
    ))
    fig.update_layout(**_LAY, height=210,
                      xaxis={**_AX},
                      yaxis={**_AX, "range":[0,100]},
                      showlegend=False,
                      title=dict(text="Asset Health Trend",font=dict(color="#86868b",size=11),x=0))
    return fig


def _mode_bar(mode_dist: list) -> go.Figure:
    if not mode_dist:
        return go.Figure()
    df = pd.DataFrame(mode_dist)
    if df.empty:
        return go.Figure()
    pal = [_RED,_ORG,_BLU,_GRN,"#bf5af2"]
    fig = go.Figure(go.Bar(
        x=df["cnt"], y=df["failure_mode"].str.replace("_"," ").str.title(),
        orientation="h",
        marker=dict(color=[pal[i % len(pal)] for i in range(len(df))], line=dict(width=0)),
        hovertemplate="<b>%{y}</b>: %{x}<extra></extra>",
    ))
    fig.update_layout(**_LAY, height=210,
                      xaxis={**_AX},
                      yaxis={**_AX},
                      title=dict(text="Failure Mode Distribution",font=dict(color="#86868b",size=11),x=0))
    return fig


# ═══════════════════════════════════════════════════════════════
# MAIN LAYOUT — left panel (controls) + right panel (content)
# ═══════════════════════════════════════════════════════════════

render_header()
render_hero()

# Top-level two-column split: controls | content
col_ctrl, col_main = st.columns([1, 4], gap="large")

# ── LEFT CONTROL PANEL ────────────────────────────────────────
with col_ctrl:
    st.markdown(
        f'<div style="background:{_SRF};border:1px solid {_BDR};'
        f'border-radius:18px;padding:20px 16px;position:sticky;top:1rem;">'
        f'<div style="font:600 13px/1 Inter,sans-serif;color:{_T1};margin-bottom:4px;">Sensor Control</div>'
        f'<div style="font:400 11px/1 Inter,sans-serif;color:{_T3};margin-bottom:18px;">'
        f'Adjust readings · run analysis</div>',
        unsafe_allow_html=True,
    )

    sensor_vals: dict = {}
    for gi, (group_name, sids) in enumerate(SENSOR_GROUPS):
        st.markdown(
            f'<div style="font:600 10px/1 Inter,sans-serif;color:{_T3};'
            f'letter-spacing:0.5px;text-transform:uppercase;'
            f'margin:{0 if gi == 0 else 14}px 0 10px;">{group_name}</div>',
            unsafe_allow_html=True,
        )
        for sid in sids:
            cfg = SENSORS[sid]
            if sid not in st.session_state:
                st.session_state[sid] = cfg["default"]
            if f"{sid}_num" not in st.session_state:
                st.session_state[f"{sid}_num"] = st.session_state[sid]

            miss = st.checkbox(f"Missing: {cfg['label']}", value=False, key=f"miss_{sid}")

            num_col, rst_col = st.columns([4, 1])
            with num_col:
                # Real (visible) Streamlit label — it handles its own spacing
                # correctly, unlike a raw HTML label placed in the sibling
                # column, which didn't line up with the input box next to it.
                st.number_input(
                    f"{cfg['label']} ({cfg['unit']})",
                    min_value=cfg["min"], max_value=cfg["max"], step=0.1,
                    key=f"{sid}_num", disabled=miss,
                    on_change=_sync_slider_from_num, args=(sid,),
                )
            with rst_col:
                st.markdown('<div class="reset-btn-spacer"></div>', unsafe_allow_html=True)
                if st.button("↺", key=f"reset_{sid}", help="Reset to default", disabled=miss):
                    st.session_state[sid] = cfg["default"]
                    st.session_state[f"{sid}_num"] = cfg["default"]
                    st.rerun()

            sensor_vals[sid] = None if miss else st.slider(
                f"{cfg['label']} ({cfg['unit']})",
                min_value=cfg["min"], max_value=cfg["max"],
                step=0.1, key=sid, label_visibility="collapsed", disabled=miss,
                on_change=_sync_num_from_slider, args=(sid,),
            )
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
    predict_btn = st.button("Run Prediction", use_container_width=True, type="primary")
    st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

    if st.button("↺  Reset Sensors", use_container_width=True, key="reset_btn", type="secondary"):
        for sid, cfg in SENSORS.items():
            st.session_state[sid] = cfg["default"]
            st.session_state[f"{sid}_num"] = cfg["default"]
            st.session_state[f"miss_{sid}"] = False
        st.rerun()

    st.markdown(
        f'<div style="margin-top:20px;margin-bottom:2px;font:500 10px/1 Inter,sans-serif;'
        f'color:{_T3};letter-spacing:0.5px;text-transform:uppercase;">Navigate</div>',
        unsafe_allow_html=True,
    )
    status_btn    = st.button("System Status",   use_container_width=True, key="sb_status",  type="secondary")
    drift_btn     = st.button("Drift Report",    use_container_width=True, key="sb_drift",   type="secondary")
    history_btn   = st.button("History",         use_container_width=True, key="sb_hist",    type="secondary")
    analytics_btn = st.button("Analytics",       use_container_width=True, key="sb_anlt",    type="secondary")
    alerts_btn    = st.button("Alerts",          use_container_width=True, key="sb_alrt",    type="secondary")
    timeline_btn  = st.button("Equipment Timeline", use_container_width=True, key="sb_tmln", type="secondary")

    st.markdown(
        f'<div style="margin-top:16px;border-top:1px solid {_BDR};padding-top:16px;">'
        f'<div style="font:500 10px/1 Inter,sans-serif;color:{_T2};'
        f'letter-spacing:0.4px;text-transform:uppercase;margin-bottom:8px;">Failure Threshold</div>'
        f'<div style="font:700 24px/1 JetBrains Mono,monospace;color:{_T1};margin-bottom:8px;">0.70</div>'
        f'<div style="background:{_SRF2};border-radius:2px;height:2px;">'
        f'<div style="width:70%;height:100%;background:{_BLU};border-radius:2px;"></div></div>'
        f'<div style="font:400 11px/1 Inter,sans-serif;color:{_T3};margin-top:6px;">Confidence cutoff</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Theme toggle ──────────────────────────────────────────
    st.markdown("<div style='height:4px'></div>", unsafe_allow_html=True)
    _toggle_lbl = "☀  Light Mode" if _THEME == "dark" else "☾  Dark Mode"
    if st.button(_toggle_lbl, use_container_width=True, key="theme_toggle", type="secondary"):
        st.session_state["theme"] = "light" if _THEME == "dark" else "dark"
        st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)  # close card div

# ── RIGHT CONTENT PANEL ───────────────────────────────────────
with col_main:

    tab_pred, tab_sys, tab_drift, tab_hist, tab_anlt, tab_alrt, tab_tmln = st.tabs([
        "  Prediction  ",
        "  System  ",
    "  Drift  ",
    "  History  ",
    "  Analytics  ",
    "  Alerts  ",
    "  Equipment Timeline  ",
])


# ═══════════════════════════════════════════════════════════════
# PREDICTION TAB
# ═══════════════════════════════════════════════════════════════

with tab_pred:
    _label("Live Sensor Monitor")
    render_sensor_grid(sensor_vals, st.session_state.get("last_anomalies", []))

    if predict_btn:
        with st.spinner("Running inference…"):
            try:
                resp = requests.post(API_URL, json=dict(sensor_vals), headers=HEADERS, timeout=10)
                resp.raise_for_status()
                r = resp.json()
                st.session_state["pred"]           = r
                st.session_state["last_anomalies"] = r.get("sensor_anomalies", [])
            except requests.exceptions.ConnectionError:
                _alert("error", "Cannot connect to backend — is the API server running on port 8000?")
                st.stop()
            except requests.exceptions.HTTPError as e:
                _on_http_error(e)
                _alert("error", f"API {e.response.status_code}: {e.response.text}")
                st.stop()
            except Exception as e:
                _alert("error", f"Unexpected error: {e}")
                st.stop()

    r = st.session_state.get("pred")

    if r:
        _sep()
        _label("Analysis Results")
        render_banner(r.get("severity","NONE"), r.get("recommendation",""), r.get("confidence",0))

        if r.get("alert"):
            st.markdown(
                f'<div class="fade-in" style="background:rgba(255,59,48,0.07);'
                f'border:1px solid rgba(255,59,48,0.25);border-radius:14px;'
                f'padding:14px 20px;margin-bottom:20px;">'
                f'<span style="font:600 10px/1 Inter,sans-serif;color:{_RED};'
                f'letter-spacing:0.4px;text-transform:uppercase;margin-right:10px;">Alert</span>'
                f'<span style="font:400 13px/1 Inter,sans-serif;color:{_RED};">'
                f'{r.get("alert_message","")}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        if r.get("trend_alert"):
            _alert("warning", f"Confidence trend: <b>{r.get('confidence_trend')}</b> — unusual spike detected.")

        # KPI row
        pred = r.get("prediction", 0)
        hs   = r.get("health_score", 100)
        tr   = r.get("confidence_trend","—")
        k1,k2,k3,k4,k5,k6 = st.columns(6)
        with k1: kpi("Status",        "Failure" if pred else "Normal",     _RED if pred else _GRN)
        with k2: kpi("Confidence",    f"{r.get('confidence',0)*100:.1f}%", _BLU)
        with k3: kpi("Time to Fail",  f"{r.get('time_to_failure_hours','—')}h", _ORG)
        with k4: kpi("Health Score",  f"{hs:.0f}/100", _GRN if hs>=70 else _RED)
        with k5: kpi("Trend",         tr, _RED if tr=="RISING" else _BLU if tr=="FALLING" else _GRN)
        with k6: kpi("Latency",       f"{r.get('latency_ms','—')}ms", _T2)

        st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

        col_a, col_b, col_c = st.columns([1.1, 0.65, 1.0])

        with col_a:
            _label("Top Risk Factors")
            render_factors(r.get("top_factors", []))
            if r.get("sensor_anomalies"):
                st.markdown(
                    f'<div style="background:rgba(255,149,0,0.07);border:1px solid rgba(255,149,0,0.2);'
                    f'border-radius:14px;padding:16px;margin-top:16px;">'
                    f'<div style="font:600 10px/1 Inter,sans-serif;color:{_ORG};'
                    f'letter-spacing:0.4px;text-transform:uppercase;margin-bottom:8px;">Sensor Anomalies</div>'
                    f'<div style="font:400 12px/1.5 Inter,sans-serif;color:{_ORG};">'
                    f'{r.get("anomaly_warning","")}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

        with col_b:
            _label("Confidence")
            render_gauge(r.get("confidence",0), r.get("prediction",0))
            render_health_ring(r.get("health_score",100), r.get("failure_mode","UNKNOWN"))

        with col_c:
            _label("SHAP Feature Importance")
            render_shap(r.get("shap_values", {}))

        _sep()
        pr_col, rca_col = st.columns(2)
        with pr_col:
            render_prescriptive(r.get("prescriptive_actions",[]), r.get("maintenance_priority","LOW"))
        with rca_col:
            render_rca(r.get("rca", {}))

        # Meta bar
        st.markdown(
            f'<div style="background:{_SRF};border:1px solid {_BDR};'
            f'border-radius:12px;padding:12px 20px;margin-top:16px;'
            f'display:flex;gap:28px;flex-wrap:wrap;align-items:center;">'
            f'<span style="font:400 11px/1 Inter,sans-serif;color:{_T3};">'
            f'Model <span style="color:{_T1};font-weight:500;">v{r.get("model_version","—")}</span></span>'
            f'<span style="font:400 11px/1 Inter,sans-serif;color:{_T3};">'
            f'Request <span style="color:{_T1};font-family:JetBrains Mono,monospace;font-size:10px;">'
            f'{r.get("request_id","—")[:22]}…</span></span>'
            f'<span style="font:400 11px/1 Inter,sans-serif;color:{_T3};">'
            f'Mode <span style="color:{_T1};font-weight:500;">{r.get("failure_mode","—")}</span></span>'
            f'<span style="font:400 11px/1 Inter,sans-serif;color:{_T3};">'
            f'Priority <span style="color:{PRIO_C.get(r.get("maintenance_priority","LOW"),_BLU)};'
            f'font-weight:500;">{r.get("maintenance_priority","—")}</span></span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        with st.expander("Raw API Response"):
            st.json(r)

    elif not predict_btn:
        _empty_state("◈", "Adjust sensor values and press Run Prediction", "Run Prediction")


# ═══════════════════════════════════════════════════════════════
# SYSTEM STATUS TAB
# ═══════════════════════════════════════════════════════════════

with tab_sys:
    if status_btn or "status" not in st.session_state:
        with st.spinner("Fetching status…"):
            try:
                resp = requests.get(STATUS_URL, headers=HEADERS, timeout=6)
                resp.raise_for_status()
                st.session_state["status"] = resp.json()
            except Exception as e:
                if isinstance(e, requests.exceptions.HTTPError): _on_http_error(e)
                _alert("error", f"Cannot fetch status: {e}")

    s = st.session_state.get("status")
    if s:
        _label("System Health")
        c1,c2,c3,c4,c5,c6 = st.columns(6)
        api_ok = s.get("api_status","") == "ok"
        drift_d = s.get("drift_detected", False)
        with c1: kpi("API",         "Online" if api_ok else "Offline", _GRN if api_ok else _RED)
        with c2: kpi("Model",       s.get("model_version","—"),         _T1)
        with c3: kpi("Predictions", str(s.get("total_predictions",0)),  _BLU)
        with c4: kpi("Failure Rate",f"{s.get('failure_rate',0)*100:.1f}%", _RED if s.get('failure_rate',0)>0.3 else _GRN)
        with c5: kpi("Avg Latency", f"{s.get('avg_latency_ms',0):.1f}ms",  _ORG)
        with c6: kpi("Drift",       "Detected" if drift_d else "Clean", _RED if drift_d else _GRN)

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        c7,c8,c9 = st.columns(3)
        with c7: kpi("P95 Latency", f"{s.get('p95_latency_ms',0):.1f}ms", _T1)
        with c8: kpi("DB Records",  str(s.get("db_records",0)),            _BLU)
        with c9:
            up = s.get("uptime_seconds",0)
            h,r=divmod(up,3600); m,sc=divmod(r,60)
            kpi("Uptime", f"{h:02d}h {m:02d}m", _GRN)

        if drift_d and s.get("drifted_features"):
            _alert("warning", f"Drifted features: {', '.join(s['drifted_features'])}")
    else:
        _empty_state("⌁", "Load a snapshot of API health, throughput and drift status", "System Status")


# ═══════════════════════════════════════════════════════════════
# DRIFT REPORT TAB
# ═══════════════════════════════════════════════════════════════

with tab_drift:
    if drift_btn or "drift" not in st.session_state:
        with st.spinner("Fetching drift report…"):
            try:
                resp = requests.get(DRIFT_URL, headers=HEADERS, timeout=6)
                resp.raise_for_status()
                st.session_state["drift"] = resp.json()
            except Exception as e:
                if isinstance(e, requests.exceptions.HTTPError): _on_http_error(e)
                _alert("error", f"Cannot fetch drift report: {e}")

    d = st.session_state.get("drift")
    if d:
        if "message" in d:
            _alert("info", d["message"])
        else:
            _label("Feature Drift Analysis")
            n = len(d.get("drifted_features",[]))
            c1,c2,c3,c4 = st.columns(4)
            with c1: kpi("Checked",        d.get("checked_at","—")[:10],               _T1)
            with c2: kpi("Tested",         str(d.get("total_features_checked",0)),      _BLU)
            with c3: kpi("Drifted",        str(n),                                      _RED if n>0 else _GRN)
            with c4: kpi("Retrain",        "Required" if d.get("retrain_triggered") else "Not needed", _RED if d.get("retrain_triggered") else _GRN)
            if d.get("drifted_features"):
                _alert("error", f"Drift detected in: {', '.join(d['drifted_features'])}")
                drift_df = pd.DataFrame(d.get("drift_details",[]))
                if not drift_df.empty:
                    st.dataframe(drift_df, use_container_width=True)
            else:
                _alert("success", "All feature distributions are stable — no drift detected.")
    else:
        _empty_state("∿", "Check whether live sensor distributions have drifted from training data", "Drift Report")


# ═══════════════════════════════════════════════════════════════
# HISTORY TAB
# ═══════════════════════════════════════════════════════════════

with tab_hist:
    if history_btn or "history" not in st.session_state:
        with st.spinner("Loading history…"):
            try:
                resp = requests.get(HISTORY_URL, params={"limit":200}, headers=HEADERS, timeout=10)
                resp.raise_for_status()
                st.session_state["history"] = resp.json()
            except Exception as e:
                if isinstance(e, requests.exceptions.HTTPError): _on_http_error(e)
                _alert("error", f"Cannot fetch history: {e}")

    hist = st.session_state.get("history")
    if hist:
        records = hist.get("records",[])
        if not records:
            _alert("info", "No prediction records found.")
        else:
            df_h     = pd.DataFrame(records)
            total    = len(df_h)
            failures = int(df_h["prediction"].sum()) if "prediction" in df_h.columns else 0
            avg_c    = float(df_h["confidence"].mean()) if "confidence" in df_h.columns else 0
            avg_h    = float(df_h["health_score"].mean()) if "health_score" in df_h.columns else 0

            _label(f"Prediction Timeline — {total} records")
            kc1,kc2,kc3,kc4 = st.columns(4)
            with kc1: kpi("Total",       str(total),               _BLU)
            with kc2: kpi("Failures",    str(failures),            _RED if failures>0 else _GRN)
            with kc3: kpi("Avg Conf",    f"{avg_c*100:.1f}%",      _T1)
            with kc4: kpi("Avg Health",  f"{avg_h:.1f}/100",       _GRN if avg_h>=70 else _RED)

            st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
            ch1, ch2 = st.columns([2,1])
            with ch1: st.plotly_chart(_conf_timeline(records), use_container_width=True, config={"displayModeBar":False}, key="hist_timeline")
            with ch2: st.plotly_chart(_sev_donut(records),     use_container_width=True, config={"displayModeBar":False}, key="hist_donut")

            _label("Record Table")
            disp = [c for c in ["timestamp","prediction","confidence","severity",
                                  "health_score","failure_mode","ttf_hours","latency_ms"]
                    if c in df_h.columns]
            st.dataframe(df_h[disp], use_container_width=True, height=300)
    else:
        _empty_state("◷", "Browse the last 200 predictions across confidence and severity", "History")


# ═══════════════════════════════════════════════════════════════
# ANALYTICS TAB
# ═══════════════════════════════════════════════════════════════

with tab_anlt:
    hours_sel = st.select_slider("Time window", options=[1,3,6,12,24,48,72,168], value=24, key="an_hrs")

    if analytics_btn or "analytics" not in st.session_state:
        with st.spinner("Computing analytics…"):
            try:
                resp = requests.get(ANALYTICS_URL, params={"hours":hours_sel}, headers=HEADERS, timeout=10)
                resp.raise_for_status()
                st.session_state["analytics"] = resp.json()
            except Exception as e:
                if isinstance(e, requests.exceptions.HTTPError): _on_http_error(e)
                _alert("error", f"Cannot fetch analytics: {e}")

    an = st.session_state.get("analytics")
    if an:
        total_an = an.get("total",0) or 0
        fails_an = an.get("failures",0) or 0
        fr       = (fails_an/total_an*100) if total_an else 0

        _label(f"Analytics — Last {hours_sel}h")
        a1,a2,a3,a4,a5 = st.columns(5)
        with a1: kpi("Events",        str(total_an),                       _BLU)
        with a2: kpi("Failures",      str(fails_an),                       _RED if fails_an>0 else _GRN)
        with a3: kpi("Failure Rate",  f"{fr:.1f}%",                        _RED if fr>20 else _GRN)
        with a4: kpi("Avg Confidence",f"{(an.get('avg_confidence') or 0)*100:.1f}%", _T1)
        with a5: kpi("Avg Health",    f"{an.get('avg_health') or 0:.1f}",  _GRN if (an.get("avg_health") or 0)>=70 else _RED)

        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        b1,b2,b3,b4 = st.columns(4)
        with b1: kpi("High",   str(an.get("high_count")   or 0), _RED)
        with b2: kpi("Medium", str(an.get("medium_count") or 0), _ORG)
        with b3: kpi("Low",    str(an.get("low_count")    or 0), _GRN)
        with b4: kpi("None",   str(an.get("none_count")   or 0), _BLU)

        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        rows = an.get("confidence_trend",[])
        md   = an.get("failure_mode_distribution",[])
        c1, c2 = st.columns([2,1])
        with c1: st.plotly_chart(_health_trend(rows), use_container_width=True, config={"displayModeBar":False}, key="an_health")
        with c2: st.plotly_chart(_mode_bar(md),       use_container_width=True, config={"displayModeBar":False}, key="an_modes")
        if rows:
            st.plotly_chart(_conf_timeline(rows), use_container_width=True, config={"displayModeBar":False}, key="an_timeline")
    else:
        _empty_state("▤", "Select a time window, then load aggregate trends and failure modes", "Analytics")


# ═══════════════════════════════════════════════════════════════
# ALERTS TAB
# ═══════════════════════════════════════════════════════════════

with tab_alrt:
    fc1, fc2 = st.columns([3,1])
    with fc1: unack = st.checkbox("Unacknowledged only", value=False, key="unack_f")
    with fc2: ref_btn = st.button("Refresh", use_container_width=True, key="ref_alrt")

    if alerts_btn or ref_btn or "alerts" not in st.session_state:
        with st.spinner("Loading alerts…"):
            try:
                resp = requests.get(
                    ALERTS_URL,
                    params={"limit":100,"unack_only":str(unack).lower()},
                    headers=HEADERS, timeout=10,
                )
                resp.raise_for_status()
                st.session_state["alerts"] = resp.json()
            except Exception as e:
                if isinstance(e, requests.exceptions.HTTPError): _on_http_error(e)
                _alert("error", f"Cannot fetch alerts: {e}")

    al = st.session_state.get("alerts")
    if al:
        alist    = al.get("alerts",[])
        unack_n  = sum(1 for a in alist if not a.get("acknowledged"))
        _label(f"Alert Center — {len(alist)} alerts · {unack_n} unacknowledged")

        if not alist:
            _alert("success", "No alerts match your filter.")
        else:
            for alert in alist:
                sev      = alert.get("severity","NONE")
                sc       = SEVERITY.get(sev, SEVERITY["NONE"])
                is_ack   = bool(alert.get("acknowledged"))
                ts       = (alert.get("timestamp","")[:16]).replace("T"," ")
                ack_span = (
                    '<span style="font:500 10px/1 Inter,sans-serif;color:#30d158;margin-left:8px;">✓ Acknowledged</span>'
                    if is_ack else ""
                )
                opacity  = "0.45" if is_ack else "1"

                row_l, row_r = st.columns([5,1])
                with row_l:
                    st.markdown(
                        f'<div style="background:{sc["bg"]};border:1px solid {sc["bd"]};'
                        f'border-radius:14px;padding:16px 20px;margin-bottom:8px;opacity:{opacity};">'
                        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;">'
                        f'{_pill(sc["label"].upper(), sc["c"])}'
                        f'<span style="font:400 11px/1 Inter,sans-serif;color:{_T3};">{ts}</span>'
                        f'<span style="margin-left:auto;font:700 13px/1 JetBrains Mono,monospace;'
                        f'color:{sc["c"]};">{alert.get("confidence",0)*100:.1f}%</span>'
                        f'{ack_span}'
                        f'</div>'
                        f'<div style="font:400 13px/1.5 Inter,sans-serif;color:{sc["c"]};'
                        f'margin-bottom:6px;">{alert.get("message","")}</div>'
                        f'<div style="font:400 10px/1 Inter,sans-serif;color:{_T3};">'
                        f'ID #{alert.get("id","—")} · {str(alert.get("request_id","—"))[:22]}…'
                        f'</div></div>',
                        unsafe_allow_html=True,
                    )
                with row_r:
                    if not is_ack:
                        if st.button("Acknowledge", key=f"ack_{alert.get('id')}", use_container_width=True):
                            try:
                                ar = requests.post(
                                    f"{BACKEND_HOST}/alerts/{alert.get('id')}/acknowledge",
                                    headers=HEADERS, timeout=5,
                                )
                                ar.raise_for_status()
                                st.toast(f"Acknowledged #{alert.get('id')}", icon="✓")
                                st.session_state.pop("alerts",None)
                                st.rerun()
                            except Exception as e:
                                if isinstance(e, requests.exceptions.HTTPError): _on_http_error(e)
                                _alert("error", f"Failed: {e}")
    else:
        _empty_state("◉", "Review and acknowledge severity-flagged prediction alerts", "Alerts")


# ═══════════════════════════════════════════════════════════════
# EQUIPMENT TIMELINE TAB
# ═══════════════════════════════════════════════════════════════

_STATUS_COLOR = {"green": _GRN, "yellow": _ORG, "red": _RED, "unknown": _T3}


def _timeline_chart(current_status: dict, next_maintenance: dict) -> go.Figure:
    """Horizontal green/yellow/red bar: now -> projected next-maintenance ETA."""
    color = _STATUS_COLOR.get((current_status or {}).get("status_color"), _T3)
    eta_hours = (next_maintenance or {}).get("eta_hours")
    span = eta_hours if eta_hours is not None else 72  # flat/improving health — show a neutral window

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[span], y=["Equipment"], orientation="h",
        marker=dict(color=color), width=0.5,
        hovertemplate="%{x:.1f}h<extra></extra>",
    ))
    fig.update_layout(
        height=110, margin=dict(l=0, r=0, t=10, b=30),
        xaxis=dict(title="Hours from now", showgrid=False),
        yaxis=dict(visible=False),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
    )
    return fig


with tab_tmln:
    eq_col1, eq_col2 = st.columns([3, 1])
    with eq_col1:
        equipment_id_sel = st.number_input(
            "Equipment ID", min_value=1, value=1, step=1, key="tmln_eq_id",
        )
    with eq_col2:
        tmln_refresh = st.button("Load Timeline", use_container_width=True, key="tmln_refresh")

    if timeline_btn or tmln_refresh or "timeline" not in st.session_state:
        with st.spinner("Loading equipment timeline…"):
            try:
                resp = requests.get(timeline_url(int(equipment_id_sel)), headers=HEADERS, timeout=10)
                resp.raise_for_status()
                st.session_state["timeline"] = resp.json()
            except Exception as e:
                if isinstance(e, requests.exceptions.HTTPError): _on_http_error(e)
                _alert("error", f"Cannot fetch equipment timeline: {e}")

    tl = st.session_state.get("timeline")
    if tl:
        current   = tl.get("current_status")
        next_maint = tl.get("next_predicted_maintenance")
        last_maint = tl.get("last_maintenance")

        _label(f"Equipment #{tl.get('equipment_id')} — Health Timeline")

        if current:
            status_color = _STATUS_COLOR.get(current.get("status_color"), _T3)
            kt1, kt2, kt3 = st.columns(3)
            with kt1: kpi("Current Health", f"{current.get('health_score', '—')}", status_color)
            with kt2: kpi("Severity", current.get("severity", "—"), status_color)
            with kt3: kpi(
                "Next Maintenance ETA",
                f"{next_maint.get('eta_hours')}h" if next_maint and next_maint.get("eta_hours") is not None else "—",
                _ORG,
            )
            st.plotly_chart(
                _timeline_chart(current, next_maint), use_container_width=True,
                config={"displayModeBar": False}, key="equipment_timeline_chart",
            )
            if next_maint and next_maint.get("message"):
                st.markdown(
                    f'<div style="font:400 11px/1.5 Inter,sans-serif;color:{_T3};'
                    f'margin-top:6px;">{next_maint["message"]}</div>',
                    unsafe_allow_html=True,
                )
        else:
            _alert("info", "No predictions recorded yet for this equipment.")

        _label("Last Actual Maintenance")
        if last_maint:
            st.markdown(
                f'<div style="background:{_SRF2};border-radius:14px;padding:16px 20px;">'
                f'<div style="font:500 12px/1 Inter,sans-serif;color:{_T1};margin-bottom:6px;">'
                f'{last_maint.get("failure_mode","—")} — resolved {str(last_maint.get("resolved_at",""))[:16].replace("T"," ")}</div>'
                f'<div style="font:400 12px/1.4 Inter,sans-serif;color:{_T3};">Request {last_maint.get("request_id","—")}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="font:400 11px/1.5 Inter,sans-serif;color:{_T3};">'
                f'No resolved maintenance action on record for this equipment yet.</div>',
                unsafe_allow_html=True,
            )
    else:
        _empty_state("⏣", "Track an asset's health, drift and last maintenance over time", "Load Timeline")
