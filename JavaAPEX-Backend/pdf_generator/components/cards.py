from __future__ import annotations

from typing import Iterable, Sequence

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from ..styles.theme import PALETTE


def metric_card_table(metrics: Sequence[dict], styles, columns: int = 4, card_height: float = 26 * mm) -> Table:
    rows = []
    current = []
    for metric in metrics:
        label = Paragraph(metric["label"], styles["card_label"])
        value = Paragraph(metric["value"], styles["card_value"])
        accent = metric.get("accent", PALETTE["info"])
        card = Table(
            [[value], [label]],
            colWidths=[38 * mm],
            rowHeights=[card_height * 0.55, card_height * 0.45],
        )
        card.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 0.8, PALETTE["border"]),
                    ("LINEABOVE", (0, 0), (-1, 0), 4, accent),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        current.append(card)
        if len(current) == columns:
            rows.append(current)
            current = []
    if current:
        while len(current) < columns:
            current.append("")
        rows.append(current)
    table = Table(rows, hAlign="LEFT", colWidths=[42 * mm] * columns, spaceAfter=8)
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return table


def score_card_table(scores: Iterable[dict], styles, columns: int = 2) -> Table:
    cards = []
    for score in scores:
        headline = Paragraph(score["title"], styles["h2"])
        value = Paragraph(score["value"], styles["card_value"])
        detail = Paragraph(score["detail"], styles["muted"])
        card = Table([[headline], [value], [detail]], colWidths=[80 * mm])
        card.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                    ("BOX", (0, 0), (-1, -1), 0.8, PALETTE["border"]),
                    ("LINEBEFORE", (0, 0), (0, -1), 4, score.get("accent", PALETTE["info"])),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        cards.append(card)
    rows = [cards[index:index + columns] for index in range(0, len(cards), columns)]
    if rows and len(rows[-1]) < columns:
        rows[-1].extend([""] * (columns - len(rows[-1])))
    table = Table(rows, colWidths=[85 * mm] * columns, hAlign="LEFT", spaceAfter=10)
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return table

