"""PDF report exports (Phase 17): AR aging, P&L, and cash flow.

Same library choice and rationale as `app.services.invoice_pdf` --
reportlab, not weasyprint (pure-Python, no native pango/cairo dependency
chain; see that module's docstring for the full argument). This module
reuses the exact same header/table/totals visual language (dark-slate
header row, alternating row backgrounds, right-aligned numeric columns) so
a PDF export "matches" the existing invoice PDF rather than looking like a
bolted-on second design.

Each `render_*_pdf` function takes the SAME dict shape the corresponding
JSON API / CSV export already returns (`app.services.reports.ar_aging_report`
/ `pnl_report` / `cash_flow_report`) rather than re-querying the database,
so there is exactly one source of truth for the numbers across JSON, CSV,
and PDF -- this module only lays them out.
"""
from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_HEADER_BG = colors.HexColor("#0f172a")
_ROW_ALT_BG = colors.HexColor("#f8fafc")
_GRID_COLOR = colors.HexColor("#cbd5e1")


def _money(value: Decimal | float | int, currency: str = "USD") -> str:
    symbol = "$" if currency.upper() == "USD" else f"{currency.upper()} "
    return f"{symbol}{Decimal(value):,.2f}"


def _doc(buffer: io.BytesIO) -> SimpleDocTemplate:
    return SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )


def _title_elements(title: str, subtitle: str | None, styles) -> list[Any]:
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=18, spaceAfter=4
    )
    muted_style = ParagraphStyle(
        "ReportMuted", parent=styles["Normal"], textColor=colors.grey, spaceAfter=14
    )
    elements: list[Any] = [Paragraph(title, title_style)]
    if subtitle:
        elements.append(Paragraph(subtitle, muted_style))
    else:
        elements.append(Spacer(1, 0.15 * inch))
    return elements


def _styled_table(table_data: list[list[str]], col_widths: list[float]) -> Table:
    table = Table(table_data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("LINEABOVE", (0, -1), (-1, -1), 0.75, _HEADER_BG),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, _GRID_COLOR),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, _ROW_ALT_BG]),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ]
        )
    )
    return table


def render_ar_aging_pdf(report: dict[str, Any]) -> bytes:
    """`report` is the exact dict `app.services.reports.ar_aging_report` returns."""
    buffer = io.BytesIO()
    doc = _doc(buffer)
    styles = getSampleStyleSheet()

    as_of = report.get("as_of")
    as_of_str = as_of.strftime("%Y-%m-%d %H:%M UTC") if isinstance(as_of, datetime) else str(as_of)
    elements = _title_elements(
        "AR Aging Report", f"As of {as_of_str}", styles
    )

    header = ["Customer", "Current", "1-30", "31-60", "61-90", "90+", "Total", "Invoices"]
    table_data = [header]
    for c in report["customers"]:
        b = c["buckets"]
        table_data.append(
            [
                c["customer_name"],
                _money(b["current"]),
                _money(b["1_30"]),
                _money(b["31_60"]),
                _money(b["61_90"]),
                _money(b["90_plus"]),
                _money(c["total"]),
                str(c["invoice_count"]),
            ]
        )
    bt = report["bucket_totals"]
    table_data.append(
        [
            "TOTAL",
            _money(bt["current"]),
            _money(bt["1_30"]),
            _money(bt["31_60"]),
            _money(bt["61_90"]),
            _money(bt["90_plus"]),
            _money(report["grand_total"]),
            str(sum(c["invoice_count"] for c in report["customers"])),
        ]
    )
    if not report["customers"]:
        table_data.insert(1, ["(no outstanding balances)", "", "", "", "", "", "", ""])

    col_widths = [1.9 * inch, 0.7 * inch, 0.7 * inch, 0.7 * inch, 0.7 * inch, 0.7 * inch, 0.8 * inch, 0.7 * inch]
    elements.append(_styled_table(table_data, col_widths))
    doc.build(elements)
    return buffer.getvalue()


