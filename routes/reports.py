import csv
import io
from datetime import datetime
from flask import Blueprint, request, jsonify, Response
from db.connection import get_db_connection
from mysql.connector import Error
from middleware.auth_middleware import roles_required

reports_bp = Blueprint('reports', __name__)

VALID_GRANULARITIES = ('daily', 'weekly', 'monthly', 'yearly')


def _parse_dates(args):
    """Extract and validate date_from, date_to from request args."""
    date_from = args.get('date_from', '').strip()
    date_to = args.get('date_to', '').strip()
    if not date_from or not date_to:
        return None, None, 'date_from and date_to are required'
    try:
        datetime.strptime(date_from, '%Y-%m-%d')
        datetime.strptime(date_to, '%Y-%m-%d')
    except ValueError:
        return None, None, 'Invalid date format. Use YYYY-MM-DD'
    if date_from > date_to:
        return None, None, 'date_from must be before or equal to date_to'
    return date_from, date_to, None


def _get_conn():
    conn = get_db_connection()
    if not conn:
        return None
    return conn


def _get_stock_report_data(cur, date_from, date_to, product_id_filter=None):
    """Shared logic for stock report queries.

    Returns (period_summary, by_product, movement_breakdown).
    ``cur`` must be a dictionary cursor.
    """
    if product_id_filter:
        prod_filter_sql = 'AND sl.product_id = %s'
        prod_filter_params = (product_id_filter,)
    else:
        prod_filter_sql = ''
        prod_filter_params = ()

    # Opening stock: latest entry BEFORE date_from
    cur.execute(f"""
        SELECT sl.product_id,
               p.name AS product_name,
               sl.quantity_before AS opening_stock
        FROM stock_ledger sl
        JOIN products p ON p.product_id = sl.product_id
        INNER JOIN (
            SELECT product_id, MAX(ledger_id) AS max_ledger
            FROM stock_ledger
            WHERE DATE(created_at) < %s
            GROUP BY product_id
        ) latest ON sl.ledger_id = latest.max_ledger
        WHERE 1=1 {prod_filter_sql}
    """, (date_from,) + prod_filter_params)
    opening_rows = {r['product_id']: r for r in cur.fetchall()}

    # Fallback: earliest-ever entry for products with no pre-date_from history
    cur.execute(f"""
        SELECT sl.product_id,
               sl.quantity_before AS opening_stock
        FROM stock_ledger sl
        INNER JOIN (
            SELECT product_id, MIN(ledger_id) AS min_ledger
            FROM stock_ledger
            GROUP BY product_id
        ) first ON sl.ledger_id = first.min_ledger
        WHERE sl.product_id NOT IN (
            SELECT product_id FROM stock_ledger WHERE DATE(created_at) < %s
        )
        {prod_filter_sql}
    """, (date_from,) + prod_filter_params)
    for r in cur.fetchall():
        if r['product_id'] not in opening_rows:
            opening_rows[r['product_id']] = {
                'product_id': r['product_id'],
                'product_name': '',
                'opening_stock': r['opening_stock'],
            }

    # Closing stock: latest entry at/before date_to
    cur.execute(f"""
        SELECT sl.product_id,
               sl.quantity_after AS closing_stock
        FROM stock_ledger sl
        INNER JOIN (
            SELECT product_id, MAX(ledger_id) AS max_ledger
            FROM stock_ledger
            WHERE DATE(created_at) <= %s
            GROUP BY product_id
        ) latest ON sl.ledger_id = latest.max_ledger
        WHERE 1=1 {prod_filter_sql}
    """, (date_to,) + prod_filter_params)
    closing_rows = {r['product_id']: r['closing_stock'] for r in cur.fetchall()}

    # In-period movements
    cur.execute(f"""
        SELECT sl.product_id,
               p.name AS product_name,
               COALESCE(SUM(CASE WHEN sl.quantity_change > 0 THEN sl.quantity_change ELSE 0 END), 0) AS stock_in,
               COALESCE(SUM(CASE WHEN sl.quantity_change < 0 THEN ABS(sl.quantity_change) ELSE 0 END), 0) AS stock_out
        FROM stock_ledger sl
        LEFT JOIN products p ON p.product_id = sl.product_id
        WHERE DATE(sl.created_at) BETWEEN %s AND %s
        {prod_filter_sql}
        GROUP BY sl.product_id, p.name
    """, (date_from, date_to) + prod_filter_params)
    movement_rows = cur.fetchall()

    # Build by_product
    all_product_ids = (
        set(opening_rows.keys())
        | set(closing_rows.keys())
        | set(r['product_id'] for r in movement_rows)
    )
    by_product = []
    total_in = 0
    total_out = 0
    for pid in sorted(all_product_ids):
        o = opening_rows.get(pid, {})
        c = closing_rows.get(pid, 0)
        m = next((r for r in movement_rows if r['product_id'] == pid), None)
        stock_in = m['stock_in'] if m else 0
        stock_out = m['stock_out'] if m else 0
        opening = o.get('opening_stock', 0) or 0
        name = o.get('product_name', '') or (m['product_name'] if m else '')
        expected_closing = opening + stock_in - stock_out
        by_product.append({
            'product_id': pid,
            'product_name': name,
            'opening_stock': opening,
            'stock_in': stock_in,
            'stock_out': stock_out,
            'closing_stock': c,
            'reconciled': (expected_closing == c),
        })
        total_in += stock_in
        total_out += stock_out

    # Movement breakdown
    cur.execute(f"""
        SELECT movement_type,
               COUNT(*) AS count,
               SUM(ABS(quantity_change)) AS total_quantity
        FROM stock_ledger sl
        WHERE DATE(sl.created_at) BETWEEN %s AND %s
        {prod_filter_sql}
        GROUP BY movement_type
        ORDER BY total_quantity DESC
    """, (date_from, date_to) + prod_filter_params)
    movement_breakdown = cur.fetchall()

    opening_total = sum(r['opening_stock'] for r in by_product)
    closing_total = sum(r['closing_stock'] for r in by_product)
    period_summary = {
        'total_stock_in': total_in,
        'total_stock_out': total_out,
        'net_change': total_in - total_out,
        'opening_stock_total': opening_total,
        'closing_stock_total': closing_total,
    }

    return period_summary, by_product, movement_breakdown


