import json
import uuid
import time
from flask import Blueprint, request, jsonify, Response, stream_with_context
from db.connection import get_db_connection
from mysql.connector import Error
from middleware.auth_middleware import roles_required
from utils.notifier import create_notification
from utils.notification_broadcaster import subscribe, unsubscribe
from routes.inventory import get_inventory_alerts_data

notifications_bp = Blueprint('notifications', __name__)


@notifications_bp.route('/api/notifications', methods=['GET'])
@roles_required('admin', 'manager')
def get_notifications():
    """Return notifications visible to current user, with pagination and filters.

    Query params: page (default 1), limit (default 50), type, date_from, date_to
    Response: {notifications: [...], total, page, limit, total_pages}
    """
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 50, type=int)
    notif_type = request.args.get('type')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    if page < 1: page = 1
    if limit < 1 or limit > 200: limit = 50
    offset = (page - 1) * limit

    user = request.current_user

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor(dictionary=True)

        where_clauses = [
            "(user_id = %s OR target_role = 'all' OR target_role = %s)"
        ]
        params = [user['user_id'], user['role']]

        if notif_type:
            where_clauses.append("notification_type = %s")
            params.append(notif_type)
        if date_from:
            where_clauses.append("created_at >= %s")
            params.append(f"{date_from} 00:00:00")
        if date_to:
            where_clauses.append("created_at <= %s")
            params.append(f"{date_to} 23:59:59")

        where_sql = "WHERE " + " AND ".join(where_clauses)

        cursor.execute(f"SELECT COUNT(*) AS total FROM notifications {where_sql}", params)
        total = cursor.fetchone()['total']

        cursor.execute(f"""
            SELECT * FROM notifications {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        rows = cursor.fetchall()

        for r in rows:
            if r.get('created_at'):
                r['created_at'] = r['created_at'].isoformat() if hasattr(r['created_at'], 'isoformat') else str(r['created_at'])

        total_pages = (total + limit - 1) // limit if total > 0 else 1

        return jsonify({
            'notifications': rows,
            'total': total,
            'page': page,
            'limit': limit,
            'total_pages': total_pages
        }), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@notifications_bp.route('/api/notifications/unread-count', methods=['GET'])
@roles_required('admin', 'manager')
def get_unread_count():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM notifications
            WHERE is_read = 0
              AND (user_id = %s OR target_role = 'all' OR target_role = %s)
        """, (request.current_user['user_id'], request.current_user['role']))
        count = cursor.fetchone()[0]
        return jsonify({'unread_count': count}), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@notifications_bp.route('/api/notifications/<int:notification_id>/read', methods=['PUT'])
@roles_required('admin', 'manager')
def mark_read(notification_id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE notifications SET is_read = 1 WHERE notification_id = %s",
            (notification_id,)
        )
        conn.commit()
        return jsonify({'message': 'Marked as read'}), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@notifications_bp.route('/api/notifications/read-all', methods=['PUT'])
@roles_required('admin', 'manager')
def mark_all_read():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE notifications SET is_read = 1
            WHERE is_read = 0
              AND (user_id = %s OR target_role = 'all' OR target_role = %s)
        """, (request.current_user['user_id'], request.current_user['role']))
        conn.commit()
        return jsonify({'message': 'All marked as read'}), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@notifications_bp.route('/api/notifications/stream', methods=['GET'])
@roles_required('admin', 'manager')
def stream_notifications():
    """SSE endpoint — streams notifications in real time.

    Supports Last-Event-ID header (sent automatically on EventSource reconnect)
    and ?last_id= query param (for the initial connection before an event ID
    has been received).
    """
    user = request.current_user
    sub_id = str(uuid.uuid4())

    catch_up_from = request.headers.get('Last-Event-ID')
    if not catch_up_from:
        catch_up_from = request.args.get('last_id')

    def generate():
        q = None
        try:
            # ── catch-up from DB ────────────────────────────────
            conn = get_db_connection()
            if conn:
                try:
                    cursor = conn.cursor(dictionary=True)
                    vis = ("(user_id = %s OR target_role = 'all' "
                           "OR target_role = %s)")
                    params = [user['user_id'], user['role']]
                    if catch_up_from:
                        cursor.execute(
                            f"SELECT * FROM notifications "
                            f"WHERE notification_id > %s AND {vis} "
                            f"ORDER BY notification_id ASC",
                            [int(catch_up_from)] + params
                        )
                    else:
                        cursor.execute(
                            f"SELECT * FROM notifications "
                            f"WHERE {vis} "
                            f"ORDER BY notification_id ASC",
                            params
                        )
                    for row in cursor.fetchall():
                        nid = row['notification_id']
                        if row.get('created_at'):
                            row['created_at'] = (
                                row['created_at'].isoformat()
                                if hasattr(row['created_at'], 'isoformat')
                                else str(row['created_at'])
                            )
                        yield (
                            f"id: {nid}\n"
                            f"data: {json.dumps(row, default=str)}\n\n"
                        )
                    cursor.close()
                finally:
                    conn.close()

            # ── subscribe to live feed ───────────────────────────
            q = subscribe(sub_id, user['user_id'], user['role'])

            while True:
                try:
                    notif = q.get(timeout=15)
                    nid = notif.get('notification_id', '')
                    yield (
                        f"id: {nid}\n"
                        f"data: {json.dumps(notif, default=str)}\n\n"
                    )
                except Exception:
                    # no message in 15 s → send SSE comment as heartbeat
                    yield f": heartbeat {time.time():.0f}\n\n"

        except GeneratorExit:
            pass
        finally:
            if q:
                unsubscribe(sub_id)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no',
        }
    )


@notifications_bp.route('/api/notifications', methods=['POST'])
@roles_required('admin')
def create_manual_notification():
    """Admin-only: create a manual 'general' notification."""
    data = request.get_json() or {}
    title = data.get('title', '').strip()
    message = data.get('message', '').strip()
    target_role = data.get('target_role', 'all')
    if not title or not message:
        return jsonify({'error': 'title and message are required'}), 400
    if target_role not in ('admin', 'manager', 'staff', 'all'):
        return jsonify({'error': 'Invalid target_role'}), 400
    create_notification(
        title=title,
        message=message,
        notification_type='general',
        target_role=target_role
    )
    return jsonify({'message': 'Notification created'}), 201


@notifications_bp.route('/api/notifications/check-low-stock', methods=['POST'])
@roles_required('admin')
def check_low_stock_and_notify():
    """Admin-only: check current alerts and create one notification per low-stock
    product that doesn't already have an unread low_stock notification."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor(dictionary=True)

        alerts_data = get_inventory_alerts_data()
        created = 0
        for alert in alerts_data:
            if alert['alert_type'] != 'low_stock':
                continue
            cursor.execute("""
                SELECT notification_id FROM notifications
                WHERE notification_type = 'low_stock'
                  AND related_id = %s
                  AND related_type = 'product'
                  AND is_read = 0
                LIMIT 1
            """, (alert['product_id'],))
            if cursor.fetchone():
                continue
            create_notification(
                title='Low Stock Alert',
                message=f"{alert['product_name']} has only {alert['current_stock']} units in stock (threshold: {alert['minimum_stock_threshold']}).",
                notification_type='low_stock',
                target_role='all',
                related_id=alert['product_id'],
                related_type='product'
            )
            created += 1

        return jsonify({'message': f'{created} low stock notification(s) created', 'created': created}), 201
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
