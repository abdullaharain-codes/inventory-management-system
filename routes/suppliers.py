from flask import Blueprint, request, jsonify
from db.connection import get_db_connection
from mysql.connector import Error
from middleware.auth_middleware import admin_required, roles_required
from utils.activity_logger import log_activity
from utils.notifier import create_notification

suppliers_bp = Blueprint('suppliers', __name__)


@suppliers_bp.route('/api/suppliers', methods=['GET'])
@roles_required('admin', 'manager')
def get_all_suppliers():
    """Fetch all suppliers"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM suppliers ORDER BY supplier_id")
        suppliers = cursor.fetchall()

        return jsonify(suppliers), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@suppliers_bp.route('/api/suppliers/<int:supplier_id>', methods=['GET'])
@roles_required('admin', 'manager')
def get_supplier_by_id(supplier_id):
    """Fetch single supplier with purchase history placeholders"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT * FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        supplier = cursor.fetchone()

        if not supplier:
            return jsonify({'error': 'Supplier not found'}), 404

        # Purchase history summary — placeholder values for now.
        # These will be populated from the Purchases module once Phase 7 is built.
        supplier['total_orders']    = 0
        supplier['total_spend']     = 0.00
        supplier['last_order_date'] = None

        return jsonify(supplier), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@suppliers_bp.route('/api/suppliers', methods=['POST'])
@roles_required('admin', 'manager')
def add_supplier():
    """Add new supplier"""
    connection = None
    cursor = None
    try:
        data = request.get_json()

        # Validate required fields
        if 'name' not in data:
            return jsonify({'error': 'Missing required field: name'}), 400

        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)

        # Validate tax_registration_number uniqueness if provided
        tax_number = data.get('tax_registration_number')
        if tax_number:
            cursor.execute(
                "SELECT supplier_id FROM suppliers WHERE tax_registration_number = %s",
                (tax_number,)
            )
            if cursor.fetchone():
                return jsonify({'error': 'Tax registration number already exists'}), 409

        query = """
            INSERT INTO suppliers (name, contact_person, phone, email, address,
                                   tax_registration_number, payment_terms, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            data.get('name'),
            data.get('contact_person'),
            data.get('phone'),
            data.get('email'),
            data.get('address'),
            tax_number,
            data.get('payment_terms'),
            data.get('notes')
        )

        cursor.execute(query, values)
        connection.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='suppliers',
            action_type='create',
            description=f"Created supplier '{data.get('name')}' (ID #{cursor.lastrowid})"
        )
        create_notification(
            title='Supplier Added',
            message=f"{request.current_user['name']} added supplier '{data.get('name')}' (ID #{cursor.lastrowid}).",
            notification_type='supplier_added',
            target_role='all',
            related_id=cursor.lastrowid,
            related_type='supplier'
        )

        return jsonify({
            'message': 'Supplier added successfully',
            'supplier_id': cursor.lastrowid
        }), 201

    except Error as e:
        if 'Duplicate entry' in str(e) and 'email' in str(e):
            return jsonify({'error': 'Email already exists'}), 409
        if 'Duplicate entry' in str(e) and 'tax_registration_number' in str(e):
            return jsonify({'error': 'Tax registration number already exists'}), 409
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@suppliers_bp.route('/api/suppliers/<int:supplier_id>', methods=['PUT'])
@roles_required('admin', 'manager')
def update_supplier(supplier_id):
    """Update supplier"""
    connection = None
    cursor = None
    try:
        data = request.get_json()

        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)

        # Check if supplier exists
        cursor.execute("SELECT * FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        existing = cursor.fetchone()
        if not existing:
            return jsonify({'error': 'Supplier not found'}), 404

        # Validate tax_registration_number uniqueness if provided and changed
        tax_number = data.get('tax_registration_number')
        if tax_number and tax_number != existing.get('tax_registration_number'):
            cursor.execute(
                "SELECT supplier_id FROM suppliers WHERE tax_registration_number = %s AND supplier_id != %s",
                (tax_number, supplier_id)
            )
            if cursor.fetchone():
                return jsonify({'error': 'Tax registration number already exists'}), 409

        # Build dynamic update query
        update_fields = []
        values = []

        updatable_fields = ['name', 'contact_person', 'phone', 'email', 'address',
                            'tax_registration_number', 'payment_terms', 'notes']
        for field in updatable_fields:
            if field in data:
                update_fields.append(f"{field} = %s")
                values.append(data[field])

        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400

        values.append(supplier_id)
        query = f"UPDATE suppliers SET {', '.join(update_fields)} WHERE supplier_id = %s"

        cursor.execute(query, values)
        connection.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='suppliers',
            action_type='update',
            description=f"Updated supplier #{supplier_id} ('{existing['name']}'): {', '.join(update_fields)}"
        )
        create_notification(
            title='Supplier Updated',
            message=f"{request.current_user['name']} updated supplier '{existing['name']}' (ID #{supplier_id}).",
            notification_type='supplier_updated',
            target_role='all',
            related_id=supplier_id,
            related_type='supplier'
        )

        return jsonify({'message': 'Supplier updated successfully'}), 200

    except Error as e:
        if 'Duplicate entry' in str(e) and 'email' in str(e):
            return jsonify({'error': 'Email already exists'}), 409
        if 'Duplicate entry' in str(e) and 'tax_registration_number' in str(e):
            return jsonify({'error': 'Tax registration number already exists'}), 409
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@suppliers_bp.route('/api/suppliers/<int:supplier_id>', methods=['DELETE'])
@admin_required
def delete_supplier(supplier_id):
    """Delete supplier"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)

        # Check if supplier exists
        cursor.execute("SELECT * FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        supplier = cursor.fetchone()
        if not supplier:
            return jsonify({'error': 'Supplier not found'}), 404

        # Check if supplier has products
        cursor.execute("SELECT COUNT(*) AS cnt FROM products WHERE supplier_id = %s", (supplier_id,))
        product_count = cursor.fetchone()['cnt']
        if product_count > 0:
            return jsonify({'error': 'Cannot delete supplier with existing products. Update products first.'}), 409

        cursor.execute("DELETE FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        connection.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='suppliers',
            action_type='delete',
            description=f"Deleted supplier '{supplier['name']}' (ID #{supplier_id})"
        )
        create_notification(
            title='Supplier Deleted',
            message=f"{request.current_user['name']} deleted supplier '{supplier['name']}' (ID #{supplier_id}).",
            notification_type='supplier_deleted',
            target_role='all',
            related_id=supplier_id,
            related_type='supplier'
        )

        return jsonify({'message': 'Supplier deleted successfully'}), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()


@suppliers_bp.route('/api/suppliers/<int:supplier_id>/products', methods=['GET'])
@roles_required('admin', 'manager')
def get_supplier_products(supplier_id):
    """Fetch all products belonging to this supplier"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)

        # Verify supplier exists
        cursor.execute("SELECT supplier_id FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Supplier not found'}), 404

        cursor.execute("""
            SELECT p.*, c.name AS category_name
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.category_id
            WHERE p.supplier_id = %s
            ORDER BY p.name
        """, (supplier_id,))
        products = cursor.fetchall()
        for p in products:
            p['category'] = p.pop('category_name') or p.get('category')

        return jsonify(products), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()
