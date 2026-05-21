from __future__ import annotations

import os
from typing import Dict

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


PALETTE = {
    "navy": colors.HexColor("#0F172A"),
    "slate": colors.HexColor("#334155"),
    "muted": colors.HexColor("#64748B"),
    "border": colors.HexColor("#E2E8F0"),
    "surface": colors.HexColor("#F8FAFC"),
    "white": colors.white,
    "success": colors.HexColor("#16A34A"),
    "info": colors.HexColor("#2563EB"),
    "minor": colors.HexColor("#EAB308"),
    "major": colors.HexColor("#F97316"),
    "critical": colors.HexColor("#EF4444"),
    "blocker": colors.HexColor("#991B1B"),
}


def register_brand_fonts() -> Dict[str, str]:
    candidates = {
        "Inter": [
            r"C:\Windows\Fonts\Inter-Regular.ttf",
            r"C:\Windows\Fonts\Inter_24pt-Regular.ttf",
        ],
        "Poppins": [r"C:\Windows\Fonts\Poppins-Regular.ttf"],
        "Manrope": [r"C:\Windows\Fonts\Manrope-Regular.ttf"],
    }
    registered = {}
    for family, paths in candidates.items():
        for path in paths:
            if os.path.isfile(path):
                name = family
                if name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(name, path))
                registered["base"] = name
                return registered
    registered["base"] = "Helvetica"
    return registered


def build_styles():
    fonts = register_brand_fonts()
    base_font = fonts["base"]
    sample = getSampleStyleSheet()

    styles = {
        "title": ParagraphStyle(
            "ReportTitle",
            parent=sample["Title"],
            fontName=base_font,
            fontSize=22,
            leading=26,
            textColor=PALETTE["navy"],
            spaceAfter=10,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=sample["Heading1"],
            fontName=base_font,
            fontSize=16,
            leading=20,
            textColor=PALETTE["navy"],
            spaceAfter=10,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=sample["Heading2"],
            fontName=base_font,
            fontSize=13,
            leading=17,
            textColor=PALETTE["navy"],
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=sample["BodyText"],
            fontName=base_font,
            fontSize=9.5,
            leading=13,
            textColor=PALETTE["slate"],
        ),
        "muted": ParagraphStyle(
            "Muted",
            parent=sample["BodyText"],
            fontName=base_font,
            fontSize=8.5,
            leading=11.5,
            textColor=PALETTE["muted"],
        ),
        "small_center": ParagraphStyle(
            "SmallCenter",
            parent=sample["BodyText"],
            fontName=base_font,
            fontSize=8.5,
            leading=10,
            alignment=TA_CENTER,
            textColor=PALETTE["muted"],
        ),
        "card_value": ParagraphStyle(
            "CardValue",
            parent=sample["BodyText"],
            fontName=base_font,
            fontSize=17,
            leading=20,
            textColor=PALETTE["navy"],
            alignment=TA_CENTER,
        ),
        "card_label": ParagraphStyle(
            "CardLabel",
            parent=sample["BodyText"],
            fontName=base_font,
            fontSize=8.5,
            leading=10,
            alignment=TA_CENTER,
            textColor=PALETTE["muted"],
        ),
        "badge": ParagraphStyle(
            "Badge",
            parent=sample["BodyText"],
            fontName=base_font,
            fontSize=8.5,
            alignment=TA_CENTER,
            textColor=colors.white,
        ),
    }
    return styles


def severity_color(severity: str):
    normalized = (severity or "").upper()
    if normalized == "BLOCKER":
        return PALETTE["blocker"]
    if normalized == "CRITICAL":
        return PALETTE["critical"]
    if normalized == "MAJOR":
        return PALETTE["major"]
    if normalized == "MINOR":
        return PALETTE["minor"]
    return PALETTE["info"]

