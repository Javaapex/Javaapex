from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer

from ..components.tables import build_findings_table, build_metadata_table
from ..helpers.snippets import load_code_snippet, suggest_remediation


def build_security_overview_section(context: dict, styles):
    job = context["job"]
    report = context["report"]
    vulnerabilities = report.get("vulnerability_details", [])[:8]
    hotspots = report.get("security_hotspot_details", [])[:6]
    summary_entries = [
        ("Quality Gate", getattr(job, "sonar_quality_gate", None) or "N/A"),
        ("Risk Posture", context["risk_posture"]),
        ("Vulnerabilities", str(getattr(job, "sonar_vulnerabilities", 0))),
        ("Security Hotspots", str(getattr(job, "sonar_security_hotspots", 0))),
        ("Dashboard", f'<link href="{context["dashboard_url"]}">{context["dashboard_url"]}</link>' if context["dashboard_url"] else "N/A"),
    ]
    flowables = [
        Paragraph("Security Overview", styles["h1"]),
        build_metadata_table(summary_entries, styles),
        Spacer(1, 4 * mm),
        Paragraph("Top Vulnerabilities", styles["h2"]),
        build_findings_table(vulnerabilities, styles, max_rows=8) if vulnerabilities else Paragraph("No vulnerability details were returned for this scan.", styles["muted"]),
        Spacer(1, 4 * mm),
        Paragraph("Security Hotspots", styles["h2"]),
        build_findings_table(hotspots, styles, max_rows=6) if hotspots else Paragraph("No hotspot details were returned for this scan.", styles["muted"]),
    ]

    if vulnerabilities:
        primary = vulnerabilities[0]
        fix = suggest_remediation(primary)
        snippet = load_code_snippet(job, primary.get("component"), primary.get("line"))
        flowables.extend(
            [
                Spacer(1, 4 * mm),
                Paragraph("Code Preview & Suggested Remediation", styles["h2"]),
                Paragraph(f"<b>Finding:</b> {primary.get('message', 'N/A')}", styles["body"]),
                Paragraph(f"<b>Problematic snippet</b><br/><font face='Courier'>{(snippet or fix['bad']).replace(chr(10), '<br/>')}</font>", styles["muted"]),
                Spacer(1, 2 * mm),
                Paragraph(f"<b>Suggested fix</b><br/><font face='Courier'>{fix['good'].replace(chr(10), '<br/>')}</font>", styles["muted"]),
                Paragraph(fix["summary"], styles["body"]),
            ]
        )
    flowables.append(PageBreak())
    return flowables

