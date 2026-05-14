from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer, Table, TableStyle
from reportlab.graphics.shapes import Drawing as ShapeDrawing, Rect, String

from ..components.cards import metric_card_table
from ..components.charts import build_issue_distribution_chart, build_qr_code, build_severity_distribution_chart
from ..helpers.formatters import format_timestamp, get_repository_name
from ..styles.theme import PALETTE


def build_dashboard_section(context: dict, styles):
    job = context["job"]
    scores = context["scores"]
    metrics = [
        {"label": "Project Health", "value": f"{scores['project_health']} / 100", "accent": PALETTE["info"]},
        {"label": "Risk Posture", "value": context["risk_posture"], "accent": context["risk_color"]},
        {"label": "Quality Gate", "value": getattr(job, "sonar_quality_gate", None) or "N/A", "accent": PALETTE["success"] if getattr(job, "sonar_quality_gate", "") == "PASSED" else context["risk_color"]},
        {"label": "Coverage", "value": f"{getattr(job, 'sonar_coverage', 0)}%", "accent": PALETTE["info"]},
        {"label": "Vulnerabilities", "value": str(getattr(job, "sonar_vulnerabilities", 0)), "accent": PALETTE["critical"]},
        {"label": "Code Smells", "value": str(getattr(job, "sonar_code_smells", 0)), "accent": PALETTE["major"]},
        {"label": "Bugs", "value": str(getattr(job, "sonar_bugs", 0)), "accent": PALETTE["info"]},
        {"label": "Security Hotspots", "value": str(getattr(job, "sonar_security_hotspots", 0)), "accent": colors.HexColor("#B45309")},
    ]

    logo = ShapeDrawing(42, 42)
    logo.add(Rect(0, 0, 42, 42, fillColor=PALETTE["surface"], strokeColor=PALETTE["border"], rx=6, ry=6))
    logo.add(String(8, 17, "LOGO", fontName="Helvetica-Bold", fontSize=11, fillColor=PALETTE["muted"]))

    hero = Table(
        [[
            logo,
            Paragraph("<b>Modernization & Security Assessment</b>", styles["title"]),
            build_qr_code(context["dashboard_url"]) if context["dashboard_url"] else "",
        ]],
        colWidths=[18 * mm, 125 * mm, 22 * mm],
    )
    hero.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))

    subtitle = Paragraph(
        f"<b>Repository:</b> {get_repository_name(getattr(job, 'source_repo', None))} &nbsp;&nbsp; "
        f"<b>Scan Timestamp:</b> {format_timestamp(getattr(job, 'completed_at', None))} &nbsp;&nbsp; "
        f"<b>Report Version:</b> {context['report_version']}",
        styles["body"],
    )

    chart_row = Table(
        [[build_issue_distribution_chart(context["issue_distribution"]), build_severity_distribution_chart(context["severity_distribution"])]],
        colWidths=[88 * mm, 95 * mm],
    )
    chart_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))

    return [
        hero,
        Spacer(1, 4 * mm),
        subtitle,
        Spacer(1, 6 * mm),
        metric_card_table(metrics, styles, columns=4),
        Spacer(1, 4 * mm),
        Paragraph(context["executive_summary"], styles["body"]),
        Spacer(1, 6 * mm),
        chart_row,
        PageBreak(),
    ]
