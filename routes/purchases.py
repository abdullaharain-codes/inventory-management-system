import traceback
from flask import Blueprint, request, jsonify
from db.connection import get_db_connection
from mysql.connector import Error
from datetime import datetime
from middleware.auth_middleware import roles_required
from utils.activity_logger import log_activity
from utils.stock_ledger import log_stock_movement
from utils.notifier import create_notification, check_and_notify_low_stock

purchases_bp = Blueprint('purchases', __name__)

VALID_TRANSITIONS = {
    'draft':               ['pending_approval'],
    'pending_approval':    ['approved', 'cancelled'],
    'approved':            ['partially_received', 'received', 'cancelled'],
    'partially_received':  ['received', 'cancelled'],
    'received':            [],
    'cancelled':           []
}


def _next_po_number(cursor):
    cursor.execute("SELECT COALESCE(MAX(po_id), 0) + 1 AS next_num FROM purchase_orders")
    row = cursor.fetchone()
    next_num = row['next_num'] if isinstance(row, dict) else row[0]
    return f"PO-{str(next_num).zfill(4)}"


def _get_po_or_404(cursor, po_id):
    cursor.execute("""
        SELECT * FROM purchase_orders WHERE po_id = %s
    """, (po_id,))
    return cursor.fetchone()


def _serialize_po(po, items=None):
    if not po:
        return None
    result = dict(po)
    if result.get('subtotal') is not None:
        result['subtotal'] = float(result['subtotal'])
    for f in ('created_at', 'updated_at', 'approved_at'):
        if result.get(f):
            result[f] = str(result[f])
    if items is not None:
        for item in items:
            item['unit_cost'] = float(item['unit_cost']) if item.get('unit_cost') is not None else 0.0
            item['item_total'] = float(item['item_total']) if item.get('item_total') is not None else 0.0
        result['items'] = items
    return result


# ── Next PO number ─────────────────────────────────────────────────

@purchases_bp.route('/api/purchase-orders/next-number', methods=['GET'])
@roles_required('admin', 'manager')
def get_next_po_number():
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor()
        po_number = _next_po_number(cursor)
        return jsonify({'next_po_number': po_number}), 200
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── List all ───────────────────────────────────────────────────────

@purchases_bp.route('/api/purchase-orders', methods=['GET'])
@roles_required('admin', 'manager')
def get_all_purchase_orders():
    status_filter = request.args.get('status')
    supplier_id = request.args.get('supplier_id', type=int)
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)

        where = []
        params = []
        if status_filter:
            where.append("po.status = %s")
            params.append(status_filter)
        if supplier_id:
            where.append("po.supplier_id = %s")
            params.append(supplier_id)
        if date_from:
            where.append("po.created_at >= %s")
            params.append(f"{date_from} 00:00:00")
        if date_to:
            where.append("po.created_at <= %s")
            params.append(f"{date_to} 23:59:59")

        where_sql = "WHERE " + " AND ".join(where) if where else ""

        cursor.execute(f"""
            SELECT po.*,
                   (SELECT COUNT(*) FROM purchase_order_items WHERE po_id = po.po_id) AS item_count
            FROM purchase_orders po
            {where_sql}
            ORDER BY po.created_at DESC
        """, params)
        pos = [_serialize_po(row) for row in cursor.fetchall()]
        return jsonify(pos), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Get single ─────────────────────────────────────────────────────

@purchases_bp.route('/api/purchase-orders/<int:po_id>', methods=['GET'])
@roles_required('admin', 'manager')
def get_purchase_order(po_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)

        po = _get_po_or_404(cursor, po_id)
        if not po:
            return jsonify({'error': 'Purchase order not found'}), 404

        cursor.execute("""
            SELECT poi.*,
                   COALESCE(p.name, poi.product_name) AS product_name
            FROM purchase_order_items poi
            LEFT JOIN products p ON poi.product_id = p.product_id
            WHERE poi.po_id = %s
            ORDER BY poi.item_id
        """, (po_id,))
        items = cursor.fetchall()

        return jsonify(_serialize_po(po, items)), 200

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Create ─────────────────────────────────────────────────────────

