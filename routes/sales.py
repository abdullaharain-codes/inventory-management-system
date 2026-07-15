from flask import Blueprint, request, jsonify
from db.connection import get_db_connection
from mysql.connector import Error
from middleware.auth_middleware import login_required, admin_required, roles_required
from utils.stock_ledger import log_stock_movement
from utils.notifier import create_notification, check_and_notify_low_stock

sales_bp = Blueprint('sales', __name__)


@sales_bp.route('/api/sales/summary', methods=['GET'])
@roles_required('admin', 'manager')
def get_sales_summary():
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) as total_sales, SUM(total_amount) as total_revenue FROM sales")
        summary = cursor.fetchone()
        cursor.execute("""
            SELECT s.product_id,
                   COALESCE(p.name, s.product_name) as product_name,
                   SUM(s.quantity_sold) as total_quantity_sold
            FROM sales s
            LEFT JOIN products p ON s.product_id = p.product_id
            GROUP BY s.product_id, s.product_name
            ORDER BY total_quantity_sold DESC LIMIT 1
        """)
        best_selling = cursor.fetchone()
        return jsonify({
            'total_sales': summary['total_sales'] or 0,
            'total_revenue': float(summary['total_revenue']) if summary['total_revenue'] else 0.0,
            'best_selling_product': best_selling if best_selling else None
        }), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@sales_bp.route('/api/sales', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
def get_all_sales():
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT s.*, COALESCE(p.name, s.product_name) as product_name
            FROM sales s
            LEFT JOIN products p ON s.product_id = p.product_id
            ORDER BY s.sale_date DESC, s.sale_id DESC
        """)
        sales = cursor.fetchall()
        # FIX: convert date objects to strings — prevents "Invalid Date" on frontend
        for sale in sales:
            if sale.get('sale_date'):
                sale['sale_date'] = str(sale['sale_date'])
            if sale.get('created_at'):
                sale['created_at'] = str(sale['created_at'])
            if sale.get('total_amount'):
                sale['total_amount'] = float(sale['total_amount'])
            if sale.get('sale_price'):
                sale['sale_price'] = float(sale['sale_price'])
        return jsonify(sales), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@sales_bp.route('/api/sales/<int:sale_id>', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
def get_sale_by_id(sale_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor(dictionary=True)
        cursor.execute("""
            SELECT s.*, COALESCE(p.name, s.product_name) as product_name
            FROM sales s
            LEFT JOIN products p ON s.product_id = p.product_id
            WHERE s.sale_id = %s
        """, (sale_id,))
        sale = cursor.fetchone()
        if not sale:
            return jsonify({'error': 'Sale not found'}), 404
        if sale.get('sale_date'):
            sale['sale_date'] = str(sale['sale_date'])
        if sale.get('created_at'):
            sale['created_at'] = str(sale['created_at'])
        return jsonify(sale), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@sales_bp.route('/api/sales', methods=['POST'])
@roles_required('admin', 'manager', 'staff')
def add_sale():
    connection = None
    cursor = None
    try:
        data = request.get_json()
        for field in ['product_id', 'quantity_sold', 'sale_price', 'sale_date']:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor()
        cursor.execute(
            "SELECT stock_quantity, name FROM products WHERE product_id = %s",
            (data['product_id'],)
        )
        product = cursor.fetchone()
        if not product:
            return jsonify({'error': 'Product not found'}), 404
        if data['quantity_sold'] > product[0]:
            return jsonify({'error': f'Insufficient stock. Available: {product[0]}'}), 400
        quantity_before = product[0]
        product_name = product[1]
        cursor.execute("""
            INSERT INTO sales (product_id, product_name, quantity_sold, sale_price, sale_date, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (data['product_id'], product_name, data['quantity_sold'], data['sale_price'],
              data['sale_date'], data.get('notes')))
        sale_id = cursor.lastrowid

        cursor.execute(
            "UPDATE products SET stock_quantity = stock_quantity - %s WHERE product_id = %s",
            (data['quantity_sold'], data['product_id'])
        )
        connection.commit()
        log_stock_movement(
            product_id=data['product_id'],
            product_name=product_name,
            movement_type='sale',
            quantity_change=-data['quantity_sold'],
            quantity_before=quantity_before,
            reference_id=sale_id,
            reference_type='sale',
            actor_user_id=request.current_user['user_id'],
            actor_name=request.current_user['name'],
            notes=data.get('notes')
        )
        total_amount = data['quantity_sold'] * data['sale_price']
        create_notification(
            title='Sale Completed',
            message=f"{request.current_user['name']} sold {data['quantity_sold']} unit(s) of '{product_name}' for Rs{total_amount:.2f}.",
            notification_type='sale_completed',
            target_role='all',
            related_id=sale_id,
            related_type='sale'
        )
        check_and_notify_low_stock(data['product_id'])
        return jsonify({'message': 'Sale recorded successfully', 'sale_id': sale_id}), 201
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@sales_bp.route('/api/sales/<int:sale_id>', methods=['PUT'])
@admin_required
def update_sale(sale_id):
    connection = None
    cursor = None
    try:
        data = request.get_json()
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor()
        cursor.execute(
            "SELECT product_id, quantity_sold FROM sales WHERE sale_id = %s",
            (sale_id,)
        )
        original = cursor.fetchone()
        if not original:
            return jsonify({'error': 'Sale not found'}), 404
        original_product_id = original[0]
        original_quantity   = original[1]
        new_product_id = data.get('product_id', original_product_id)
        new_quantity   = data.get('quantity_sold', original_quantity)
        update_fields, values = [], []
        if 'product_id' in data and data['product_id'] != original_product_id:
            cursor.execute("SELECT name FROM products WHERE product_id = %s", (data['product_id'],))
            prod = cursor.fetchone()
            if not prod:
                return jsonify({'error': 'New product not found'}), 404
            data['product_name'] = prod[0]
        for field in ['product_id', 'product_name', 'quantity_sold', 'sale_price', 'sale_date', 'notes']:
            if field in data:
                update_fields.append(f"{field} = %s")
                values.append(data[field])
        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400
        values.append(sale_id)
        cursor.execute(
            f"UPDATE sales SET {', '.join(update_fields)} WHERE sale_id = %s",
            values
        )
        if original_product_id != new_product_id or original_quantity != new_quantity:
            cursor.execute(
                "UPDATE products SET stock_quantity = stock_quantity + %s WHERE product_id = %s",
                (original_quantity, original_product_id)
            )
            cursor.execute(
                "SELECT stock_quantity FROM products WHERE product_id = %s",
                (new_product_id,)
            )
            current_stock = cursor.fetchone()[0]
            if new_quantity > current_stock:
                connection.rollback()
                return jsonify({'error': f'Insufficient stock. Available: {current_stock}'}), 400
            cursor.execute(
                "UPDATE products SET stock_quantity = stock_quantity - %s WHERE product_id = %s",
                (new_quantity, new_product_id)
            )
        connection.commit()
        return jsonify({'message': 'Sale updated successfully'}), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@sales_bp.route('/api/sales/<int:sale_id>', methods=['DELETE'])
@admin_required
def delete_sale(sale_id):
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        cursor = connection.cursor()
        cursor.execute(
            "SELECT product_id, quantity_sold FROM sales WHERE sale_id = %s",
            (sale_id,)
        )
        sale = cursor.fetchone()
        if not sale:
            return jsonify({'error': 'Sale not found'}), 404

        cursor.execute(
            "SELECT stock_quantity, name FROM products WHERE product_id = %s",
            (sale[0],)
        )
        prod = cursor.fetchone()
        quantity_before = prod[0]
        product_name = prod[1] if prod else 'Unknown'

        cursor.execute("DELETE FROM sales WHERE sale_id = %s", (sale_id,))
        cursor.execute(
            "UPDATE products SET stock_quantity = stock_quantity + %s WHERE product_id = %s",
            (sale[1], sale[0])
        )
        connection.commit()
        log_stock_movement(
            product_id=sale[0],
            product_name=product_name,
            movement_type='sale',
            quantity_change=sale[1],
            quantity_before=quantity_before,
            reference_id=sale_id,
            reference_type='sale',
            actor_user_id=request.current_user['user_id'],
            actor_name=request.current_user['name'],
            notes='Sale deleted, stock restored'
        )
        return jsonify({'message': 'Sale deleted and stock restored successfully'}), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()