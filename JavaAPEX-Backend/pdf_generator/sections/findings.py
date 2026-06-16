from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer

from ..components.tables import build_findings_table


def build_detailed_findings_section(context: dict, styles):
    report = context["report"]
    sections = [
        ("Detailed Vulnerabilities", report.get("vulnerability_details", [])),
        ("Detailed Code Smells", report.get("code_smell_details", [])),
        ("Detailed Bugs", report.get("bug_details", [])),
        ("Detailed Security Hotspots", report.get("security_hotspot_details", [])),
    ]
    flowables = []
    first = True
    for title, findings in sections:
        if not first:
            flowables.append(PageBreak())
        first = False
        flowables.append(Paragraph(title, styles["h1"]))
        if findings:
            flowables.append(build_findings_table(findings, styles))
        else:
            flowables.append(Paragraph("No detailed findings were returned for this category.", styles["muted"]))
        flowables.append(Spacer(1, 3 * mm))
    return flowables

