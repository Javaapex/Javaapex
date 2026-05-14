from __future__ import annotations

from io import BytesIO
from typing import Any, Dict

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import PageBreak, SimpleDocTemplate, Spacer

from .helpers.formatters import format_timestamp
from .helpers.scoring import (
    build_ai_recommendations,
    issue_category_distribution,
    remediation_effort_hours,
    risk_posture,
    scorecard,
    severity_distribution,
    top_findings_by_severity,
)
from .sections.conclusion import build_conclusion_section
from .sections.dashboard import build_dashboard_section
from .sections.findings import build_detailed_findings_section
from .sections.insights import build_ai_insights_section
from .sections.maintainability import build_maintainability_section
from .sections.refactoring import build_refactoring_section
from .sections.security import build_security_overview_section
from .sections.testing import build_coverage_testing_section
from .styles.theme import PALETTE, build_styles


class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        self._saved_page_states = []
        super().__init__(*args, **kwargs)

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(page_count)
            super().showPage()
        super().save()

    def _draw_footer(self, page_count: int):
        page_width, page_height = A4
        self.saveState()
        self.setFillColor(colors.Color(0.96, 0.97, 0.99))
        self.setFont("Helvetica-Bold", 46)
        self.translate(page_width / 2, page_height / 2)
        self.rotate(35)
        self.drawCentredString(0, 0, "CONFIDENTIAL")
        self.restoreState()

        self.saveState()
        self.setFillColor(PALETTE["muted"])
        self.setFont("Helvetica", 8)
        self.drawString(15 * mm, 8 * mm, "Java Migration Accelerator | Sonar Modernization Assessment")
        self.drawRightString(page_width - 15 * mm, 8 * mm, f"Page {self._pageNumber} of {page_count}")
        self.drawString(15 * mm, 13 * mm, "Confidential | Version 2.0")
        self.restoreState()


def _context_from_job(job: Any) -> Dict[str, Any]:
    report = getattr(job, "sonar_report", None) or {}
    scores = scorecard(job, report)
    posture = risk_posture(job, report)
    risk_color = {
        "Critical": PALETTE["blocker"],
        "High": PALETTE["critical"],
        "Moderate": PALETTE["major"],
        "Low": PALETTE["success"],
    }[posture]
    maintainability_color = PALETTE["major"] if scores["maintainability"] < 65 else PALETTE["success"]
    coverage_color = PALETTE["info"] if scores["testability"] >= 70 else PALETTE["major"]
    readiness_color = PALETTE["success"] if scores["modernization_readiness"] >= 75 else PALETTE["major"] if scores["modernization_readiness"] >= 55 else PALETTE["critical"]
    dashboard_url = getattr(job, "sonar_analysis_url", None) or report.get("analysis_url")
    executive_summary = (
        f"{getattr(job, 'source_repo', 'This repository')} was assessed on {format_timestamp(getattr(job, 'completed_at', None))}. "
        f"The scan reported {getattr(job, 'sonar_vulnerabilities', 0)} vulnerabilities, {getattr(job, 'sonar_code_smells', 0)} code smells, "
        f"{getattr(job, 'sonar_bugs', 0)} bugs, and {getattr(job, 'sonar_security_hotspots', 0)} security hotspots with a "
        f"quality gate status of {getattr(job, 'sonar_quality_gate', None) or 'N/A'}."
    )
    return {
        "job": job,
        "report": report,
        "scores": scores,
        "risk_posture": posture,
        "risk_color": risk_color,
        "maintainability_color": maintainability_color,
        "coverage_color": coverage_color,
        "readiness_color": readiness_color,
        "issue_distribution": issue_category_distribution(job),
        "severity_distribution": severity_distribution(report),
        "ai_recommendations": build_ai_recommendations(job, report),
        "efforts": remediation_effort_hours(report),
        "dashboard_url": dashboard_url,
        "executive_summary": executive_summary,
        "top_findings": top_findings_by_severity(report),
        "report_version": "2.0",
    }


def build_sonar_assessment_pdf(job: Any) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=18 * mm,
        title="Sonar Modernization & Security Assessment",
        author="Java Migration Accelerator",
    )
    styles = build_styles()
    context = _context_from_job(job)

    story = []
    story.extend(build_dashboard_section(context, styles))
    story.extend(build_ai_insights_section(context, styles))
    story.extend(build_security_overview_section(context, styles))
    story.extend(build_maintainability_section(context, styles))
    story.extend(build_coverage_testing_section(context, styles))
    story.extend(build_refactoring_section(context, styles))
    story.extend(build_detailed_findings_section(context, styles))
    story.append(PageBreak())
    story.extend(build_conclusion_section(context, styles))
    story.append(Spacer(1, 4 * mm))

    doc.build(story, canvasmaker=NumberedCanvas)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
