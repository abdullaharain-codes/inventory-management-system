import os
import csv
import io
from flask import Blueprint, request, jsonify, current_app, Response
from werkzeug.utils import secure_filename
from db.connection import get_db_connection
from mysql.connector import Error
from middleware.auth_middleware import login_required, admin_required, roles_required
from utils.activity_logger import log_activity
from utils.notifier import create_notification

products_bp = Blueprint('products', __name__)

ALLOWED_EXT = {'png', 'jpg', 'jpeg', 'webp'}
UPLOAD_DIR  = os.path.join('static', 'uploads', 'products')


def _validate_uniqueness(cursor, field, value, exclude_id=None):
    """Check if a given field value (sku or barcode) already exists.
       exclude_id: skip this product_id (for updates)."""
    if exclude_id:
        cursor.execute(
            f"SELECT product_id FROM products WHERE LOWER({field}) = LOWER(%s) AND product_id != %s",
            (value, exclude_id)
        )
    else:
        cursor.execute(
            f"SELECT product_id FROM products WHERE LOWER({field}) = LOWER(%s)",
            (value,)
        )
    return cursor.fetchone() is not None


def _allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


# ── Search (must be registered BEFORE <int:product_id>) ──────────
@products_bp.route('/api/products/search', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
def search_products():
    """Search products by name, category, sku, or barcode"""
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
            SELECT p.*, s.name as supplier_name,
                   c.name AS category_name
            FROM products p
            LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
            LEFT JOIN categories c ON p.category_id = c.category_id
            WHERE p.name LIKE %s
               OR p.category LIKE %s
               OR c.name LIKE %s
               OR p.sku LIKE %s
               OR p.barcode LIKE %s
            ORDER BY p.product_id
        """
        like_term = f"%{search_term}%"
        cursor.execute(query, (like_term, like_term, like_term, like_term, like_term))
        products = cursor.fetchall()
        for p in products:
            p['category'] = p.pop('category_name') or p.get('category')
        return jsonify(products), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── List all ──────────────────────────────────────────────────────
@products_bp.route('/api/products', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
def get_all_products():
    """Fetch all products with supplier name and category name"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        query = """
            SELECT p.*, s.name as supplier_name,
                   c.name AS category_name
            FROM products p
            LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
            LEFT JOIN categories c ON p.category_id = c.category_id
            ORDER BY p.product_id
        """
        cursor.execute(query)
        products = cursor.fetchall()
        for p in products:
            p['category'] = p.pop('category_name') or p.get('category')
        return jsonify(products), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Get single ────────────────────────────────────────────────────
@products_bp.route('/api/products/<int:product_id>', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
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
            SELECT p.*, s.name as supplier_name,
                   c.name AS category_name
            FROM products p
            LEFT JOIN suppliers s ON p.supplier_id = s.supplier_id
            LEFT JOIN categories c ON p.category_id = c.category_id
            WHERE p.product_id = %s
        """
        cursor.execute(query, (product_id,))
        product = cursor.fetchone()

        if not product:
            return jsonify({'error': 'Product not found'}), 404
        product['category'] = product.pop('category_name') or product.get('category')
        return jsonify(product), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Create ────────────────────────────────────────────────────────
@products_bp.route('/api/products', methods=['POST'])
@roles_required('admin', 'manager')
def add_product():
    """Add new product with optional sku, barcode, unit_of_measure, tax_rate"""
    connection = None
    cursor = None
    try:
        data = request.get_json()
        if not data or 'name' not in data or 'price' not in data:
            return jsonify({'error': 'name and price are required'}), 400

        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)

        sku     = data.get('sku')
        barcode = data.get('barcode')

        if sku and _validate_uniqueness(cursor, 'sku', sku):
            return jsonify({'error': f"SKU '{sku}' already exists"}), 409

        if barcode and _validate_uniqueness(cursor, 'barcode', barcode):
            return jsonify({'error': f"Barcode '{barcode}' already exists"}), 409

        category_id = data.get('category_id')
        category = data.get('category')
        if category_id is not None:
            category = None
        elif category is None:
            category = None

        query = """
            INSERT INTO products (name, description, category, category_id, sku, barcode,
                                  unit_of_measure, tax_rate, price, cost_price, stock_quantity, supplier_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        values = (
            data.get('name'),
            data.get('description'),
            category,
            category_id,
            sku,
            barcode,
            data.get('unit_of_measure', 'pcs'),
            data.get('tax_rate', 0.00),
            data.get('price'),
            data.get('cost_price'),
            data.get('stock_quantity', 0),
            data.get('supplier_id')
        )
        cursor.execute(query, values)
        connection.commit()
        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='products',
            action_type='create',
            description=f"Created product '{data.get('name')}' (ID #{cursor.lastrowid})"
        )
        create_notification(
            title='Product Added',
            message=f"{request.current_user['name']} added product '{data.get('name')}' (ID #{cursor.lastrowid}).",
            notification_type='product_added',
            target_role='all',
            related_id=cursor.lastrowid,
            related_type='product'
        )
        return jsonify({'message': 'Product added successfully', 'product_id': cursor.lastrowid}), 201

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Update ────────────────────────────────────────────────────────
@products_bp.route('/api/products/<int:product_id>', methods=['PUT'])
@roles_required('admin', 'manager')
def update_product(product_id):
    """Update product — supports sku, barcode, unit_of_measure, tax_rate"""
    connection = None
    cursor = None
    try:
        data = request.get_json()
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT product_id FROM products WHERE product_id = %s", (product_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'Product not found'}), 404

        sku     = data.get('sku')
        barcode = data.get('barcode')

        if sku is not None and _validate_uniqueness(cursor, 'sku', sku, exclude_id=product_id):
            return jsonify({'error': f"SKU '{sku}' already exists"}), 409

        if barcode is not None and _validate_uniqueness(cursor, 'barcode', barcode, exclude_id=product_id):
            return jsonify({'error': f"Barcode '{barcode}' already exists"}), 409

        update_fields = []
        values = []

        for field in ['name', 'description', 'price', 'cost_price', 'stock_quantity', 'supplier_id',
                       'category_id', 'sku', 'barcode', 'unit_of_measure', 'tax_rate']:
            if field in data:
                update_fields.append(f"{field} = %s")
                values.append(data[field])

        if 'category_id' in data:
            update_fields.append("category = %s")
            values.append(None)

        if 'category' in data and 'category_id' not in data:
            update_fields.append("category = %s")
            values.append(data['category'])

        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400

        values.append(product_id)
        cursor.execute(f"UPDATE products SET {', '.join(update_fields)} WHERE product_id = %s", values)
        connection.commit()
        changed = ', '.join(update_fields)
        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='products',
            action_type='update',
            description=f"Updated product #{product_id}: {changed}"
        )
        create_notification(
            title='Product Updated',
            message=f"{request.current_user['name']} updated product #{product_id}: {changed}.",
            notification_type='product_updated',
            target_role='all',
            related_id=product_id,
            related_type='product'
        )
        return jsonify({'message': 'Product updated successfully'}), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Image upload ──────────────────────────────────────────────────
@products_bp.route('/api/products/<int:product_id>/image', methods=['POST'])
@roles_required('admin', 'manager')
def upload_product_image(product_id):
    """Upload or replace a product image (jpg/png/webp, max 5MB)"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT product_id, name, image_path FROM products WHERE product_id = %s", (product_id,))
        product = cursor.fetchone()
        if not product:
            return jsonify({'error': 'Product not found'}), 404

        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400

        file = request.files['image']
        if not file.filename:
            return jsonify({'error': 'No file selected'}), 400

        if not _allowed_file(file.filename):
            return jsonify({'error': 'Invalid file type. Allowed: jpg, jpeg, png, webp'}), 400

        filename = secure_filename(f"prod_{product_id}_{file.filename}")
        upload_path = os.path.join(current_app.root_path, UPLOAD_DIR)
        os.makedirs(upload_path, exist_ok=True)
        filepath = os.path.join(upload_path, filename)

        file.save(filepath)

        rel_path = f"{UPLOAD_DIR}/{filename}".replace('\\', '/')

        # Delete old image if it exists
        if product['image_path']:
            old_path = os.path.join(current_app.root_path, product['image_path'])
            if os.path.exists(old_path):
                os.remove(old_path)

        cursor.execute("UPDATE products SET image_path = %s WHERE product_id = %s", (rel_path, product_id))
        connection.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='products',
            action_type='image_upload',
            description=f"Uploaded image for product '{product['name']}' (ID #{product_id})"
        )

        return jsonify({'message': 'Image uploaded successfully', 'image_path': rel_path}), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Cost price CSV template export ────────────────────────────────