def render_pnl_pdf(report: dict[str, Any]) -> bytes:
    """`report` is the exact dict `app.services.reports.pnl_report` returns."""
    buffer = io.BytesIO()
    doc = _doc(buffer)
    styles = getSampleStyleSheet()

    subtitle = f"{report['start_date'].date()} to {report['end_date'].date()} &middot; cash-basis"
    elements = _title_elements("Profit &amp; Loss Report", subtitle, styles)

    header = ["Month", "Revenue", "Refunds", "Net Revenue", "Parts Cost", "Labor Cost", "Net"]
    table_data = [header]
    for m in report["months"]:
        table_data.append(
            [
                m["month"],
                _money(m["revenue"]),
                _money(m["refunds"]),
                _money(m["net_revenue"]),
                _money(m["parts_cost"]),
                _money(m["labor_cost"]) + ("*" if m["labor_cost_unavailable"] else ""),
                _money(m["net"]),
            ]
        )
    t = report["totals"]
    table_data.append(
        [
            "TOTAL",
            _money(t["revenue"]),
            _money(t["refunds"]),
            _money(t["net_revenue"]),
            _money(t["parts_cost"]),
            _money(t["labor_cost"]) + ("*" if t["labor_cost_unavailable"] else ""),
            _money(t["net"]),
        ]
    )
    if not report["months"]:
        table_data.insert(1, ["(no activity in this range)", "", "", "", "", "", ""])

    col_widths = [0.9 * inch, 1.0 * inch, 0.9 * inch, 1.05 * inch, 1.0 * inch, 1.0 * inch, 0.9 * inch]
    elements.append(_styled_table(table_data, col_widths))

    if t["labor_cost_unavailable"] or any(m["labor_cost_unavailable"] for m in report["months"]):
        elements.append(Spacer(1, 0.2 * inch))
        unrated = ", ".join(t.get("unrated_technicians", [])) or "unknown"
        elements.append(
            Paragraph(
                f"* Labor cost is incomplete: at least one technician has no hourly rate set "
                f"({unrated}), so their clocked hours are excluded from labor cost.",
                styles["Normal"],
            )
        )

    doc.build(elements)
    return buffer.getvalue()


def render_cash_flow_pdf(report: dict[str, Any]) -> bytes:
    """`report` is the exact dict `app.services.reports.cash_flow_report` returns."""
    buffer = io.BytesIO()
    doc = _doc(buffer)
    styles = getSampleStyleSheet()

    subtitle = f"{report['start_date'].date()} to {report['end_date'].date()}"
    elements = _title_elements("Cash Flow Report", subtitle, styles)

    header = ["Month", "Cash In", "Refunds Out", "Cost Incurred", "Net Cash"]
    table_data = [header]
    for m in report["months"]:
        table_data.append(
            [
                m["month"],
                _money(m["cash_in"]),
                _money(m["refunds_out"]),
                _money(m["cost_incurred"]),
                _money(m["net_cash"]),
            ]
        )
    t = report["totals"]
    table_data.append(
        [
            "TOTAL",
            _money(t["cash_in"]),
            _money(t["refunds_out"]),
            _money(t["cost_incurred"]),
            _money(t["net_cash"]),
        ]
    )
    if not report["months"]:
        table_data.insert(1, ["(no activity in this range)", "", "", "", ""])

    col_widths = [1.1 * inch, 1.3 * inch, 1.3 * inch, 1.4 * inch, 1.3 * inch]
    elements.append(_styled_table(table_data, col_widths))

    elements.append(Spacer(1, 0.2 * inch))
    elements.append(Paragraph(report["cost_incurred_caveat"], styles["Normal"]))

    doc.build(elements)
    return buffer.getvalue()


__all__ = ["render_ar_aging_pdf", "render_cash_flow_pdf", "render_pnl_pdf"]