# ── Sales Report ──────────────────────────────────────────────────
@reports_bp.route('/api/reports/sales', methods=['GET'])
@roles_required('admin', 'manager')
def sales_report():
    date_from, date_to, err = _parse_dates(request.args)
    if err:
        return jsonify({'error': err}), 400

    granularity = request.args.get('granularity', 'daily').lower()
    if granularity not in VALID_GRANULARITIES:
        return jsonify({'error': f'granularity must be one of: {", ".join(VALID_GRANULARITIES)}'}), 400

    conn = _get_conn()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cur = conn.cursor(dictionary=True)

        # ── Period summary ──
        cur.execute("""
            SELECT COALESCE(SUM(grand_total), 0) AS total_revenue,
                   COUNT(*) AS total_bills,
                   COALESCE(SUM(discount_amount), 0) AS total_discount,
                   COALESCE(SUM(gst_amount), 0) AS total_gst,
                   COALESCE(SUM(subtotal), 0) AS total_subtotal
            FROM bills
            WHERE bill_date BETWEEN %s AND %s
        """, (date_from, date_to))
        ps = cur.fetchone()
        ps['avg_bill_value'] = round(ps['total_revenue'] / ps['total_bills'], 2) if ps['total_bills'] > 0 else 0
        ps['date_from'] = date_from
        ps['date_to'] = date_to

        # ── Time series ──
        if granularity == 'daily':
            group_expr = 'bill_date'
            label_expr = 'DATE_FORMAT(bill_date, "%Y-%m-%d")'
        elif granularity == 'weekly':
            group_expr = 'YEARWEEK(bill_date, 1)'
            label_expr = 'CONCAT(YEAR(bill_date), "-W", LPAD(WEEK(bill_date, 1), 2, "0"))'
        elif granularity == 'monthly':
            group_expr = 'DATE_FORMAT(bill_date, "%Y-%m")'
            label_expr = 'DATE_FORMAT(bill_date, "%Y-%m")'
        else:  # yearly
            group_expr = 'YEAR(bill_date)'
            label_expr = 'YEAR(bill_date)'

        cur.execute(f"""
            SELECT {label_expr} AS period_label,
                   MIN(bill_date) AS period_start,
                   MAX(bill_date) AS period_end,
                   COALESCE(SUM(grand_total), 0) AS revenue,
                   COUNT(*) AS bill_count,
                   COALESCE(SUM(discount_amount), 0) AS discount,
                   COALESCE(SUM(gst_amount), 0) AS gst
            FROM bills
            WHERE bill_date BETWEEN %s AND %s
            GROUP BY {group_expr}
            ORDER BY MIN(bill_date)
        """, (date_from, date_to))
        time_series = cur.fetchall()

        # ── Top 10 products by revenue ──
        cur.execute("""
            SELECT bi.product_id,
                   COALESCE(bi.product_name, p.name) AS product_name,
                   SUM(bi.quantity) AS quantity_sold,
                   SUM(bi.item_total) AS revenue
            FROM bill_items bi
            JOIN bills b ON b.bill_id = bi.bill_id
            LEFT JOIN products p ON p.product_id = bi.product_id
            WHERE b.bill_date BETWEEN %s AND %s
            GROUP BY bi.product_id, COALESCE(bi.product_name, p.name)
            ORDER BY revenue DESC
            LIMIT 10
        """, (date_from, date_to))
        top_products = cur.fetchall()

        # ── Payment method breakdown ──
        cur.execute("""
            SELECT payment_method,
                   COUNT(*) AS count,
                   COALESCE(SUM(grand_total), 0) AS revenue
            FROM bills
            WHERE bill_date BETWEEN %s AND %s
            GROUP BY payment_method
            ORDER BY revenue DESC
        """, (date_from, date_to))
        payment_breakdown = cur.fetchall()

        cur.close()
        return jsonify({
            'period_summary': ps,
            'time_series': time_series,
            'top_products': top_products,
            'payment_method_breakdown': payment_breakdown
        }), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ── Stock / Inventory Movement Report ─────────────────────────────
