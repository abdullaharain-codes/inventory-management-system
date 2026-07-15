from flask import Blueprint, request, jsonify
from db.connection import get_db_connection
from mysql.connector import Error
from middleware.auth_middleware import roles_required
from utils.activity_logger import log_activity
from utils.stock_ledger import log_stock_movement
from utils.notifier import create_notification
from datetime import datetime

adjustments_bp = Blueprint('adjustments', __name__)

VALID_REASON_CODES = {'damaged', 'expired', 'audit_correction', 'opening_balance', 'other'}


def _apply_stock_change(cursor, product_id, quantity_change):
    cursor.execute(
        "UPDATE products SET stock_quantity = stock_quantity + %s WHERE product_id = %s",
        (quantity_change, product_id)
    )


def _get_product_info(cursor, product_id):
    cursor.execute(
        "SELECT name, stock_quantity FROM products WHERE product_id = %s",
        (product_id,)
    )
    return cursor.fetchone()


@adjustments_bp.route('/api/adjustments', methods=['POST'])
@roles_required('admin', 'manager')
def create_adjustment():
    conn = None
    cursor = None
    try:
        data = request.get_json() or {}
        product_id = data.get('product_id')
        adjustment_type = data.get('adjustment_type')
        quantity = data.get('quantity')
        reason_code = data.get('reason_code')
        notes = data.get('notes', '')

        if not product_id:
            return jsonify({'error': 'product_id is required'}), 400
        if adjustment_type not in ('add', 'remove'):
            return jsonify({'error': 'adjustment_type must be add or remove'}), 400
        if not quantity or int(quantity) <= 0:
            return jsonify({'error': 'quantity must be a positive number'}), 400
        if reason_code not in VALID_REASON_CODES:
            return jsonify({'error': f'Invalid reason_code. Must be one of: {", ".join(sorted(VALID_REASON_CODES))}'}), 400

        quantity = int(quantity)

        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor()

        product = _get_product_info(cursor, product_id)
        if not product:
            return jsonify({'error': 'Product not found'}), 404

        product_name = product[0]
        current_stock = product[1]

        if adjustment_type == 'remove' and quantity > current_stock:
            return jsonify({'error': f'Cannot remove {quantity} units — only {current_stock} in stock'}), 400

        current_user = request.current_user
        is_admin = current_user['role'] == 'admin'
        now = datetime.now()

        quantity_change = quantity if adjustment_type == 'add' else -quantity

        if is_admin:
            status = 'approved'
            resolved_at = now
            approved_by_user_id = current_user['user_id']
            approved_by_name = current_user['name']
            _apply_stock_change(cursor, product_id, quantity_change)
        else:
            status = 'pending'
            resolved_at = None
            approved_by_user_id = None
            approved_by_name = None

        cursor.execute("""
            INSERT INTO stock_adjustments
                (product_id, product_name, adjustment_type, quantity, reason_code, notes,
                 status, requested_by_user_id, requested_by_name,
                 approved_by_user_id, approved_by_name, resolved_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            product_id, product_name, adjustment_type, quantity, reason_code, notes,
            status, current_user['user_id'], current_user['name'],
            approved_by_user_id, approved_by_name, resolved_at
        ))
        adjustment_id = cursor.lastrowid
        conn.commit()

        if is_admin:
            log_stock_movement(
                product_id=product_id,
                product_name=product_name,
                movement_type='adjustment',
                quantity_change=quantity_change,
                quantity_before=current_stock,
                reference_id=adjustment_id,
                reference_type='adjustment',
                actor_user_id=current_user['user_id'],
                actor_name=current_user['name'],
                notes=f"{adjustment_type} {quantity} units — {reason_code}{': ' + notes if notes else ''}"
            )
            log_activity(
                user_id=current_user['user_id'],
                user_role=current_user['role'],
                module='adjustments',
                action_type='create_approved',
                description=f"Auto-approved adjustment #{adjustment_id}: {adjustment_type} {quantity} units of '{product_name}' ({reason_code})"
            )
            return jsonify({
                'message': 'Adjustment applied immediately',
                'adjustment_id': adjustment_id,
                'status': 'approved'
            }), 201
        else:
            log_activity(
                user_id=current_user['user_id'],
                user_role=current_user['role'],
                module='adjustments',
                action_type='create_pending',
                description=f"Created pending adjustment #{adjustment_id}: {adjustment_type} {quantity} units of '{product_name}' ({reason_code})"
            )
            create_notification(
                title='New Adjustment Pending Approval',
                message=f"{current_user['name']} requested a {adjustment_type} adjustment of {quantity} units of '{product_name}' ({reason_code}).",
                notification_type='pending_adjustment',
                target_role='admin',
                related_id=adjustment_id,
                related_type='adjustment'
            )
            return jsonify({
                'message': 'Adjustment submitted for approval',
                'adjustment_id': adjustment_id,
                'status': 'pending'
            }), 201

    except Error as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@adjustments_bp.route('/api/adjustments', methods=['GET'])
@roles_required('admin', 'manager')
def get_adjustments():
    status_filter = request.args.get('status')
    product_id = request.args.get('product_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor(dictionary=True)

        where_clauses = []
        params = []

        if status_filter:
            where_clauses.append("a.status = %s")
            params.append(status_filter)
        if product_id:
            where_clauses.append("a.product_id = %s")
            params.append(product_id)
        if date_from:
            where_clauses.append("a.created_at >= %s")
            params.append(f"{date_from} 00:00:00")
        if date_to:
            where_clauses.append("a.created_at <= %s")
            params.append(f"{date_to} 23:59:59")

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        cursor.execute(f"""
            SELECT a.*
            FROM stock_adjustments a
            {where_sql}
            ORDER BY a.created_at DESC
        """, params)
        rows = cursor.fetchall()

        for r in rows:
            for ts_field in ('created_at', 'resolved_at'):
                if r.get(ts_field):
                    r[ts_field] = r[ts_field].isoformat() if hasattr(r[ts_field], 'isoformat') else str(r[ts_field])

        return jsonify(rows), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@adjustments_bp.route('/api/adjustments/<int:adjustment_id>/approve', methods=['PUT'])
@roles_required('admin')
def approve_adjustment(adjustment_id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor()

        cursor.execute("""
            SELECT adjustment_id, product_id, product_name, adjustment_type, quantity,
                   reason_code, notes, status, requested_by_user_id, requested_by_name
            FROM stock_adjustments WHERE adjustment_id = %s
        """, (adjustment_id,))
        adj = cursor.fetchone()
        if not adj:
            return jsonify({'error': 'Adjustment not found'}), 404
        if adj[7] != 'pending':
            return jsonify({'error': f'Adjustment is already {adj[7]}'}), 400

        current_user = request.current_user
        now = datetime.now()
        product_id = adj[1]
        product_name = adj[2]
        adjustment_type = adj[3]
        quantity = adj[4]
        reason_code = adj[5]
        notes = adj[6]
        requested_by_user_id = adj[8]
        requested_by_name = adj[9]
        quantity_change = quantity if adjustment_type == 'add' else -quantity

        cursor.execute(
            "SELECT stock_quantity FROM products WHERE product_id = %s",
            (product_id,)
        )
        prod = cursor.fetchone()
        quantity_before = prod[0] if prod else 0

        if adjustment_type == 'remove' and quantity > quantity_before:
            return jsonify({'error': f'Cannot remove {quantity} units — only {quantity_before} in stock'}), 400

        _apply_stock_change(cursor, product_id, quantity_change)

        cursor.execute("""
            UPDATE stock_adjustments
            SET status = 'approved',
                approved_by_user_id = %s,
                approved_by_name = %s,
                resolved_at = %s
            WHERE adjustment_id = %s
        """, (current_user['user_id'], current_user['name'], now, adjustment_id))
        conn.commit()

        log_stock_movement(
            product_id=product_id,
            product_name=product_name,
            movement_type='adjustment',
            quantity_change=quantity_change,
            quantity_before=quantity_before,
            reference_id=adjustment_id,
            reference_type='adjustment',
            actor_user_id=current_user['user_id'],
            actor_name=current_user['name'],
            notes=f"Approved adjustment: {adjustment_type} {quantity} units — {reason_code}{': ' + notes if notes else ''}"
        )
        log_activity(
            user_id=current_user['user_id'],
            user_role=current_user['role'],
            module='adjustments',
            action_type='approve',
            description=f"Approved adjustment #{adjustment_id}: {adjustment_type} {quantity} units of '{product_name}' ({reason_code})"
        )
        create_notification(
            title='Adjustment Approved',
            message=f"{current_user['name']} approved your {adjustment_type} adjustment of {quantity} unit(s) of '{product_name}'.",
            notification_type='adjustment_approved',
            user_id=requested_by_user_id,
            related_id=adjustment_id,
            related_type='adjustment'
        )

        return jsonify({'message': 'Adjustment approved and applied', 'status': 'approved'}), 200

    except Error as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


@adjustments_bp.route('/api/adjustments/<int:adjustment_id>/reject', methods=['PUT'])
@roles_required('admin')
def reject_adjustment(adjustment_id):
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = conn.cursor()

        cursor.execute("""
            SELECT adjustment_id, status, requested_by_user_id, requested_by_name
            FROM stock_adjustments WHERE adjustment_id = %s
        """, (adjustment_id,))
        adj = cursor.fetchone()
        if not adj:
            return jsonify({'error': 'Adjustment not found'}), 404
        if adj[1] != 'pending':
            return jsonify({'error': f'Adjustment is already {adj[1]}'}), 400

        current_user = request.current_user
        now = datetime.now()
        requested_by_user_id = adj[2]
        requested_by_name = adj[3]

        cursor.execute("""
            UPDATE stock_adjustments
            SET status = 'rejected',
                approved_by_user_id = %s,
                approved_by_name = %s,
                resolved_at = %s
            WHERE adjustment_id = %s
        """, (current_user['user_id'], current_user['name'], now, adjustment_id))
        conn.commit()

        log_activity(
            user_id=current_user['user_id'],
            user_role=current_user['role'],
            module='adjustments',
            action_type='reject',
            description=f"Rejected adjustment #{adjustment_id}"
        )
        create_notification(
            title='Adjustment Rejected',
            message=f"{current_user['name']} rejected your pending adjustment (#{adjustment_id}).",
            notification_type='adjustment_rejected',
            user_id=requested_by_user_id,
            related_id=adjustment_id,
            related_type='adjustment'
        )

        return jsonify({'message': 'Adjustment rejected', 'status': 'rejected'}), 200

    except Error as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
