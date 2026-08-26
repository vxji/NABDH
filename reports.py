# =============================================================
# reports.py — Auto-generated PDF Prediction Reports (§6 of v4.2.0)
# NABDH AI Maintenance Platform
# =============================================================
#
# reportlab, not WeasyPrint: pure-Python, no native Cairo/Pango dependency
# (WeasyPrint is notoriously hard to install on Windows). matplotlib (Agg,
# headless) renders the SHAP bar chart as a static PNG embedded in the PDF.
# Purely a presentation layer over an already-computed prediction result —
# no ml_logic.py / SHAP TreeExplainer logic here, just reading its output.

import io
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

logger = logging.getLogger(__name__)

REPORTS_DIR = os.getenv("REPORTS_DIR", "reports")

_TABLE_STYLE = TableStyle([
    ("BACKGROUND",  (0, 0), (-1, 0), colors.HexColor("#1c1c1e")),
    ("TEXTCOLOR",   (0, 0), (-1, 0), colors.white),
    ("GRID",        (0, 0), (-1, -1), 0.5, colors.grey),
    ("FONTSIZE",    (0, 0), (-1, -1), 9),
    ("VALIGN",      (0, 0), (-1, -1), "TOP"),
])


def _shap_chart_image(shap_values: dict, top_n: int = 8) -> Optional[io.BytesIO]:
    if not shap_values:
        return None
    items = sorted(shap_values.items(), key=lambda kv: abs(kv[1]), reverse=True)[:top_n]
    items.reverse()  # largest bar ends up on top in a horizontal barh plot
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    bar_colors = ["#ff3b30" if v > 0 else "#30d158" for v in values]

    fig, ax = plt.subplots(figsize=(6, 3.2))
    ax.barh(labels, values, color=bar_colors)
    ax.set_xlabel("SHAP value (impact on failure probability)")
    ax.set_title("Top Contributing Sensors")
    fig.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


def generate_prediction_report(prediction: dict) -> bytes:
    """
    `prediction` is the same shape main.py's PredictionResponse produces
    (plus request_id) — prediction result, SHAP chart, RCA, prescriptive
    actions, and a generation timestamp.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, topMargin=0.6 * inch, bottomMargin=0.6 * inch)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("NABDH Maintenance Report", styles["Title"]))
    story.append(Paragraph(f"Request ID: {prediction.get('request_id', '—')}", styles["Normal"]))
    story.append(Paragraph(f"Generated: {datetime.now(timezone.utc).isoformat()}", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    summary_rows = [
        ["Field", "Value"],
        ["Prediction", "FAILURE" if prediction.get("prediction") else "NORMAL"],
        ["Confidence", f"{(prediction.get('confidence') or 0) * 100:.1f}%"],
        ["Severity", str(prediction.get("severity", "—"))],
        ["Health Score", str(prediction.get("health_score", "—"))],
        ["Failure Mode", str(prediction.get("failure_mode", "—"))],
        ["Time to Failure (hours)", str(prediction.get("time_to_failure_hours", "—"))],
        ["Recommendation", str(prediction.get("recommendation", "—"))],
        ["Model Version", str(prediction.get("model_version", "—"))],
    ]
    table = Table(summary_rows, colWidths=[2.2 * inch, 3.8 * inch])
    table.setStyle(_TABLE_STYLE)
    story.append(table)
    story.append(Spacer(1, 0.25 * inch))

    shap_values = prediction.get("shap_values") or {}
    chart = _shap_chart_image(shap_values)
    if chart:
        story.append(Paragraph("SHAP Explainability", styles["Heading2"]))
        story.append(Image(chart, width=6 * inch, height=3.2 * inch))
        story.append(Spacer(1, 0.2 * inch))

    rca = prediction.get("rca") or {}
    if rca.get("primary_cause"):
        story.append(Paragraph("Root Cause Analysis", styles["Heading2"]))
        story.append(Paragraph(str(rca.get("primary_cause", "")), styles["Normal"]))
        for step in (rca.get("causal_chain") or [])[:5]:
            story.append(Paragraph(f"• {step.get('narrative', '')}", styles["Normal"]))
        story.append(Spacer(1, 0.2 * inch))

    actions = prediction.get("prescriptive_actions") or []
    if actions:
        story.append(Paragraph("Prescriptive Actions", styles["Heading2"]))
        action_rows = [["Priority", "Action", "Est. Hours"]]
        for a in actions:
            action_rows.append([
                str(a.get("priority", "—")),
                str(a.get("action", "—")),
                str(a.get("est_fix_hours", "—")),
            ])
        action_table = Table(action_rows, colWidths=[0.8 * inch, 4.4 * inch, 0.8 * inch])
        action_table.setStyle(_TABLE_STYLE)
        story.append(action_table)

    doc.build(story)
    return buf.getvalue()


def save_report(request_id: str, pdf_bytes: bytes) -> str:
    os.makedirs(REPORTS_DIR, exist_ok=True)
    file_path = os.path.join(REPORTS_DIR, f"{request_id}.pdf")
    with open(file_path, "wb") as f:
        f.write(pdf_bytes)
    return file_path
