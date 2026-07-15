"""
PDF invoice generator using fpdf2.
Returns PDF bytes — caller decides how to serve them.

Supports two formats:
  - 'a4'          : standard A4 paper (default)
  - 'thermal_80mm': compact 80mm POS-style receipt with dynamic height
"""
import os
from datetime import datetime
from fpdf import FPDF


_PKR = "Rs."  # Pakistani Rupee (fpdf2 Helvetica cannot encode Unicode ₨)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_str(val, fallback=""):
    if val is None:
        return fallback
    s = str(val).strip()
    return s if s else fallback


def _fmt_date(raw):
    """Format a date string into a human-readable form."""
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


def _fmt_date_short(raw):
    """Short date for thermal receipt."""
    if not raw:
        return "---"
    try:
        if isinstance(raw, str):
            for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
                try:
                    return datetime.strptime(raw[:19], fmt).strftime("%d/%m/%Y")
                except ValueError:
                    continue
        return str(raw)
    except Exception:
        return str(raw)


def _money(val):
    """Format a number as Rs. X,XXX.XX"""
    try:
        return f"{_PKR} {float(val or 0):,.2f}"
    except (ValueError, TypeError):
        return f"{_PKR} 0.00"


def _draw_dashed_line(pdf, x1, y, x2):
    """Draw a dashed horizontal line using short segments."""
    pdf.set_draw_color(150, 150, 150)
    pdf.set_line_width(0.3)
    seg = 2
    gap = 1.5
    x = x1
    while x < x2:
        end = min(x + seg, x2)
        pdf.line(x, y, end, y)
        x = end + gap


# ── Thermal 80mm receipt ─────────────────────────────────────────────────────

