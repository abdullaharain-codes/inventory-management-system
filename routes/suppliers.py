from flask import Blueprint, request, jsonify
from db.connection import get_db_connection
from mysql.connector import Error

suppliers_bp = Blueprint('suppliers', __name__)

@suppliers_bp.route('/api/suppliers', methods=['GET'])
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
def get_supplier_by_id(supplier_id):
    """Fetch single supplier"""
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
        
        return jsonify(supplier), 200
    
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@suppliers_bp.route('/api/suppliers', methods=['POST'])
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
        
        cursor = connection.cursor()
        query = """
            INSERT INTO suppliers (name, contact_person, phone, email, address)
            VALUES (%s, %s, %s, %s, %s)
        """
        values = (
            data.get('name'),
            data.get('contact_person'),
            data.get('phone'),
            data.get('email'),
            data.get('address')
        )
        
        cursor.execute(query, values)
        connection.commit()
        
        return jsonify({
            'message': 'Supplier added successfully',
            'supplier_id': cursor.lastrowid
        }), 201
    
    except Error as e:
        # Check for duplicate email error
        if 'Duplicate entry' in str(e) and 'email' in str(e):
            return jsonify({'error': 'Email already exists'}), 409
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@suppliers_bp.route('/api/suppliers/<int:supplier_id>', methods=['PUT'])
def update_supplier(supplier_id):
    """Update supplier"""
    connection = None
    cursor = None
    try:
        data = request.get_json()
        
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = connection.cursor()
        
        # Check if supplier exists
        cursor.execute("SELECT supplier_id FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Supplier not found'}), 404
        
        # Build dynamic update query
        update_fields = []
        values = []
        
        updatable_fields = ['name', 'contact_person', 'phone', 'email', 'address']
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
        
        return jsonify({'message': 'Supplier updated successfully'}), 200
    
    except Error as e:
        if 'Duplicate entry' in str(e) and 'email' in str(e):
            return jsonify({'error': 'Email already exists'}), 409
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()

@suppliers_bp.route('/api/suppliers/<int:supplier_id>', methods=['DELETE'])
def delete_supplier(supplier_id):
    """Delete supplier"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = connection.cursor()
        
        # Check if supplier exists
        cursor.execute("SELECT supplier_id FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Supplier not found'}), 404
        
        # Check if supplier has products
        cursor.execute("SELECT COUNT(*) FROM products WHERE supplier_id = %s", (supplier_id,))
        product_count = cursor.fetchone()[0]
        if product_count > 0:
            return jsonify({'error': 'Cannot delete supplier with existing products. Update products first.'}), 409
        
        cursor.execute("DELETE FROM suppliers WHERE supplier_id = %s", (supplier_id,))
        connection.commit()
        
        return jsonify({'message': 'Supplier deleted successfully'}), 200
    
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if connection:
            connection.close()