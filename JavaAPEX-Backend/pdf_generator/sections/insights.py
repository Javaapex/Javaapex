from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, Spacer, Table

from ..components.cards import score_card_table
from ..components.charts import build_progress_gauge


def build_ai_insights_section(context: dict, styles):
    scores = context["scores"]
    score_cards = [
        {"title": "Security Score", "value": f"{scores['security']}%", "detail": "Measures vulnerability pressure, hotspot review burden, and severity posture.", "accent": context["risk_color"]},
        {"title": "Maintainability Score", "value": f"{scores['maintainability']}%", "detail": "Captures code smell volume, complexity, and refactoring drag.", "accent": context["maintainability_color"]},
        {"title": "Testability Score", "value": f"{scores['testability']}%", "detail": "Derived primarily from coverage and overall code health indicators.", "accent": context["coverage_color"]},
        {"title": "Modernization Readiness", "value": f"{scores['modernization_readiness']}%", "detail": "Blended view of security, maintainability, cloud readiness, and Java upgrade compatibility.", "accent": context["readiness_color"]},
    ]

    bullets = [ListItem(Paragraph(f"<b>{item['priority']}:</b> {item['title']} - {item['detail']}", styles["body"])) for item in context["ai_recommendations"]]

    gauges = Table(
        [
            [build_progress_gauge("Cloud Readiness", scores["cloud_readiness"], context["readiness_color"]), build_progress_gauge("Java Upgrade Compatibility", scores["java_upgrade_compatibility"], context["coverage_color"])],
            [build_progress_gauge("Security Score", scores["security"], context["risk_color"]), build_progress_gauge("Maintainability Score", scores["maintainability"], context["maintainability_color"])],
        ],
        colWidths=[90 * mm, 90 * mm],
    )

    return [
        Paragraph("AI Insights & Migration Readiness", styles["h1"]),
        Paragraph("These insights prioritize what should be remediated first to improve modernization confidence, security posture, and operational readiness.", styles["body"]),
        Spacer(1, 4 * mm),
        score_card_table(score_cards, styles, columns=2),
        Spacer(1, 3 * mm),
        Paragraph("AI Recommendations", styles["h2"]),
        ListFlowable(bullets, bulletType="bullet", start="circle"),
        Spacer(1, 5 * mm),
        Paragraph("Migration Readiness Signals", styles["h2"]),
        gauges,
        PageBreak(),
    ]

