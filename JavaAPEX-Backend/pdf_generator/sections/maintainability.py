from __future__ import annotations

from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, Spacer

from ..components.tables import build_findings_table
from ..helpers.scoring import rule_frequency
from ..helpers.snippets import load_code_snippet, suggest_remediation


def build_maintainability_section(context: dict, styles):
    job = context["job"]
    report = context["report"]
    smells = report.get("code_smell_details", [])
    top_smells = smells[:12]
    frequent_rules = rule_frequency(smells, limit=5)

    flowables = [
        Paragraph("Maintainability Analysis", styles["h1"]),
        Paragraph(
            f"The project currently reports <b>{getattr(job, 'sonar_code_smells', 0)}</b> code smells. The maintainability score is "
            f"<b>{context['scores']['maintainability']}%</b>, which reflects complexity hotspots, repeated literals, empty blocks, and structural cleanup opportunities.",
            styles["body"],
        ),
        Spacer(1, 3 * mm),
    ]

    if frequent_rules:
        flowables.append(Paragraph("Most Frequent Maintainability Rules", styles["h2"]))
        for rule, count in frequent_rules:
            flowables.append(Paragraph(f"• <b>{rule}</b> appeared {count} times.", styles["body"]))
        flowables.append(Spacer(1, 3 * mm))

    flowables.extend([
        Paragraph("Representative Code Smells", styles["h2"]),
        build_findings_table(top_smells, styles, max_rows=12) if top_smells else Paragraph("No code smell details were returned for this scan.", styles["muted"]),
    ])

    if top_smells:
        sample = next((item for item in top_smells if str(item.get("severity") or "").upper() in {"BLOCKER", "CRITICAL", "MAJOR"}), top_smells[0])
        fix = suggest_remediation(sample)
        snippet = load_code_snippet(job, sample.get("component"), sample.get("line"))
        flowables.extend(
            [
                Spacer(1, 4 * mm),
                Paragraph("Refactoring Preview", styles["h2"]),
                Paragraph(f"<b>Problematic snippet</b><br/><font face='Courier'>{(snippet or fix['bad']).replace(chr(10), '<br/>')}</font>", styles["muted"]),
                Spacer(1, 2 * mm),
                Paragraph(f"<b>Recommended direction</b><br/><font face='Courier'>{fix['good'].replace(chr(10), '<br/>')}</font>", styles["muted"]),
                Paragraph(fix["summary"], styles["body"]),
            ]
        )

    flowables.append(PageBreak())
    return flowables

