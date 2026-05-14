from __future__ import annotations

from typing import Iterable, List

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from ..helpers.formatters import compact_path, format_timestamp, normalize_severity
from ..styles.theme import PALETTE, severity_color


def build_findings_table(findings: Iterable[dict], styles, max_rows: int | None = None) -> Table:
    data: List[list] = [[
        Paragraph("<b>Severity</b>", styles["body"]),
        Paragraph("<b>Issue</b>", styles["body"]),
        Paragraph("<b>File</b>", styles["body"]),
        Paragraph("<b>Rule</b>", styles["body"]),
        Paragraph("<b>Effort</b>", styles["body"]),
        Paragraph("<b>Status</b>", styles["body"]),
    ]]
    items = list(findings)
    if max_rows is not None:
        items = items[:max_rows]
    for item in items:
        data.append([
            Paragraph(normalize_severity(item.get("severity") or item.get("vulnerability_probability")), styles["body"]),
            Paragraph(str(item.get("message") or "N/A"), styles["body"]),
            Paragraph(compact_path(item.get("component")), styles["muted"]),
            Paragraph(str(item.get("rule") or "N/A"), styles["muted"]),
            Paragraph(str(item.get("effort") or item.get("debt") or "N/A"), styles["muted"]),
            Paragraph(str(item.get("status") or "N/A"), styles["muted"]),
        ])

    table = Table(
        data,
        colWidths=[22 * mm, 70 * mm, 45 * mm, 26 * mm, 18 * mm, 20 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), PALETTE["surface"]),
        ("BOX", (0, 0), (-1, -1), 0.7, PALETTE["border"]),
        ("INNERGRID", (0, 0), (-1, -1), 0.4, PALETTE["border"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for row_index in range(1, len(data)):
        background = colors.white if row_index % 2 else colors.HexColor("#FCFDFE")
        commands.append(("BACKGROUND", (0, row_index), (-1, row_index), background))
        if row_index < len(data):
            severity = normalize_severity(items[row_index - 1].get("severity") or items[row_index - 1].get("vulnerability_probability"))
            commands.append(("TEXTCOLOR", (0, row_index), (0, row_index), severity_color(severity)))
    table.setStyle(TableStyle(commands))
    return table


def build_metadata_table(entries: list[tuple[str, str]], styles) -> Table:
    rows = []
    for label, value in entries:
        rows.append([
            Paragraph(f"<b>{label}</b>", styles["body"]),
            Paragraph(value, styles["body"]),
        ])
    table = Table(rows, colWidths=[42 * mm, 125 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.7, PALETTE["border"]),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, PALETTE["border"]),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    return table

