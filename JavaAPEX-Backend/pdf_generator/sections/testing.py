from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer

from ..components.charts import build_progress_gauge


def build_coverage_testing_section(context: dict, styles):
    job = context["job"]
    coverage = float(getattr(job, "sonar_coverage", 0.0) or 0.0)
    score = context["scores"]["testability"]
    bullets = [
        f"Coverage currently sits at {coverage}%, which is {'below' if coverage < 50 else 'within'} a comfortable modernization threshold.",
        f"Testability score is {score}%, indicating how safely the codebase can absorb refactoring and Java upgrade work.",
        "Target high-complexity services and vulnerability-affected components first when expanding unit and integration tests.",
    ]
    flowables = [
        Paragraph("Coverage & Testing", styles["h1"]),
        build_progress_gauge("Coverage", int(round(coverage)), context["coverage_color"]),
        Spacer(1, 4 * mm),
        build_progress_gauge("Testability Score", score, context["coverage_color"]),
        Spacer(1, 5 * mm),
        Paragraph("Assessment Notes", styles["h2"]),
    ]
    for note in bullets:
        flowables.append(Paragraph(f"• {note}", styles["body"]))
    flowables.append(PageBreak())
    return flowables