@purchases_bp.route('/api/purchase-orders', methods=['POST'])
@roles_required('admin', 'manager')
def create_purchase_order():
    connection = None
    cursor = None
    try:
        data = request.get_json() or {}
        items_data = data.get('items', [])

        if not items_data:
            return jsonify({'error': 'At least one item is required'}), 400

        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)

        supplier_id = data.get('supplier_id')
        supplier_name = ''

        if supplier_id:
            cursor.execute("SELECT name FROM suppliers WHERE supplier_id = %s", (supplier_id,))
            sup = cursor.fetchone()
            if not sup:
                return jsonify({'error': 'Supplier not found'}), 404
            supplier_name = sup['name']

        if not supplier_name:
            return jsonify({'error': 'Supplier is required'}), 400

        po_number = _next_po_number(cursor)

        cursor.execute("""
            INSERT INTO purchase_orders
                (po_number, supplier_id, supplier_name, status,
                 expected_delivery_date, notes,
                 created_by_user_id, created_by_name)
            VALUES (%s, %s, %s, 'draft', %s, %s, %s, %s)
        """, (
            po_number, supplier_id, supplier_name,
            data.get('expected_delivery_date'),
            data.get('notes'),
            request.current_user['user_id'],
            request.current_user['name']
        ))
        po_id = cursor.lastrowid

        subtotal = 0.0
        for item in items_data:
            cursor.execute(
                "SELECT name FROM products WHERE product_id = %s",
                (item['product_id'],)
            )
            prod = cursor.fetchone()
            pname = prod['name'] if prod else 'Unknown'

            cursor.execute("""
                INSERT INTO purchase_order_items
                    (po_id, product_id, product_name, quantity_ordered, unit_cost)
                VALUES (%s, %s, %s, %s, %s)
            """, (po_id, item['product_id'], pname, item['quantity_ordered'], item['unit_cost']))
            subtotal += item['quantity_ordered'] * item['unit_cost']

        cursor.execute(
            "UPDATE purchase_orders SET subtotal = %s WHERE po_id = %s",
            (round(subtotal, 2), po_id)
        )
        connection.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='purchases',
            action_type='create',
            description=f"Created PO {po_number} (ID #{po_id}) from '{supplier_name}' — {len(items_data)} item(s), Rs{subtotal:.2f}"
        )

        create_notification(
            title='New Purchase Order Created',
            message=f"{request.current_user['name']} created PO {po_number} from '{supplier_name}' — {len(items_data)} item(s), Rs{subtotal:.2f}.",
            notification_type='new_po',
            target_role='admin',
            related_id=po_id,
            related_type='purchase_order'
        )

        cursor.execute("SELECT * FROM purchase_orders WHERE po_id = %s", (po_id,))
        po = cursor.fetchone()
        return jsonify(_serialize_po(po)), 201

    except Exception as e:
        traceback.print_exc()
        if connection: connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Update (only draft) ────────────────────────────────────────────

@purchases_bp.route('/api/purchase-orders/<int:po_id>', methods=['PUT'])
@roles_required('admin', 'manager')
def update_purchase_order(po_id):
    connection = None
    cursor = None
    try:
        data = request.get_json() or {}

        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)

        po = _get_po_or_404(cursor, po_id)
        if not po:
            return jsonify({'error': 'Purchase order not found'}), 404
        if po['status'] != 'draft':
            return jsonify({'error': 'Cannot edit a PO that is not in draft status'}), 400

        supplier_id = data.get('supplier_id')
        if supplier_id is not None:
            cursor.execute("SELECT name FROM suppliers WHERE supplier_id = %s", (supplier_id,))
            sup = cursor.fetchone()
            if not sup:
                return jsonify({'error': 'Supplier not found'}), 404
            cursor.execute(
                "UPDATE purchase_orders SET supplier_id = %s, supplier_name = %s WHERE po_id = %s",
                (supplier_id, sup['name'], po_id)
            )

        if 'expected_delivery_date' in data:
            cursor.execute(
                "UPDATE purchase_orders SET expected_delivery_date = %s WHERE po_id = %s",
                (data['expected_delivery_date'], po_id)
            )
        if 'notes' in data:
            cursor.execute(
                "UPDATE purchase_orders SET notes = %s WHERE po_id = %s",
                (data['notes'], po_id)
            )

        items_data = data.get('items')
        if items_data is not None:
            cursor.execute("DELETE FROM purchase_order_items WHERE po_id = %s", (po_id,))
            subtotal = 0.0
            for item in items_data:
                cursor.execute(
                    "SELECT name FROM products WHERE product_id = %s",
                    (item['product_id'],)
                )
                prod = cursor.fetchone()
                pname = prod['name'] if prod else 'Unknown'
                cursor.execute("""
                    INSERT INTO purchase_order_items
                        (po_id, product_id, product_name, quantity_ordered, unit_cost)
                    VALUES (%s, %s, %s, %s, %s)
                """, (po_id, item['product_id'], pname, item['quantity_ordered'], item['unit_cost']))
                subtotal += item['quantity_ordered'] * item['unit_cost']
            cursor.execute(
                "UPDATE purchase_orders SET subtotal = %s WHERE po_id = %s",
                (round(subtotal, 2), po_id)
            )

        connection.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='purchases',
            action_type='update',
            description=f"Updated PO {po['po_number']} (ID #{po_id})"
        )

        po = _get_po_or_404(cursor, po_id)
        cursor.execute(
            "SELECT * FROM purchase_order_items WHERE po_id = %s ORDER BY item_id",
            (po_id,)
        )
        items = cursor.fetchall()
        return jsonify(_serialize_po(po, items)), 200

    except Exception as e:
        traceback.print_exc()
        if connection: connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Submit for approval (draft → pending_approval) ─────────────────

