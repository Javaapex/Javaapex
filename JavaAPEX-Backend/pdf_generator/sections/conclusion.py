from __future__ import annotations

from reportlab.platypus import Paragraph


def build_conclusion_section(context: dict, styles):
    scores = context["scores"]
    posture = context["risk_posture"]
    confidence = "High" if scores["modernization_readiness"] >= 80 else "Moderate" if scores["modernization_readiness"] >= 60 else "Cautious"
    readiness = "Ready with remediation" if posture in {"Low", "Moderate"} else "Needs targeted remediation"
    narrative = (
        f"The application shows a <b>{confidence}</b> modernization confidence level with an overall readiness score of "
        f"<b>{scores['modernization_readiness']}%</b>. Current risk posture is <b>{posture}</b>, and production readiness is best described as "
        f"<b>{readiness}</b>."
    )
    next_steps = [
        "Close security vulnerabilities and complete hotspot triage before production sign-off.",
        "Refactor the highest-complexity services and repeated-literal hotspots to reduce modernization risk.",
        "Increase automated coverage around the most business-critical code paths and fixed findings.",
        "Re-run Sonar after remediation to validate quality gate movement and improved readiness scores.",
    ]
    flowables = [
        Paragraph("Executive Conclusion & Next Steps", styles["h1"]),
        Paragraph(narrative, styles["body"]),
        Paragraph(
            "The application is suitable for modernization, however remediation of security findings and improvement in unit test coverage are strongly recommended before production migration.",
            styles["body"],
        ),
        Paragraph("Recommended Next Steps", styles["h2"]),
    ]
    for item in next_steps:
        flowables.append(Paragraph(f"• {item}", styles["body"]))
    return flowables

