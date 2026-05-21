from __future__ import annotations

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors

from ..styles.theme import PALETTE


def build_issue_distribution_chart(distribution: dict) -> Drawing:
    drawing = Drawing(220, 180)
    pie = Pie()
    pie.x = 25
    pie.y = 25
    pie.width = 120
    pie.height = 120
    pie.data = list(distribution.values()) or [1]
    pie.labels = list(distribution.keys()) or ["No Issues"]
    pie.sideLabels = True
    palette = [PALETTE["critical"], PALETTE["major"], PALETTE["info"], colors.HexColor("#F59E0B")]
    for index in range(len(pie.data)):
        pie.slices[index].fillColor = palette[index % len(palette)]
        pie.slices[index].strokeColor = colors.white
        pie.slices[index].popout = 2 if index == 0 else 0
    drawing.add(String(10, 165, "Issue Distribution", fontSize=11, fontName="Helvetica-Bold", fillColor=PALETTE["navy"]))
    drawing.add(pie)
    return drawing


def build_severity_distribution_chart(distribution: dict) -> Drawing:
    drawing = Drawing(260, 180)
    chart = VerticalBarChart()
    chart.x = 30
    chart.y = 35
    chart.height = 110
    chart.width = 190
    chart.data = [[distribution.get(key, 0) for key in ("BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO")]]
    chart.categoryAxis.categoryNames = ["Blocker", "Critical", "Major", "Minor", "Info"]
    chart.valueAxis.valueMin = 0
    chart.bars[0].fillColor = PALETTE["critical"]
    chart.barSpacing = 5
    chart.groupSpacing = 8
    drawing.add(String(10, 165, "Severity Distribution", fontSize=11, fontName="Helvetica-Bold", fillColor=PALETTE["navy"]))
    drawing.add(chart)
    return drawing


def build_progress_gauge(label: str, value: int, accent=PALETTE["info"]) -> Drawing:
    drawing = Drawing(165, 42)
    drawing.add(String(0, 31, label, fontSize=9, fontName="Helvetica-Bold", fillColor=PALETTE["navy"]))
    drawing.add(Rect(0, 12, 150, 10, fillColor=PALETTE["border"], strokeColor=PALETTE["border"], rx=5, ry=5))
    drawing.add(Rect(0, 12, max(0, min(150, int(150 * (value / 100)))), 10, fillColor=accent, strokeColor=accent, rx=5, ry=5))
    drawing.add(String(130, 30, f"{value}%", fontSize=10, fontName="Helvetica-Bold", fillColor=accent))
    return drawing


def build_qr_code(url: str, size: int = 70) -> Drawing:
    widget = QrCodeWidget(url)
    bounds = widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    drawing = Drawing(size, size)
    scale_x = size / width
    scale_y = size / height
    widget.scale(scale_x, scale_y)
    drawing.add(widget)
    return drawing