@purchases_bp.route('/api/purchase-orders/<int:po_id>/submit', methods=['PUT'])
@roles_required('admin', 'manager')
def submit_purchase_order(po_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)

        po = _get_po_or_404(cursor, po_id)
        if not po:
            return jsonify({'error': 'Purchase order not found'}), 404

        if po['status'] not in ('draft',):
            return jsonify({'error': f"Cannot submit a PO with status '{po['status']}'. Only 'draft' can be submitted."}), 400

        cursor.execute(
            "UPDATE purchase_orders SET status = 'pending_approval' WHERE po_id = %s",
            (po_id,)
        )
        connection.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='purchases',
            action_type='submit',
            description=f"Submitted PO {po['po_number']} (ID #{po_id}) for approval"
        )

        po = _get_po_or_404(cursor, po_id)
        return jsonify(_serialize_po(po)), 200

    except Exception as e:
        traceback.print_exc()
        if connection: connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Approve (pending_approval → approved, admin only) ──────────────

@purchases_bp.route('/api/purchase-orders/<int:po_id>/approve', methods=['PUT'])
@roles_required('admin')
def approve_purchase_order(po_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)

        po = _get_po_or_404(cursor, po_id)
        if not po:
            return jsonify({'error': 'Purchase order not found'}), 404

        if po['status'] != 'pending_approval':
            return jsonify({'error': f"Cannot approve a PO with status '{po['status']}'. Only 'pending_approval' can be approved."}), 400

        now = datetime.now()

        cursor.execute("""
            UPDATE purchase_orders
            SET status = 'approved',
                approved_by_user_id = %s,
                approved_by_name = %s,
                approved_at = %s
            WHERE po_id = %s
        """, (
            request.current_user['user_id'],
            request.current_user['name'],
            now,
            po_id
        ))
        connection.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='purchases',
            action_type='approve',
            description=f"Approved PO {po['po_number']} (ID #{po_id})"
        )

        create_notification(
            title='PO Approved',
            message=f"{request.current_user['name']} approved PO {po['po_number']} from '{po['supplier_name']}'.",
            notification_type='po_approved',
            target_role='manager',
            related_id=po_id,
            related_type='purchase_order'
        )

        po = _get_po_or_404(cursor, po_id)
        return jsonify(_serialize_po(po)), 200

    except Exception as e:
        traceback.print_exc()
        if connection: connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Cancel (admin only, not received) ──────────────────────────────

@purchases_bp.route('/api/purchase-orders/<int:po_id>/cancel', methods=['PUT'])
@roles_required('admin')
def cancel_purchase_order(po_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)

        po = _get_po_or_404(cursor, po_id)
        if not po:
            return jsonify({'error': 'Purchase order not found'}), 404

        if 'cancelled' not in VALID_TRANSITIONS.get(po['status'], []):
            return jsonify({'error': f"Cannot cancel a PO with status '{po['status']}'"}), 400

        cursor.execute(
            "UPDATE purchase_orders SET status = 'cancelled' WHERE po_id = %s",
            (po_id,)
        )
        connection.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='purchases',
            action_type='cancel',
            description=f"Cancelled PO {po['po_number']} (ID #{po_id})"
        )

        create_notification(
            title='PO Cancelled',
            message=f"{request.current_user['name']} cancelled PO {po['po_number']} from '{po['supplier_name']}'.",
            notification_type='po_cancelled',
            target_role='all',
            related_id=po_id,
            related_type='purchase_order'
        )

        po = _get_po_or_404(cursor, po_id)
        return jsonify(_serialize_po(po)), 200

    except Exception as e:
        traceback.print_exc()
        if connection: connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Receive (approved → partially_received/received) ───────────────