def _generate_thermal(bill_data, company_info):
    """Generate a compact POS-style receipt on 80mm-wide paper."""
    page_w = 80
    margin = 3
    usable = page_w - 2 * margin  # 74 mm

    # ── Pre-compute content height ──────────────────────────────
    h = 0
    # Header block
    h += 6  # company name
    addr = _safe_str(company_info.get('address'))
    if addr:
        # estimate lines: ~25 chars per line at 7pt on 74mm
        nlines = max(1, -(-len(addr) // 25))
        h += nlines * 3.5 + 1
    phone = _safe_str(company_info.get('phone'))
    if phone:
        h += 4
    gst = company_info.get('gst_number')
    if gst:
        h += 4
    h += 3  # gap after header
    h += 2  # dashed line
    h += 4  # bill number
    h += 4  # date
    cust_name = _safe_str(bill_data.get('customer_name'))
    cust_phone = _safe_str(bill_data.get('customer_phone'))
    if cust_name:
        h += 4
    if cust_phone:
        h += 4
    h += 2  # dashed line
    # Items
    items = bill_data.get('items', [])
    for item in items:
        pname = _safe_str(item.get('product_name'), 'Item')
        h += 4  # product name line
        h += 4  # qty x price  = total line
    h += 2  # dashed line
    # Totals
    h += 5  # subtotal
    disc_pct = float(bill_data.get('discount_percent') or 0)
    gst_pct = float(bill_data.get('gst_percent') or 0)
    if disc_pct > 0:
        h += 5
    if gst_pct > 0:
        h += 5
    h += 6  # grand total
    h += 2  # dashed line
    h += 5  # payment method
    h += 5  # payment status
    h += 2  # dashed line
    h += 12  # thank you + timestamp
    h += 15  # bottom buffer

    # Create PDF with dynamic height
    pdf = FPDF(orientation='P', unit='mm', format=(page_w, h))
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    cx = margin
    cy = 4

    # ── Header ──────────────────────────────────────────────────
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_xy(cx, cy)
    pdf.cell(usable, 5, _safe_str(company_info.get('company_name'), 'Shop'), align="C", ln=True)
    cy = pdf.get_y()

    pdf.set_font("Helvetica", "", 7)
    if addr:
        pdf.set_xy(cx, cy)
        pdf.multi_cell(usable, 3.5, addr, align="C")
        cy = pdf.get_y()
    if phone:
        pdf.set_xy(cx, cy)
        pdf.cell(usable, 3.5, phone, align="C", ln=True)
        cy = pdf.get_y()
    if gst:
        pdf.set_xy(cx, cy)
        pdf.cell(usable, 3.5, f"GST: {gst}", align="C", ln=True)
        cy = pdf.get_y()

    cy += 3
    _draw_dashed_line(pdf, cx, cy, cx + usable)
    cy += 3

    # ── Bill info ───────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 7)
    pdf.set_xy(cx, cy)
    pdf.cell(usable, 3.5, f"Bill: {_safe_str(bill_data.get('bill_number'), '---')}", ln=True)
    cy = pdf.get_y()
    pdf.set_xy(cx, cy)
    pdf.cell(usable, 3.5, f"Date: {_fmt_date_short(bill_data.get('bill_date'))}", ln=True)
    cy = pdf.get_y()

    if cust_name:
        pdf.set_xy(cx, cy)
        pdf.cell(usable, 3.5, f"Cust: {cust_name}", ln=True)
        cy = pdf.get_y()
    if cust_phone:
        pdf.set_xy(cx, cy)
        pdf.cell(usable, 3.5, f"Ph: {cust_phone}", ln=True)
        cy = pdf.get_y()

    cy += 1
    _draw_dashed_line(pdf, cx, cy, cx + usable)
    cy += 3

    # ── Items ───────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 7)
    for idx, item in enumerate(items):
        pname = _safe_str(item.get('product_name'), f"Item #{idx+1}")
        qty = item.get('quantity', 0)
        up = _money(item.get('unit_price', 0))
        total = _money(item.get('item_total', 0))

        pdf.set_xy(cx, cy)
        pdf.cell(usable, 3.5, pname, ln=True)
        cy = pdf.get_y()

        pdf.set_xy(cx, cy)
        pdf.cell(usable / 2, 3.5, f"  {qty} x {up}", align="L")
        pdf.set_xy(cx + usable / 2, cy)
        pdf.cell(usable / 2, 3.5, total, align="R")
        pdf.ln(3.5)
        cy = pdf.get_y()

    _draw_dashed_line(pdf, cx, cy, cx + usable)
    cy += 3

    # ── Totals ──────────────────────────────────────────────────
    pdf.set_font("Helvetica", "", 7)

    def _thermal_row(label, value, cy):
        pdf.set_xy(cx, cy)
        pdf.cell(usable / 2, 4, label, align="L")
        pdf.set_xy(cx + usable / 2, cy)
        pdf.cell(usable / 2, 4, value, align="R")
        return cy + 4

    cy = _thermal_row("Subtotal:", _money(bill_data.get('subtotal')), cy)

    if disc_pct > 0:
        cy = _thermal_row(f"Discount ({disc_pct}%):", f"-{_money(bill_data.get('discount_amount'))}", cy)
    if gst_pct > 0:
        cy = _thermal_row(f"GST ({gst_pct}%):", f"+{_money(bill_data.get('gst_amount'))}", cy)

    # Grand total — bold
    pdf.set_font("Helvetica", "B", 8)
    cy = _thermal_row("TOTAL:", _money(bill_data.get('grand_total')), cy)
    pdf.set_font("Helvetica", "", 7)

    _draw_dashed_line(pdf, cx, cy, cx + usable)
    cy += 3

    # ── Payment ─────────────────────────────────────────────────
    payment_method = _safe_str(bill_data.get('payment_method'), 'cash').capitalize()
    payment_status = _safe_str(bill_data.get('payment_status'), 'paid').upper()

    pdf.set_xy(cx, cy)
    pdf.cell(usable, 4, f"Payment: {payment_method}", ln=True)
    cy = pdf.get_y()

    pdf.set_xy(cx, cy)
    pdf.cell(usable, 4, f"Status: {payment_status}", ln=True)
    cy = pdf.get_y()

    _draw_dashed_line(pdf, cx, cy, cx + usable)
    cy += 3

    # ── Footer ──────────────────────────────────────────────────
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(120, 120, 120)
    pdf.set_xy(cx, cy)
    pdf.cell(usable, 4, "Thank you for your business!", align="C", ln=True)
    cy = pdf.get_y()
    pdf.set_font("Helvetica", "", 6)
    pdf.set_xy(cx, cy)
    pdf.cell(usable, 3, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), align="C")

    pdf.set_text_color(0, 0, 0)
    return bytes(pdf.output())


# ── A4 layout ────────────────────────────────────────────────────────────────

def _generate_a4(bill_data, company_info):
    """Generate a standard A4 invoice."""
    from fpdf import FPDF as _FPDF

    class _InvoicePDF(_FPDF):
        def __init__(self):
            super().__init__(orientation='P', unit='mm', format='A4')
            self.set_auto_page_break(auto=False)
        def footer(self):
            pass

    pdf = _InvoicePDF()
    pdf.add_page()
    page_w = 210
    lm = 10
    rm = 10
    usable = page_w - lm - rm
    cursor_x = lm
    cursor_y = 10

    # ── 1. HEADER ───────────────────────────────────────────────
    logo_h = 0
    logo_w = 0
    logo_path = company_info.get('logo_path')
    if logo_path:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_logo = os.path.join(project_root, logo_path)
        if os.path.isfile(full_logo):
            try:
                logo_w = 30
                logo_h = 25
                pdf.image(full_logo, x=lm, y=cursor_y, h=logo_h)
            except Exception:
                logo_h = 0

    info_x = lm + logo_w + 4 if logo_h else lm
    info_w = usable - logo_w - 4 if logo_h else usable

    pdf.set_xy(info_x, cursor_y)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(info_w, 7, _safe_str(company_info.get('company_name'), 'Inventory Management System'),
             ln=True, align="R" if logo_h else "L")

    pdf.set_x(info_x)
    pdf.set_font("Helvetica", "", 9)
    addr = _safe_str(company_info.get('address'))
    if addr:
        pdf.cell(info_w, 4.5, addr, ln=True, align="R" if logo_h else "L")
        pdf.set_x(info_x)

    phone = _safe_str(company_info.get('phone'))
    if phone:
        pdf.cell(info_w, 4.5, f"Phone: {phone}", ln=True, align="R" if logo_h else "L")
        pdf.set_x(info_x)

    gst = company_info.get('gst_number')
    if gst:
        pdf.cell(info_w, 4.5, f"GST: {gst}", ln=True, align="R" if logo_h else "L")
        pdf.set_x(info_x)

    tagline = _safe_str(company_info.get('tagline'))
    if tagline:
        pdf.set_font("Helvetica", "I", 8)
        pdf.cell(info_w, 4.5, tagline, ln=True, align="R" if logo_h else "L")

    cursor_y = max(pdf.get_y(), cursor_y + logo_h) + 2

    # Separator
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.4)
    pdf.line(lm, cursor_y, page_w - rm, cursor_y)
    cursor_y += 5

    # ── 2. INVOICE title ────────────────────────────────────────
    has_gst = bool(company_info.get('gst_number'))
    title_text = "TAX INVOICE" if has_gst else "INVOICE"

    pdf.set_xy(lm, cursor_y)
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(30, 41, 59)
    pdf.cell(usable / 2, 9, title_text)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(107, 114, 128)
    pdf.set_xy(lm + usable / 2, cursor_y)
    pdf.cell(usable / 2, 5, f"Invoice #: {_safe_str(bill_data.get('bill_number'), '---')}", ln=True, align="R")
    pdf.set_x(lm + usable / 2)
    pdf.cell(usable / 2, 5, f"Date: {_fmt_date(bill_data.get('bill_date'))}", align="R")
    cursor_y = max(pdf.get_y(), cursor_y + 9) + 3
    pdf.set_text_color(0, 0, 0)

    # ── 3. CUSTOMER ─────────────────────────────────────────────
    cust_name = _safe_str(bill_data.get('customer_name'))
    cust_phone = _safe_str(bill_data.get('customer_phone'))
    if cust_name or cust_phone:
        pdf.set_xy(lm, cursor_y)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(usable, 5, "Bill To:")
        cursor_y = pdf.get_y() + 5.5
        if cust_name:
            pdf.set_xy(lm, cursor_y)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(usable, 5, cust_name)
            cursor_y += 5
        if cust_phone:
            pdf.set_xy(lm, cursor_y)
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(usable, 4.5, cust_phone)
            cursor_y += 5
        cursor_y += 2

    # ── 4. ITEMS TABLE ──────────────────────────────────────────
    col_widths = [82, 22, 40, 46]
    headers = ["Item", "Qty", "Unit Price", "Total"]
    row_h = 7

    pdf.set_xy(lm, cursor_y)
    pdf.set_fill_color(30, 41, 59)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    for i, hdr in enumerate(headers):
        align = "R" if i >= 2 else ("C" if i == 1 else "L")
        pdf.cell(col_widths[i], row_h, f"  {hdr}" if i == 0 else hdr,
                 border=0, fill=True, align=align)
    pdf.ln(row_h)
    cursor_y = pdf.get_y()

    items = bill_data.get('items', [])
    pdf.set_text_color(30, 41, 59)
    for idx, item in enumerate(items):
        if cursor_y + row_h > 285:
            pdf.add_page()
            cursor_y = 15
            pdf.set_xy(lm, cursor_y)
            pdf.set_fill_color(30, 41, 59)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 9)
            for i, hdr in enumerate(headers):
                align = "R" if i >= 2 else ("C" if i == 1 else "L")
                pdf.cell(col_widths[i], row_h, f"  {hdr}" if i == 0 else hdr,
                         border=0, fill=True, align=align)
            pdf.ln(row_h)
            cursor_y = pdf.get_y()
            pdf.set_text_color(30, 41, 59)

        if idx % 2 == 1:
            pdf.set_fill_color(243, 244, 246)
            fill = True
        else:
            pdf.set_fill_color(255, 255, 255)
            fill = True

        pdf.set_font("Helvetica", "", 9)
        pdf.set_xy(lm, cursor_y)

        product_name = _safe_str(item.get('product_name'), f"Item #{idx+1}")
        qty = str(item.get('quantity', ''))
        unit_price = _money(item.get('unit_price', 0))
        item_total = _money(item.get('item_total', 0))

        pdf.cell(col_widths[0], row_h, f"  {product_name}", border=0, fill=fill)
        pdf.cell(col_widths[1], row_h, qty, border=0, fill=fill, align="C")
        pdf.cell(col_widths[2], row_h, unit_price, border=0, fill=fill, align="R")
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(col_widths[3], row_h, item_total, border=0, fill=fill, align="R")
        pdf.ln(row_h)
        cursor_y = pdf.get_y()

    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.3)
    pdf.line(lm, cursor_y, page_w - rm, cursor_y)
    cursor_y += 5

    # ── 5. TOTALS ───────────────────────────────────────────────
    total_label_w = 70
    total_val_w = 50
    total_x = page_w - rm - total_label_w - total_val_w

    def _totals_row(label, value, bold=False, color=None, skip=False):
        nonlocal cursor_y
        if skip:
            return
        if color:
            pdf.set_text_color(*color)
        pdf.set_font("Helvetica", "B" if bold else "", 10)
        pdf.set_xy(total_x, cursor_y)
        pdf.cell(total_label_w, 6, label, align="R")
        pdf.set_xy(total_x + total_label_w, cursor_y)
        pdf.cell(total_val_w, 6, value, align="R")
        if color:
            pdf.set_text_color(0, 0, 0)
        cursor_y += 6

    disc_pct = float(bill_data.get('discount_percent') or 0)
    gst_pct = float(bill_data.get('gst_percent') or 0)

    _totals_row("Subtotal:", _money(bill_data.get('subtotal')))
    _totals_row(f"Discount ({disc_pct}%):", f"-{_money(bill_data.get('discount_amount'))}",
                color=(220, 38, 38), skip=(disc_pct <= 0))
    _totals_row(f"GST ({gst_pct}%):", f"+{_money(bill_data.get('gst_amount'))}",
                color=(5, 150, 105), skip=(gst_pct <= 0))

    cursor_y += 1

    pdf.set_draw_color(30, 41, 59)
    pdf.set_line_width(0.5)
    box_h = 9
    pdf.rect(total_x, cursor_y, total_label_w + total_val_w, box_h)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(30, 41, 59)
    pdf.set_xy(total_x, cursor_y + 1)
    pdf.cell(total_label_w, 7, "Grand Total:", align="R")
    pdf.set_xy(total_x + total_label_w, cursor_y + 1)
    pdf.cell(total_val_w, 7, _money(bill_data.get('grand_total')), align="R")
    pdf.set_text_color(0, 0, 0)
    cursor_y += box_h + 5

    # ── 6. PAYMENT INFO ─────────────────────────────────────────
    payment_method = _safe_str(bill_data.get('payment_method'), 'cash').capitalize()
    payment_status = _safe_str(bill_data.get('payment_status'), 'paid')

    pdf.set_xy(lm, cursor_y)
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(usable, 5.5, f"Payment Method: {payment_method}")
    cursor_y += 5.5

    pdf.set_xy(lm, cursor_y)
    pdf.set_font("Helvetica", "B", 10)
    if payment_status.lower() == 'paid':
        pdf.set_text_color(5, 150, 105)
        status_label = "PAID"
    else:
        pdf.set_text_color(217, 119, 6)
        status_label = "PENDING"
    pdf.cell(usable, 5.5, f"Payment Status: {status_label}")
    pdf.set_text_color(0, 0, 0)
    cursor_y += 8

    # ── 7. NOTES ────────────────────────────────────────────────
    notes = _safe_str(bill_data.get('notes'))
    if notes:
        pdf.set_xy(lm, cursor_y)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(usable, 5, "Notes:")
        cursor_y += 5
        pdf.set_xy(lm, cursor_y)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(107, 114, 128)
        pdf.multi_cell(usable, 4.5, notes)
        pdf.set_text_color(0, 0, 0)
        cursor_y = pdf.get_y() + 3

    # ── 8. FOOTER (dynamic, ~15mm below last content) ───────────
    footer_y = max(cursor_y + 15, 270)
    pdf.set_draw_color(180, 180, 180)
    pdf.set_line_width(0.3)
    pdf.line(lm, footer_y - 3, page_w - rm, footer_y - 3)

    pdf.set_xy(lm, footer_y)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(156, 163, 175)
    pdf.cell(usable, 5, "Thank you for your business!", align="C", ln=True)

    pdf.set_x(lm)
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(usable, 4, f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", align="C")

    return bytes(pdf.output())


# ── Public API ───────────────────────────────────────────────────────────────

def generate_invoice_pdf(bill_data, company_info):
    """Return a PDF invoice as *bytes*.

    Parameters
    ----------
    bill_data : dict
        Must match the structure returned by GET /api/bills/<id>.
    company_info : dict
        Must match the structure returned by get_company_info().
    """
    fmt = company_info.get('invoice_format', 'a4')
    if fmt == 'thermal_80mm':
        return _generate_thermal(bill_data, company_info)
    return _generate_a4(bill_data, company_info)