@products_bp.route('/api/products/export-cost-template', methods=['GET'])
@roles_required('admin', 'manager')
def export_cost_template():
    """Download a CSV template pre-filled with current product data for cost_price bulk update"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT product_id, name, sku, price, cost_price FROM products ORDER BY product_id"
        )
        products = cursor.fetchall()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(['product_id', 'name', 'sku', 'current_selling_price', 'cost_price'])
        for p in products:
            writer.writerow([
                p['product_id'],
                p['name'],
                p['sku'] or '',
                p['price'],
                p['cost_price'] if p['cost_price'] is not None else ''
            ])

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='products',
            action_type='export',
            description=f"Exported cost_price CSV template ({len(products)} products)"
        )

        output = buf.getvalue()
        buf.close()
        return Response(
            output,
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename="cost_price_template.csv"'}
        )

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Cost price CSV bulk import ────────────────────────────────────
@products_bp.route('/api/products/import-cost-prices', methods=['POST'])
@roles_required('admin', 'manager')
def import_cost_prices():
    """Bulk update cost_price from an uploaded CSV file"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400

    file = request.files['file']
    if not file.filename or not file.filename.lower().endswith('.csv'):
        return jsonify({'error': 'Please upload a .csv file'}), 400

    try:
        stream = io.StringIO(file.stream.read().decode('utf-8-sig'))
        reader = csv.DictReader(stream)
    except Exception:
        return jsonify({'error': 'Could not parse CSV file'}), 400

    required_cols = {'product_id', 'cost_price'}
    if not required_cols.issubset(set(reader.fieldnames or [])):
        return jsonify({'error': f'CSV must have columns: product_id, cost_price'}), 400

    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        updated = 0
        skipped_empty = 0
        errors = []
        warnings = []
        valid_updates = []

        for row_num, row in enumerate(reader, start=2):
            raw_pid = (row.get('product_id') or '').strip()
            raw_cost = (row.get('cost_price') or '').strip()
            csv_name = (row.get('name') or '').strip()

            if not raw_pid:
                errors.append({'row': row_num, 'product_id': None, 'reason': 'Missing product_id'})
                continue

            try:
                product_id = int(raw_pid)
            except (ValueError, TypeError):
                errors.append({'row': row_num, 'product_id': raw_pid, 'reason': f'Invalid product_id: {raw_pid}'})
                continue

            if raw_cost == '' or raw_cost is None:
                skipped_empty += 1
                continue

            try:
                cost_price = float(raw_cost)
            except (ValueError, TypeError):
                errors.append({'row': row_num, 'product_id': product_id, 'reason': f'Invalid cost_price: {raw_cost}'})
                continue

            if cost_price < 0:
                errors.append({'row': row_num, 'product_id': product_id, 'reason': f'cost_price cannot be negative: {cost_price}'})
                continue

            cursor.execute("SELECT product_id, name FROM products WHERE product_id = %s", (product_id,))
            db_product = cursor.fetchone()
            if not db_product:
                errors.append({'row': row_num, 'product_id': product_id, 'reason': f'product_id {product_id} not found'})
                continue

            if csv_name and csv_name != db_product['name']:
                warnings.append({
                    'row': row_num,
                    'product_id': product_id,
                    'message': f"Name mismatch — CSV says '{csv_name}' but DB has '{db_product['name']}'. Updated anyway using product_id."
                })

            valid_updates.append((cost_price, product_id))

        try:
            for cost_price, product_id in valid_updates:
                cursor.execute(
                    "UPDATE products SET cost_price = %s WHERE product_id = %s",
                    (cost_price, product_id)
                )
            connection.commit()
            updated = len(valid_updates)
        except Error as e:
            connection.rollback()
            return jsonify({'error': f'Database error during update, rolled back: {str(e)}'}), 500

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='products',
            action_type='bulk_update',
            description=f"Bulk cost_price import: {updated} updated, {len(errors)} errors"
        )

        return jsonify({
            'updated': updated,
            'skipped_empty': skipped_empty,
            'errors': errors,
            'warnings': warnings
        }), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()


# ── Delete ────────────────────────────────────────────────────────
@products_bp.route('/api/products/<int:product_id>', methods=['DELETE'])
@admin_required
def delete_product(product_id):
    """Delete product"""
    connection = None
    cursor = None
    try:
        connection = get_db_connection()
        if not connection:
            return jsonify({'error': 'Database connection failed'}), 500

        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT product_id, name FROM products WHERE product_id = %s", (product_id,))
        product = cursor.fetchone()
        if not product:
            return jsonify({'error': 'Product not found'}), 404

        cursor.execute("DELETE FROM products WHERE product_id = %s", (product_id,))
        connection.commit()
        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='products',
            action_type='delete',
            description=f"Deleted product '{product['name']}' (ID #{product_id})"
        )
        create_notification(
            title='Product Deleted',
            message=f"{request.current_user['name']} deleted product '{product['name']}' (ID #{product_id}).",
            notification_type='product_deleted',
            target_role='all',
            related_id=product_id,
            related_type='product'
        )
        return jsonify({'message': 'Product deleted successfully'}), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor: cursor.close()
        if connection: connection.close()