@reports_bp.route('/api/reports/stock', methods=['GET'])
@roles_required('admin', 'manager')
def stock_report():
    date_from, date_to, err = _parse_dates(request.args)
    if err:
        return jsonify({'error': err}), 400

    product_id_filter = request.args.get('product_id')
    if product_id_filter:
        try:
            product_id_filter = int(product_id_filter)
        except (ValueError, TypeError):
            return jsonify({'error': 'product_id must be an integer'}), 400

    conn = _get_conn()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cur = conn.cursor(dictionary=True)
        period_summary, by_product, movement_breakdown = _get_stock_report_data(
            cur, date_from, date_to, product_id_filter
        )
        cur.close()
        return jsonify({
            'period_summary': period_summary,
            'by_product': by_product,
            'movement_breakdown': movement_breakdown
        }), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ── Profit Report ─────────────────────────────────────────────────
@reports_bp.route('/api/reports/profit', methods=['GET'])
@roles_required('admin', 'manager')
def profit_report():
    date_from, date_to, err = _parse_dates(request.args)
    if err:
        return jsonify({'error': err}), 400

    conn = _get_conn()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cur = conn.cursor(dictionary=True)

        # Per-product profit (only products with cost_price)
        cur.execute("""
            SELECT bi.product_id,
                   COALESCE(bi.product_name, p.name) AS product_name,
                   SUM(bi.quantity) AS quantity_sold,
                   SUM(bi.item_total) AS revenue,
                   SUM(bi.quantity * p.cost_price) AS cost,
                   SUM(bi.item_total - bi.quantity * p.cost_price) AS profit
            FROM bill_items bi
            JOIN bills b ON b.bill_id = bi.bill_id
            JOIN products p ON p.product_id = bi.product_id
            WHERE b.bill_date BETWEEN %s AND %s
              AND p.cost_price IS NOT NULL
            GROUP BY bi.product_id, COALESCE(bi.product_name, p.name)
            ORDER BY profit DESC
        """, (date_from, date_to))
        by_product = cur.fetchall()

        # Calculate margin_percent per product
        for row in by_product:
            if row['revenue'] and row['revenue'] > 0:
                row['margin_percent'] = round(float(row['profit']) / float(row['revenue']) * 100, 2)
            else:
                row['margin_percent'] = 0

        total_revenue = sum(float(r['revenue']) for r in by_product)
        total_cost = sum(float(r['cost']) for r in by_product)
        total_profit = sum(float(r['profit']) for r in by_product)
        avg_margin = round(total_profit / total_revenue * 100, 2) if total_revenue > 0 else 0

        # Count distinct products sold with NULL cost_price
        cur.execute("""
            SELECT COUNT(DISTINCT bi.product_id) AS excluded_count
            FROM bill_items bi
            JOIN bills b ON b.bill_id = bi.bill_id
            JOIN products p ON p.product_id = bi.product_id
            WHERE b.bill_date BETWEEN %s AND %s
              AND p.cost_price IS NULL
        """, (date_from, date_to))
        excluded = cur.fetchone()['excluded_count']

        period_summary = {
            'total_revenue': round(total_revenue, 2),
            'total_cost': round(total_cost, 2),
            'total_profit': round(total_profit, 2),
            'avg_margin_percent': avg_margin,
            'products_excluded_no_cost_price': excluded
        }

        cur.close()
        return jsonify({
            'period_summary': period_summary,
            'by_product': by_product
        }), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ── CSV: Sales Report ─────────────────────────────────────────────
