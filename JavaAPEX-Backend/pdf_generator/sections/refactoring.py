from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer


def build_refactoring_section(context: dict, styles):
    efforts = context["efforts"]
    ordered = sorted(efforts.items(), key=lambda item: item[1], reverse=True)
    total_hours = round(sum(value for _, value in ordered), 1)
    flowables = [
        Paragraph("Refactoring Recommendations", styles["h1"]),
        Paragraph(
            "The remediation roadmap below estimates where engineering time will likely be spent and what order of work will reduce risk fastest.",
            styles["body"],
        ),
        Spacer(1, 4 * mm),
        Paragraph(f"<b>Total estimated remediation effort:</b> {total_hours} hours", styles["body"]),
        Spacer(1, 2 * mm),
    ]
    for index, (label, hours) in enumerate(ordered, start=1):
        priority = "High" if index == 1 else "Medium" if index <= 3 else "Low"
        flowables.append(Paragraph(f"{index}. <b>{label}</b> - {hours} hours estimated ({priority} priority)", styles["body"]))
    flowables.append(Spacer(1, 4 * mm))
    flowables.append(Paragraph("Suggested Remediation Order", styles["h2"]))
    ordered_steps = [
        "Contain security vulnerabilities and complete hotspot review.",
        "Refactor critical complexity and duplicated-literal hotspots in core services.",
        "Resolve maintainability issues that block automated testing and readability.",
        "Expand test coverage around refactored and security-sensitive components.",
    ]
    for step in ordered_steps:
        flowables.append(Paragraph(f"• {step}", styles["body"]))
    flowables.append(PageBreak())
    return flowables

