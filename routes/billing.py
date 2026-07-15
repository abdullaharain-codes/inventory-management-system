from flask import Blueprint, request, jsonify, Response
from db.connection import get_db_connection
from mysql.connector import Error
from datetime import datetime
from middleware.auth_middleware import login_required, admin_required, roles_required
from utils.activity_logger import log_activity
from utils.stock_ledger import log_stock_movement
from utils.notifier import create_notification, check_and_notify_low_stock
from utils.company_info import get_company_info
from utils.invoice_generator import generate_invoice_pdf

billing_bp = Blueprint('billing', __name__)


@billing_bp.route('/api/company-info', methods=['GET'])
@login_required
def get_company_info_api():
    """Public company branding info — used by the frontend receipt templates."""
    info = get_company_info()
    return jsonify(info), 200


@billing_bp.route('/api/company-info', methods=['PUT'])
@admin_required
def update_company_info_api():
    """Admin-only: update company info fields."""
    data = request.get_json() or {}
    allowed_fields = {'company_name', 'address', 'phone', 'gst_number', 'tagline', 'invoice_format'}
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return jsonify({'error': 'No valid fields to update'}), 400

    if 'invoice_format' in updates and updates['invoice_format'] not in ('thermal_80mm', 'a4'):
        return jsonify({'error': 'invoice_format must be thermal_80mm or a4'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    try:
        cursor = conn.cursor(dictionary=True)
        set_parts = []
        set_vals = []
        for k, v in updates.items():
            set_parts.append(f"{k} = %s")
            set_vals.append(v)
        cursor.execute(
            f"UPDATE company_info SET {', '.join(set_parts)} WHERE id = 1",
            set_vals
        )
        conn.commit()
        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='settings', action_type='update',
            description=f"Updated company info: {', '.join(updates.keys())}"
        )
        info = get_company_info()
        return jsonify(info), 200
    except Error as e:
        conn.rollback()
        return jsonify({'error': 'Failed to update company info'}), 500
    finally:
        cursor.close()
        conn.close()


def _fetch_bill_data(bill_id, connection):
    """Fetch a bill and its line items. Returns a dict or None."""
    cursor = connection.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT bill_id, bill_number, bill_date, subtotal,
                   discount_percent, discount_amount, grand_total,
                   gst_percent, gst_amount,
                   customer_name, customer_phone,
                   payment_method, payment_status, notes, created_at
            FROM bills WHERE bill_id = %s
        """, (bill_id,))
        bill = cursor.fetchone()
        if not bill:
            return None

        cursor.execute("""
            SELECT bi.item_id, bi.product_id, bi.quantity,
                   bi.unit_price, bi.item_total,
                   COALESCE(p.name, bi.product_name) as product_name
            FROM bill_items bi
            LEFT JOIN products p ON bi.product_id = p.product_id
            WHERE bi.bill_id = %s
        """, (bill_id,))
        items = cursor.fetchall()

        for f in ['subtotal', 'discount_amount', 'grand_total', 'gst_amount']:
            bill[f] = float(bill[f]) if bill[f] else 0.0
        if bill.get('bill_date'):
            bill['bill_date'] = str(bill['bill_date'])
        if bill.get('created_at'):
            bill['created_at'] = str(bill['created_at'])
        for item in items:
            item['unit_price'] = float(item['unit_price']) if item['unit_price'] else 0.0
            item['item_total'] = float(item['item_total']) if item['item_total'] else 0.0

        bill['items'] = items
        return bill
    finally:
        cursor.close()


@billing_bp.route('/api/bills/next-number', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
def get_next_bill_number():
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor()
        cursor.execute("SELECT COALESCE(MAX(bill_id), 0) + 1 FROM bills")
        next_id = cursor.fetchone()[0]
        return jsonify({'next_bill_number': f"BILL-{str(next_id).zfill(4)}"}), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@billing_bp.route('/api/bills', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
def get_all_bills():
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT bill_id, bill_number, bill_date, subtotal,
                   discount_percent, discount_amount, grand_total,
                   gst_percent, gst_amount,
                   customer_name, customer_phone,
                   payment_method, payment_status, notes, created_at
            FROM bills ORDER BY created_at DESC
        """)
        bills = cursor.fetchall()
        for b in bills:
            for f in ['subtotal', 'discount_amount', 'grand_total', 'gst_amount']:
                b[f] = float(b[f]) if b[f] else 0.0
            if b.get('bill_date'):
                b['bill_date'] = str(b['bill_date'])
            if b.get('created_at'):
                b['created_at'] = str(b['created_at'])
        return jsonify(bills), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@billing_bp.route('/api/bills', methods=['POST'])
