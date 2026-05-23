from flask import Blueprint, request, jsonify
from db.connection import get_db_connection
from mysql.connector import Error

products_bp = Blueprint('products', __name__)

# Search must be registered BEFORE <int:product_id> to avoid conflict
@products_bp.route('/api/products/search', methods=['GET'])
def search_products():
    """Search products by name or category"""
    search_term = request.args.get('q', '')
    if not search_term:
        return jsonify({'error': 'Search term (q) is required'}), 400

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT p.*, s.name as supplier_name
            FROM products p
            LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
            WHERE p.name LIKE %s OR p.category LIKE %s
            ORDER BY p.product_id
        """
        like_term = f"%{search_term}%"
        cursor.execute(query, (like_term, like_term))
        products = cursor.fetchall()
        return jsonify(products), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@products_bp.route('/api/products', methods=['GET'])
def get_all_products():
    """Fetch all products with supplier name"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT p.*, s.name as supplier_name
            FROM products p
            LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
            ORDER BY p.product_id
        """
        cursor.execute(query)
        products = cursor.fetchall()
        return jsonify(products), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@products_bp.route('/api/products/<int:product_id>', methods=['GET'])
def get_product_by_id(product_id):
    """Fetch single product by ID"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT p.*, s.name as supplier_name
            FROM products p
            LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
            WHERE p.product_id = %s
        """
        cursor.execute(query, (product_id,))
        product = cursor.fetchone()

        if not product:
            return jsonify({'error': 'Product not found'}), 404
        return jsonify(product), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@products_bp.route('/api/products', methods=['POST'])
def add_product():
    """Add new product"""
    connection = None
    cursor = None
    try:
        data = request.get_json()
        if not data or 'name' not in data or 'price' not in data:
            return jsonify({'error': 'name and price are required'}), 400

        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor()
        query = """
            INSERT INTO products (name, description, category, price, stock_quantity, supplier_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        values = (
            data.get('name'),
            data.get('description'),
            data.get('category'),
            data.get('price'),
            data.get('stock_quantity', 0),
            data.get('supplier_id')
        )
        cursor.execute(query, values)
        connection.commit()
        return jsonify({'message': 'Product added successfully', 'product_id': cursor.lastrowid}), 201

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@products_bp.route('/api/products/<int:product_id>', methods=['PUT'])
def update_product(product_id):
    """Update product"""
    connection = None
    cursor = None
    try:
        data = request.get_json()
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor()
        cursor.execute("SELECT product_id FROM products WHERE product_id = %s", (product_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Product not found'}), 404

        update_fields = []
        values = []
        for field in ['name', 'description', 'category', 'price', 'stock_quantity', 'supplier_id']:
            if field in data:
                update_fields.append(f"{field} = %s")
                values.append(data[field])

        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400

        values.append(product_id)
        cursor.execute(f"UPDATE products SET {', '.join(update_fields)} WHERE product_id = %s", values)
        connection.commit()
        return jsonify({'message': 'Product updated successfully'}), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


@products_bp.route('/api/products/<int:product_id>', methods=['DELETE'])
def delete_product(product_id):
    """Delete product"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor()
        cursor.execute("SELECT product_id FROM products WHERE product_id = %s", (product_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Product not found'}), 404

        cursor.execute("DELETE FROM products WHERE product_id = %s", (product_id,))
        connection.commit()
        return jsonify({'message': 'Product deleted successfully'}), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()