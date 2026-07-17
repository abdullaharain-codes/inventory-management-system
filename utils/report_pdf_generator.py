"""
Generic A4 PDF report generator using fpdf2.
Returns PDF bytes — caller decides how to serve them.

Designed for tabular reports: title, optional subtitle, columnar data.
"""
from datetime import datetime
from fpdf import FPDF

from utils.company_info import get_company_info


_PKR = "Rs."


def _safe_str(val, fallback=""):
    if val is None:
        return fallback
    s = str(val).strip()
    return s if s else fallback


def _money(val):
    try:
        return f"{_PKR} {float(val or 0):,.2f}"
    except (ValueError, TypeError):
        return f"{_PKR} 0.00"


def _fmt_date(raw):
    if not raw:
        return "---"
    try:
        if isinstance(raw, str):
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(raw[:19], fmt).strftime("%B %d, %Y")
                except ValueError:
                    continue
        return str(raw)
    except Exception:
        return str(raw)


class _ReportPDF(FPDF):
    def __init__(self):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.set_auto_page_break(auto=False)

    def footer(self):
        pass


def generate_report_pdf(title, headers, rows, date_from=None, date_to=None,
                        subtitle=None, col_widths=None, money_cols=None,
                        right_align_cols=None):
    """Generate a styled A4 report PDF and return bytes.

    Parameters
    ----------
    title : str
        Report title (e.g. "Sales Report").
    headers : list[str]
        Column headers.
    rows : list[list]
        Row data — each inner list must match len(headers).
    date_from, date_to : str, optional
        Date range to show in subtitle.
    subtitle : str, optional
        Extra subtitle text (overrides date range if both provided).
    col_widths : list[float], optional
        Custom column widths in mm. If None, equal widths.
    money_cols : set[int], optional
        Column indices to format as money.
    right_align_cols : set[int], optional
        Column indices to right-align.
    """
    company = get_company_info()
    pdf = _ReportPDF()
    pdf.add_page()

    page_w = 210
    lm = 10
    rm = 10
    usable = page_w - lm - rm
    cursor_y = 10

    # ── HEADER ───────────────────────────────────────────────
    pdf.set_xy(lm, cursor_y)
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(usable, 7, _safe_str(company.get('company_name'), 'Inventory Management System'),
             ln=True, align="L")

    pdf.set_x(lm)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(107, 114, 128)
    addr = _safe_str(company.get('address'))
    if addr:
        pdf.cell(usable, 4.5, addr, ln=True)
        pdf.set_x(lm)
    phone = _safe_str(company.get('phone'))
    if phone:
        pdf.cell(usable, 4.5, f"Phone: {phone}", ln=True)
        pdf.set_x(lm)

    cursor_y = pdf.get_y() + 2

    # Separator
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.4)
    pdf.line(lm, cursor_y, page_w - rm, cursor_y)
    cursor_y += 5

    # ── TITLE ────────────────────────────────────────────────
    pdf.set_xy(lm, cursor_y)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(usable / 2, 9, title)

    # Date range on the right
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(107, 114, 128)
    date_label = ""
    if date_from and date_to:
        date_label = f"{_fmt_date(date_from)}  -  {_fmt_date(date_to)}"
    elif subtitle:
        date_label = subtitle
    if date_label:
        pdf.set_xy(lm + usable / 2, cursor_y)
        pdf.cell(usable / 2, 5, date_label, align="R")
    cursor_y = max(pdf.get_y(), cursor_y + 9) + 3
    pdf.set_text_color(0, 0, 0)

    # ── TABLE ────────────────────────────────────────────────
    n_cols = len(headers)
    if n_cols == 0:
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(107, 114, 128)
        pdf.set_xy(lm, cursor_y + 20)
        pdf.cell(usable, 10, "No data available", align="C")
        pdf.set_text_color(0, 0, 0)
        return bytes(pdf.output())
    if col_widths:
        widths = col_widths
    else:
        widths = [usable / n_cols] * n_cols

    row_h = 7
    money_cols = money_cols or set()
    right_align_cols = right_align_cols or set()

    # Header row
    pdf.set_xy(lm, cursor_y)
    pdf.set_fill_color(30, 41, 59)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    for i, hdr in enumerate(headers):
        align = "R" if i in right_align_cols else ("C" if i == 0 else "L")
        pdf.cell(widths[i], row_h, f"  {_safe_str(hdr)}" if i == 0 else _safe_str(hdr),
                 border=0, fill=True, align=align)
    pdf.ln(row_h)
    cursor_y = pdf.get_y()

    # Data rows
    pdf.set_text_color(30, 41, 59)
    for idx, row in enumerate(rows):
        if cursor_y + row_h > 280:
            pdf.add_page()
            cursor_y = 15
            # Re-draw header
            pdf.set_xy(lm, cursor_y)
            pdf.set_fill_color(30, 41, 59)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 8)
            for i, hdr in enumerate(headers):
                align = "R" if i in right_align_cols else ("C" if i == 0 else "L")
                pdf.cell(widths[i], row_h, f"  {_safe_str(hdr)}" if i == 0 else _safe_str(hdr),
                         border=0, fill=True, align=align)
            pdf.ln(row_h)
            cursor_y = pdf.get_y()
            pdf.set_text_color(30, 41, 59)

        if idx % 2 == 1:
            pdf.set_fill_color(243, 244, 246)
        else:
            pdf.set_fill_color(255, 255, 255)

        pdf.set_font("Helvetica", "", 8)
        pdf.set_xy(lm, cursor_y)
        for i, val in enumerate(row):
            display = _money(val) if i in money_cols else _safe_str(str(val) if val is not None else "")
            align = "R" if i in right_align_cols else ("C" if i == 0 else "L")
            pdf.cell(widths[i], row_h, f"  {display}" if i == 0 else display,
                     border=0, fill=True, align=align)
        pdf.ln(row_h)
        cursor_y = pdf.get_y()

    # ── FOOTER ───────────────────────────────────────────────
    footer_y = max(cursor_y + 10, 275)
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.3)
    pdf.line(lm, footer_y - 3, page_w - rm, footer_y - 3)

    pdf.set_xy(lm, footer_y)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(156, 163, 175)
    pdf.cell(usable, 5, f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", align="C")

    pdf.set_text_color(0, 0, 0)
    return bytes(pdf.output())