@reports_bp.route('/api/reports/sales/csv', methods=['GET'])
@roles_required('admin', 'manager')
def sales_report_csv():
    date_from, date_to, err = _parse_dates(request.args)
    if err:
        return jsonify({'error': err}), 400

    granularity = request.args.get('granularity', 'daily').lower()
    if granularity not in VALID_GRANULARITIES:
        return jsonify({'error': f'granularity must be one of: {", ".join(VALID_GRANULARITIES)}'}), 400

    conn = _get_conn()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cur = conn.cursor(dictionary=True)

        if granularity == 'daily':
            group_expr = 'bill_date'
            label_expr = 'DATE_FORMAT(bill_date, "%Y-%m-%d")'
        elif granularity == 'weekly':
            group_expr = 'YEARWEEK(bill_date, 1)'
            label_expr = 'CONCAT(YEAR(bill_date), "-W", LPAD(WEEK(bill_date, 1), 2, "0"))'
        elif granularity == 'monthly':
            group_expr = 'DATE_FORMAT(bill_date, "%Y-%m")'
            label_expr = 'DATE_FORMAT(bill_date, "%Y-%m")'
        else:
            group_expr = 'YEAR(bill_date)'
            label_expr = 'YEAR(bill_date)'

        cur.execute(f"""
            SELECT {label_expr} AS period_label,
                   MIN(bill_date) AS period_start,
                   MAX(bill_date) AS period_end,
                   COALESCE(SUM(grand_total), 0) AS revenue,
                   COUNT(*) AS bill_count,
                   COALESCE(SUM(discount_amount), 0) AS discount,
                   COALESCE(SUM(gst_amount), 0) AS gst
            FROM bills
            WHERE bill_date BETWEEN %s AND %s
            GROUP BY {group_expr}
            ORDER BY MIN(bill_date)
        """, (date_from, date_to))
        rows = cur.fetchall()
        cur.close()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['period_label', 'period_start', 'period_end', 'revenue', 'bill_count', 'discount', 'gst'])
        for r in rows:
            writer.writerow([r['period_label'], r['period_start'], r['period_end'],
                             r['revenue'], r['bill_count'], r['discount'], r['gst']])

        output = buf.getvalue()
        buf.close()
        filename = f"sales_report_{date_from}_to_{date_to}_{granularity}.csv"
        return Response(output, mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="{filename}"'})
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ── CSV: Stock Report ─────────────────────────────────────────────
@reports_bp.route('/api/reports/stock/csv', methods=['GET'])
@roles_required('admin', 'manager')
def stock_report_csv():
    date_from, date_to, err = _parse_dates(request.args)
    if err:
        return jsonify({'error': err}), 400

    conn = _get_conn()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cur = conn.cursor(dictionary=True)
        period_summary, by_product, movement_breakdown = _get_stock_report_data(
            cur, date_from, date_to
        )
        cur.close()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['product_id', 'product_name', 'opening_stock', 'stock_in', 'stock_out', 'closing_stock', 'reconciled'])
        for row in by_product:
            writer.writerow([
                row['product_id'], row['product_name'], row['opening_stock'],
                row['stock_in'], row['stock_out'], row['closing_stock'], row['reconciled']
            ])

        output = buf.getvalue()
        buf.close()
        filename = f"stock_report_{date_from}_to_{date_to}.csv"
        return Response(output, mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="{filename}"'})
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ── CSV: Profit Report ────────────────────────────────────────────
@reports_bp.route('/api/reports/profit/csv', methods=['GET'])
@roles_required('admin', 'manager')
def profit_report_csv():
    date_from, date_to, err = _parse_dates(request.args)
    if err:
        return jsonify({'error': err}), 400

    conn = _get_conn()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cur = conn.cursor(dictionary=True)

        cur.execute("""
            SELECT bi.product_id,
                   COALESCE(bi.product_name, p.name) AS product_name,
                   SUM(bi.quantity) AS quantity_sold,
                   SUM(bi.item_total) AS revenue,
                   SUM(bi.quantity * p.cost_price) AS cost,
                   SUM(bi.item_total - bi.quantity * p.cost_price) AS profit
            FROM bill_items bi
            JOIN bills b ON b.bill_id = bi.bill_id
            JOIN products p ON p.product_id = bi.product_id
            WHERE b.bill_date BETWEEN %s AND %s
              AND p.cost_price IS NOT NULL
            GROUP BY bi.product_id, COALESCE(bi.product_name, p.name)
            ORDER BY profit DESC
        """, (date_from, date_to))
        rows = cur.fetchall()
        cur.close()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['product_id', 'product_name', 'quantity_sold', 'revenue', 'cost', 'profit', 'margin_percent'])
        for r in rows:
            rev = float(r['revenue'])
            margin = round(float(r['profit']) / rev * 100, 2) if rev > 0 else 0
            writer.writerow([r['product_id'], r['product_name'], r['quantity_sold'],
                             r['revenue'], r['cost'], r['profit'], margin])

        output = buf.getvalue()
        buf.close()
        filename = f"profit_report_{date_from}_to_{date_to}.csv"
        return Response(output, mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename="{filename}"'})
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()
