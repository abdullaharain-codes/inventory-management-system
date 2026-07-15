from datetime import datetime, timedelta

from flask import Blueprint, request, jsonify
from db.connection import get_db_connection
from mysql.connector import Error
from middleware.auth_middleware import roles_required

inventory_bp = Blueprint('inventory', __name__)


@inventory_bp.route('/api/inventory/stock-status', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
def get_stock_status():
    """Return all products with current stock vs minimum threshold."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT p.product_id, p.name, p.sku, p.stock_quantity,
                   p.minimum_stock_threshold, p.reorder_quantity,
                   c.name AS category_name
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.category_id
            ORDER BY p.name
        """)
        products = cursor.fetchall()
        result = []
        for p in products:
            threshold = p['minimum_stock_threshold'] or 10
            result.append({
                'product_id':            p['product_id'],
                'name':                  p['name'],
                'sku':                   p['sku'],
                'category':              p['category_name'] or '',
                'stock_quantity':        p['stock_quantity'],
                'minimum_stock_threshold': threshold,
                'reorder_quantity':      p['reorder_quantity'] or 50,
                'is_low_stock':          p['stock_quantity'] <= threshold
            })
        return jsonify(result), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@inventory_bp.route('/api/inventory/ledger', methods=['GET'])
@roles_required('admin', 'manager')
def get_stock_ledger():
    """Return paginated stock ledger, filterable by product_id, movement_type, date range."""
    product_id   = request.args.get('product_id', type=int)
    movement_type = request.args.get('movement_type')
    date_from    = request.args.get('date_from')
    date_to      = request.args.get('date_to')
    page         = request.args.get('page', 1, type=int)
    limit        = request.args.get('limit', 50, type=int)

    if page < 1:
        page = 1
    if limit < 1 or limit > 500:
        limit = 50
    offset = (page - 1) * limit

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor(dictionary=True)

        where_clauses = []
        params = []

        if product_id:
            where_clauses.append("sl.product_id = %s")
            params.append(product_id)
        if movement_type:
            where_clauses.append("sl.movement_type = %s")
            params.append(movement_type)
        if date_from:
            where_clauses.append("sl.created_at >= %s")
            params.append(f"{date_from} 00:00:00")
        if date_to:
            where_clauses.append("sl.created_at <= %s")
            params.append(f"{date_to} 23:59:59")

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        cursor.execute(f"SELECT COUNT(*) AS total FROM stock_ledger sl {where_sql}", params)
        total = cursor.fetchone()['total']

        cursor.execute(f"""
            SELECT sl.*
            FROM stock_ledger sl
            {where_sql}
            ORDER BY sl.created_at DESC, sl.ledger_id DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        rows = cursor.fetchall()

        for r in rows:
            if r.get('created_at'):
                r['created_at'] = r['created_at'].isoformat() if hasattr(r['created_at'], 'isoformat') else str(r['created_at'])

        return jsonify({
            'ledger': rows,
            'total':  total,
            'page':   page,
            'limit':  limit
        }), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


def get_inventory_alerts_data():
    """Return list of alert dicts (low_stock + expiry_soon).
    Reusable helper — not a route. Fails silently, returns [].

    This is imported by routes/notifications.py for the "Check Low
    Stock & Notify" action.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return []
        cursor = conn.cursor(dictionary=True)

        thirty_days = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
        today = datetime.now().strftime('%Y-%m-%d')

        cursor.execute("""
            SELECT p.product_id, p.name, p.category,
                   p.stock_quantity, p.minimum_stock_threshold,
                   p.reorder_quantity, p.expiry_date
            FROM products p
            WHERE p.stock_quantity <= p.minimum_stock_threshold
               OR (p.expiry_date IS NOT NULL AND p.expiry_date BETWEEN %s AND %s)
            ORDER BY p.name
        """, (today, thirty_days))
        rows = cursor.fetchall()

        alerts = []
        for r in rows:
            if r['stock_quantity'] <= (r['minimum_stock_threshold'] or 10):
                alerts.append({
                    'product_id':              r['product_id'],
                    'product_name':            r['name'],
                    'category':                r['category'] or '',
                    'current_stock':           r['stock_quantity'],
                    'minimum_stock_threshold': r['minimum_stock_threshold'] or 10,
                    'reorder_quantity':        r['reorder_quantity'] or 50,
                    'alert_type':              'low_stock',
                    'days_until_expiry':       None
                })
            if r['expiry_date'] and today <= r['expiry_date'].strftime('%Y-%m-%d') <= thirty_days:
                delta = (r['expiry_date'] - datetime.now().date()).days
                alerts.append({
                    'product_id':              r['product_id'],
                    'product_name':            r['name'],
                    'category':                r['category'] or '',
                    'current_stock':           r['stock_quantity'],
                    'minimum_stock_threshold': r['minimum_stock_threshold'] or 10,
                    'reorder_quantity':        r['reorder_quantity'] or 50,
                    'alert_type':              'expiry_soon',
                    'days_until_expiry':       delta
                })
        return alerts
    except Error as e:
        print(f"[inventory] get_inventory_alerts_data error: {e}")
        return []
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@inventory_bp.route('/api/inventory/alerts', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
def get_inventory_alerts():
    """Return low-stock and expiry-soon alerts as JSON."""
    alerts = get_inventory_alerts_data()
    return jsonify(alerts), 200