@roles_required('admin', 'manager', 'staff')
def create_bill():
    connection = None
    cursor = None
    try:
        data = request.get_json()
        if not data.get('items') or len(data['items']) == 0:
            return jsonify({'error': 'At least one item is required'}), 400

        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor()

        cursor.execute("SELECT COALESCE(MAX(bill_id), 0) + 1 FROM bills")
        next_id = cursor.fetchone()[0]
        bill_number = f"BILL-{str(next_id).zfill(4)}"

        subtotal         = sum(item['quantity'] * item['unit_price'] for item in data['items'])
        discount_percent = float(data.get('discount_percent') or 0)
        gst_percent      = float(data.get('gst_percent') or 0)
        discount_amount  = round(subtotal * discount_percent / 100, 2)
        after_discount   = subtotal - discount_amount
        gst_amount       = round(after_discount * gst_percent / 100, 2)

        # FIX: safe date handling
        _bd = data.get('bill_date')
        bill_date = _bd.strip() if isinstance(_bd, str) and _bd.strip() else datetime.now().strftime('%Y-%m-%d')

        # FIX: safe string handling — None.strip() was crashing
        _cn = data.get('customer_name')
        _cp = data.get('customer_phone')
        customer_name  = _cn.strip() if isinstance(_cn, str) and _cn.strip() else None
        customer_phone = _cp.strip() if isinstance(_cp, str) and _cp.strip() else None

        payment_method = data.get('payment_method') or 'cash'
        payment_status = data.get('payment_status') or 'paid'

        # Validate stock first — also capture before-quantities for ledger
        items_data = []
        for item in data['items']:
            cursor.execute(
                "SELECT stock_quantity, name FROM products WHERE product_id = %s",
                (item['product_id'],)
            )
            product = cursor.fetchone()
            if not product:
                connection.rollback()
                return jsonify({'error': f"Product ID {item['product_id']} not found"}), 404
            if item['quantity'] > product[0]:
                connection.rollback()
                return jsonify({'error': f"Insufficient stock for '{product[1]}'. Available: {product[0]}"}), 400
            items_data.append({
                'product_id': item['product_id'],
                'product_name': product[1],
                'quantity': item['quantity'],
                'quantity_before': product[0]
            })

        cursor.execute("""
            INSERT INTO bills (
                bill_number, bill_date, discount_percent, subtotal,
                gst_percent, gst_amount,
                customer_name, customer_phone,
                payment_method, payment_status, notes
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            bill_number, bill_date, discount_percent, subtotal,
            gst_percent, gst_amount,
            customer_name, customer_phone,
            payment_method, payment_status,
            data.get('notes') or ''
        ))
        bill_id = cursor.lastrowid

        for item in data['items']:
            cursor.execute(
                "SELECT name FROM products WHERE product_id = %s",
                (item['product_id'],)
            )
            pname = cursor.fetchone()[0]
            cursor.execute("""
                INSERT INTO bill_items (bill_id, product_id, product_name, quantity, unit_price)
                VALUES (%s,%s,%s,%s,%s)
            """, (bill_id, item['product_id'], pname, item['quantity'], item['unit_price']))

            cursor.execute("""
                INSERT INTO sales (product_id, product_name, quantity_sold, sale_price, sale_date, notes)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (item['product_id'], pname, item['quantity'], item['unit_price'],
                  bill_date, f"Auto-recorded from {bill_number}"))

        # Pending payment record for credit sales
        if payment_status == 'pending' and customer_name:
            grand_total_val = round(after_discount + gst_amount, 2)
            _dd = data.get('due_date')
            due_date = _dd.strip() if isinstance(_dd, str) and _dd.strip() else None
            cursor.execute("""
                INSERT INTO pending_payments
                    (bill_id, customer_name, customer_phone, amount_due, amount_paid, due_date, status, notes)
                VALUES (%s,%s,%s,%s,0,%s,'pending',%s)
            """, (bill_id, customer_name, customer_phone, grand_total_val,
                  due_date, data.get('notes') or ''))

        connection.commit()

        for it in items_data:
            log_stock_movement(
                product_id=it['product_id'],
                product_name=it['product_name'],
                movement_type='bill_sale',
                quantity_change=-it['quantity'],
                quantity_before=it['quantity_before'],
                reference_id=bill_id,
                reference_type='bill',
                actor_user_id=request.current_user['user_id'],
                actor_name=request.current_user['name'],
                notes=f"Auto-recorded from {bill_number}"
            )
            check_and_notify_low_stock(it['product_id'])

        cursor.execute("SELECT grand_total FROM bills WHERE bill_id = %s", (bill_id,))
        grand_total = float(cursor.fetchone()[0] or 0)

        create_notification(
            title='Order Created',
            message=f"{request.current_user['name']} created {bill_number} — Rs{grand_total:.2f}.",
            notification_type='order_created',
            target_role='all',
            related_id=bill_id,
            related_type='bill'
        )

        if payment_status == 'pending' and customer_name:
            create_notification(
                title='Pending Payment',
                message=f"{bill_number} created for '{customer_name}' — Rs{grand_total:.2f} pending.",
                notification_type='pending_payment',
                target_role='all',
                related_id=bill_id,
                related_type='bill'
            )

        return jsonify({
            'message':     'Bill created successfully',
            'bill_id':     bill_id,
            'bill_number': bill_number,
            'grand_total': grand_total
        }), 201

    except Error as e:
        if connection: connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@billing_bp.route('/api/bills/<int:bill_id>', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
def get_bill_by_id(bill_id):
    connection = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        bill = _fetch_bill_data(bill_id, connection)
        if not bill:
            return jsonify({'error': 'Bill not found'}), 404
        return jsonify(bill), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if connection: connection.close()


@billing_bp.route('/api/bills/<int:bill_id>/invoice-pdf', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
def download_invoice_pdf(bill_id):
    connection = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        bill = _fetch_bill_data(bill_id, connection)
        if not bill:
            return jsonify({'error': 'Bill not found'}), 404

        company = get_company_info()
        pdf_bytes = generate_invoice_pdf(bill, company)

        bill_number = bill.get('bill_number', f'bill_{bill_id}')
        return Response(
            pdf_bytes,
            mimetype='application/pdf',
            headers={
                'Content-Disposition': f'attachment; filename="{bill_number}.pdf"',
            }
        )
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if connection: connection.close()


@billing_bp.route('/api/bills/<int:bill_id>', methods=['PUT'])
@admin_required
def update_bill(bill_id):
    connection = None
    cursor = None
    try:
        data = request.get_json()
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor()
        cursor.execute("SELECT bill_id FROM bills WHERE bill_id = %s", (bill_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Bill not found'}), 404
        fields, values = [], []
        for col in ['customer_name', 'customer_phone', 'payment_method',
                    'payment_status', 'notes', 'gst_percent']:
            if col in data:
                fields.append(f"{col} = %s")
                values.append(data[col])
        if not fields:
            return jsonify({'error': 'No fields to update'}), 400
        values.append(bill_id)
        cursor.execute(f"UPDATE bills SET {', '.join(fields)} WHERE bill_id = %s", values)
        connection.commit()
        return jsonify({'message': 'Bill updated successfully'}), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@billing_bp.route('/api/bills/<int:bill_id>', methods=['DELETE'])
@admin_required
def delete_bill(bill_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT bill_number FROM bills WHERE bill_id = %s", (bill_id,))
        bill = cursor.fetchone()
        if not bill:
            return jsonify({'error': 'Bill not found'}), 404
        bill_number = bill['bill_number']
        cursor.execute("SELECT product_id, quantity FROM bill_items WHERE bill_id = %s", (bill_id,))
        items = cursor.fetchall()
        for item in items:
            cursor.execute(
                "UPDATE products SET stock_quantity = stock_quantity + %s WHERE product_id = %s",
                (item['quantity'], item['product_id'])
            )
        cursor.execute("DELETE FROM sales WHERE notes = %s", (f"Auto-recorded from {bill_number}",))
        cursor.execute("DELETE FROM bills WHERE bill_id = %s", (bill_id,))
        connection.commit()
        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='billing',
            action_type='delete',
            description=f"Deleted bill {bill_number} (ID #{bill_id}), stock restored"
        )
        return jsonify({'message': 'Bill deleted, stock restored'}), 200
    except Error as e:
        if connection: connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@billing_bp.route('/api/bills/<int:bill_id>/refund', methods=['POST'])
@admin_required
def create_refund(bill_id):
    connection = None
    cursor = None
    try:
        data = request.get_json()
        for f in ['product_id', 'quantity_returned', 'refund_amount', 'refund_date']:
            if f not in data:
                return jsonify({'error': f'Missing field: {f}'}), 400
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor()
        cursor.execute("SELECT bill_id FROM bills WHERE bill_id = %s", (bill_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Bill not found'}), 404
        cursor.execute(
            "SELECT quantity FROM bill_items WHERE bill_id = %s AND product_id = %s",
            (bill_id, data['product_id'])
        )
        bill_item = cursor.fetchone()
        if not bill_item:
            return jsonify({'error': 'Product not found in this bill'}), 404
        if data['quantity_returned'] > bill_item[0]:
            return jsonify({'error': f"Cannot refund more than sold ({bill_item[0]})"}), 400

        cursor.execute(
            "SELECT stock_quantity, name FROM products WHERE product_id = %s",
            (data['product_id'],)
        )
        prod_info = cursor.fetchone()
        quantity_before = prod_info[0]
        product_name = prod_info[1]

        cursor.execute("""
            INSERT INTO refunds (bill_id, product_id, quantity_returned, refund_amount, reason, refund_date)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (bill_id, data['product_id'], data['quantity_returned'],
              data['refund_amount'], data.get('reason', ''), data['refund_date']))
        cursor.execute(
            "UPDATE products SET stock_quantity = stock_quantity + %s WHERE product_id = %s",
            (data['quantity_returned'], data['product_id'])
        )
        connection.commit()
        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='billing',
            action_type='create_refund',
            description=f"Refund of {data['quantity_returned']} units of product #{data['product_id']} on bill #{bill_id} (Rs{data['refund_amount']})"
        )
        log_stock_movement(
            product_id=data['product_id'],
            product_name=product_name,
            movement_type='refund',
            quantity_change=data['quantity_returned'],
            quantity_before=quantity_before,
            reference_id=bill_id,
            reference_type='refund',
            actor_user_id=request.current_user['user_id'],
            actor_name=request.current_user['name'],
            notes=data.get('reason', '')
        )
        return jsonify({'message': 'Refund processed and stock restored'}), 201
    except Error as e:
        if connection: connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@billing_bp.route('/api/bills/<int:bill_id>/refunds', methods=['GET'])
@roles_required('admin', 'manager')
def get_bill_refunds(bill_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT r.*, p.name as product_name
            FROM refunds r JOIN products p ON r.product_id = p.product_id
            WHERE r.bill_id = %s ORDER BY r.created_at DESC
        """, (bill_id,))
        refunds = cursor.fetchall()
        for r in refunds:
            r['refund_amount'] = float(r['refund_amount'])
            if r.get('refund_date'):
                r['refund_date'] = str(r['refund_date'])
            if r.get('created_at'):
                r['created_at'] = str(r['created_at'])
        return jsonify(refunds), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@billing_bp.route('/api/pending-payments', methods=['GET'])
@roles_required('admin', 'manager')
def get_pending_payments():
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT pp.*, b.bill_number, b.bill_date
            FROM pending_payments pp
            JOIN bills b ON pp.bill_id = b.bill_id
            ORDER BY pp.created_at DESC
        """)
        payments = cursor.fetchall()
        for p in payments:
            p['amount_due']  = float(p['amount_due'])
            p['amount_paid'] = float(p['amount_paid'])
            if p.get('bill_date'):
                p['bill_date'] = str(p['bill_date'])
            if p.get('due_date'):
                p['due_date'] = str(p['due_date'])
            if p.get('created_at'):
                p['created_at'] = str(p['created_at'])
        return jsonify(payments), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@billing_bp.route('/api/pending-payments/<int:payment_id>', methods=['PUT'])
@admin_required
def update_pending_payment(payment_id):
    """
    Records a payment installment.
    LOGIC:
      total_paid = previous_paid + new_payment (capped at amount_due)
      partial  → total_paid > 0 but < amount_due
      paid     → total_paid >= amount_due
      pending  → total_paid == 0
    """
    connection = None
    cursor = None
    try:
        data = request.get_json()
        new_payment = float(data.get('amount_paid') or 0)

        if new_payment <= 0:
            return jsonify({'error': 'Payment amount must be greater than zero'}), 400

        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor()

        cursor.execute(
            "SELECT amount_due, amount_paid FROM pending_payments WHERE payment_id = %s",
            (payment_id,)
        )
        record = cursor.fetchone()
        if not record:
            return jsonify({'error': 'Payment record not found'}), 404

        amount_due    = float(record[0])
        previous_paid = float(record[1])

        # Running total — cap at amount_due, cannot overpay
        total_paid = round(min(previous_paid + new_payment, amount_due), 2)

        # Correct status logic
        if total_paid >= amount_due:
            status = 'paid'
        elif total_paid > 0:
            status = 'partial'
        else:
            status = 'pending'

        note_entry = f"Paid Rs{new_payment:.2f} on {datetime.now().strftime('%Y-%m-%d')}"
        if data.get('notes'):
            note_entry += f" — {data['notes']}"

        cursor.execute("""
            UPDATE pending_payments
            SET amount_paid = %s,
                status      = %s,
                notes       = CONCAT(IFNULL(notes, ''), ' | ', %s)
            WHERE payment_id = %s
        """, (total_paid, status, note_entry, payment_id))

        # Update bill payment_status only when FULLY paid
        if status == 'paid':
            cursor.execute("""
                UPDATE bills
                SET payment_status = 'paid'
                WHERE bill_id = (
                    SELECT bill_id FROM pending_payments WHERE payment_id = %s
                )
            """, (payment_id,))

        connection.commit()

        remaining = round(amount_due - total_paid, 2)

        create_notification(
            title='Payment Received',
            message=f"Rs{new_payment:.2f} payment recorded. Status: {status}. Remaining: Rs{remaining:.2f}.",
            notification_type='payment_received',
            target_role='all',
            related_id=payment_id,
            related_type='pending_payment'
        )

        return jsonify({
            'message':    f'Payment recorded. Status: {status}',
            'status':     status,
            'total_paid': total_paid,
            'remaining':  remaining
        }), 200

    except Error as e:
        if connection: connection.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@billing_bp.route('/api/sales/daily-summary', methods=['GET'])
@roles_required('admin', 'manager')
def daily_summary():
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                bill_date,
                COUNT(*)                       AS total_bills,
                SUM(subtotal)                  AS subtotal,
                SUM(IFNULL(discount_amount,0)) AS total_discount,
                SUM(IFNULL(gst_amount,0))      AS total_gst,
                SUM(grand_total)               AS net_revenue,
                SUM(grand_total)               AS total_revenue
            FROM bills
            WHERE bill_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY bill_date
            ORDER BY bill_date DESC
        """)
        rows = cursor.fetchall()
        for r in rows:
            r['subtotal']       = float(r['subtotal']       or 0)
            r['total_discount'] = float(r['total_discount'] or 0)
            r['total_gst']      = float(r['total_gst']      or 0)
            r['net_revenue']    = float(r['net_revenue']    or 0)
            r['total_revenue']  = float(r['total_revenue']  or 0)
            if r.get('bill_date'):
                r['bill_date'] = str(r['bill_date'])
        return jsonify(rows), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()