@purchases_bp.route('/api/purchase-orders/<int:po_id>/receive', methods=['PUT'])
@roles_required('admin', 'manager')
def receive_purchase_order(po_id):
    connection = None
    cursor = None
    try:
        data = request.get_json() or {}
        items_data = data.get('items', [])
        if not items_data:
            return jsonify({'error': 'At least one line item with quantity_received is required'}), 400

        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)

        po = _get_po_or_404(cursor, po_id)
        if not po:
            return jsonify({'error': 'Purchase order not found'}), 404

        if po['status'] not in ('approved', 'partially_received'):
            return jsonify({'error': f"Cannot receive a PO with status '{po['status']}'. Only 'approved' or 'partially_received' can be received."}), 400

        # Load existing line items keyed by item_id
        cursor.execute("""
            SELECT poi.*, p.name AS current_product_name
            FROM purchase_order_items poi
            LEFT JOIN products p ON poi.product_id = p.product_id
            WHERE poi.po_id = %s
            ORDER BY poi.item_id
        """, (po_id,))
        existing_items = {row['item_id']: row for row in cursor.fetchall()}

        if not existing_items:
            return jsonify({'error': 'PO has no line items'}), 400

        all_fully_received = True
        received_count = 0
        stock_movements = []  # collect for logging AFTER commit

        for item in items_data:
            item_id = item.get('item_id')
            qty_received = item.get('quantity_received', 0)

            if not item_id:
                return jsonify({'error': 'Each item must have an item_id'}), 400
            if qty_received <= 0:
                return jsonify({'error': f'quantity_received must be greater than 0 for item_id {item_id}'}), 400

            existing = existing_items.get(item_id)
            if not existing:
                return jsonify({'error': f'Item ID {item_id} not found in this PO'}), 404

            new_total = existing['quantity_received'] + qty_received
            if new_total > existing['quantity_ordered']:
                return jsonify({
                    'error': f"Item '{existing['product_name']}' (ID {item_id}): "
                             f"cannot receive {new_total}, ordered {existing['quantity_ordered']}, "
                             f"already received {existing['quantity_received']}"
                }), 400

            # Update quantity_received on the line item
            cursor.execute(
                "UPDATE purchase_order_items SET quantity_received = %s WHERE item_id = %s",
                (new_total, item_id)
            )

            # Increase product stock (capture stock_before for ledger)
            if existing['product_id']:
                cursor.execute(
                    "SELECT stock_quantity FROM products WHERE product_id = %s",
                    (existing['product_id'],)
                )
                prod_row = cursor.fetchone()
                stock_before = prod_row['stock_quantity'] if prod_row else 0

                cursor.execute(
                    "UPDATE products SET stock_quantity = stock_quantity + %s WHERE product_id = %s",
                    (qty_received, existing['product_id'])
                )
                stock_movements.append({
                    'product_id': existing['product_id'],
                    'product_name': existing['product_name'],
                    'quantity_change': qty_received,
                    'stock_before': stock_before,
                })

            if new_total < existing['quantity_ordered']:
                all_fully_received = False

            received_count += qty_received

        new_status = 'received' if all_fully_received else 'partially_received'

        cursor.execute(
            "UPDATE purchase_orders SET status = %s WHERE po_id = %s",
            (new_status, po_id)
        )
        connection.commit()

        # Log stock movements AFTER commit (separate connections, avoid lock wait)
        user_id = request.current_user['user_id']
        user_name = request.current_user['name']
        po_number = po['po_number']
        for sm in stock_movements:
            log_stock_movement(
                product_id=sm['product_id'],
                product_name=sm['product_name'],
                movement_type='purchase_receive',
                quantity_change=sm['quantity_change'],
                quantity_before=sm['stock_before'],
                reference_id=po_id,
                reference_type='purchase_order',
                actor_user_id=user_id,
                actor_name=user_name,
                notes=f"PO {po_number} — received {sm['quantity_change']} of {sm['product_name']}"
            )

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='purchases',
            action_type='receive',
            description=f"Received {received_count} unit(s) on PO {po['po_number']} (ID #{po_id}) — status: {new_status}"
        )

        create_notification(
            title='PO Received',
            message=f"{request.current_user['name']} received {received_count} unit(s) on PO {po['po_number']} — status: {new_status}.",
            notification_type='po_received',
            target_role='all',
            related_id=po_id,
            related_type='purchase_order'
        )

        for sm in stock_movements:
            check_and_notify_low_stock(sm['product_id'])

        # Reload and return updated PO with items
        po = _get_po_or_404(cursor, po_id)
        cursor.execute(
            "SELECT * FROM purchase_order_items WHERE po_id = %s ORDER BY item_id",
            (po_id,)
        )
        items = cursor.fetchall()
        return jsonify(_serialize_po(po, items)), 200

    except Exception as e:
        traceback.print_exc()
        if connection: connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Delete (only draft, admin only) ────────────────────────────────

@purchases_bp.route('/api/purchase-orders/<int:po_id>', methods=['DELETE'])
@roles_required('admin')
def delete_purchase_order(po_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)

        po = _get_po_or_404(cursor, po_id)
        if not po:
            return jsonify({'error': 'Purchase order not found'}), 404

        if po['status'] != 'draft':
            return jsonify({'error': 'Only draft POs can be deleted'}), 400

        cursor.execute("DELETE FROM purchase_orders WHERE po_id = %s", (po_id,))
        connection.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='purchases',
            action_type='delete',
            description=f"Deleted PO {po['po_number']} (ID #{po_id})"
        )

        return jsonify({'message': 'Purchase order deleted successfully'}), 200

    except Exception as e:
        traceback.print_exc()
        if connection: connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()
