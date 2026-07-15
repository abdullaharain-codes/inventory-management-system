from flask import Blueprint, request, jsonify
from db.connection import get_db_connection
from mysql.connector import Error
from middleware.auth_middleware import admin_required

activity_logs_bp = Blueprint('activity_logs', __name__)


@activity_logs_bp.route('/api/activity-logs', methods=['GET'])
@admin_required
def get_activity_logs():
    user_id   = request.args.get('user_id')
    module    = request.args.get('module')
    date_from = request.args.get('date_from')
    date_to   = request.args.get('date_to')
    page      = request.args.get('page', 1, type=int)
    limit     = request.args.get('limit', 50, type=int)

    if page < 1:
        page = 1
    if limit < 1 or limit > 500:
        limit = 50
    offset = (page - 1) * limit

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        cursor = conn.cursor(dictionary=True)

        where_clauses = []
        params = []

        if user_id:
            where_clauses.append("al.user_id = %s")
            params.append(int(user_id))
        if module:
            where_clauses.append("al.module = %s")
            params.append(module)
        if date_from:
            where_clauses.append("al.timestamp >= %s")
            params.append(f"{date_from} 00:00:00")
        if date_to:
            where_clauses.append("al.timestamp <= %s")
            params.append(f"{date_to} 23:59:59")

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        # Total count
        cursor.execute(f"SELECT COUNT(*) AS total FROM activity_logs al {where_sql}", params)
        total = cursor.fetchone()['total']

        # Fetch page
        cursor.execute(f"""
            SELECT al.*, u.name AS user_name
            FROM activity_logs al
            LEFT JOIN users u ON al.user_id = u.user_id
            {where_sql}
            ORDER BY al.timestamp DESC
            LIMIT %s OFFSET %s
        """, params + [limit, offset])
        logs = cursor.fetchall()

        for log in logs:
            if log.get('timestamp'):
                log['timestamp'] = log['timestamp'].isoformat() if hasattr(log['timestamp'], 'isoformat') else str(log['timestamp'])

        return jsonify({
            'logs':  logs,
            'total': total,
            'page':  page,
            'limit': limit
        }), 200

    except Error:
        return jsonify({'error': 'Failed to fetch activity logs'}), 500
    finally:
        cursor.close()
        conn.close()
