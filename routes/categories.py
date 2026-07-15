from flask import Blueprint, request, jsonify
from db.connection import get_db_connection
from mysql.connector import Error
from middleware.auth_middleware import admin_required, roles_required
from utils.activity_logger import log_activity

categories_bp = Blueprint('categories', __name__)


@categories_bp.route('/api/categories', methods=['GET'])
@roles_required('admin', 'manager', 'staff')
def get_all_categories():
    """List all categories with parent name and product count"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT
                c.*,
                p.name AS parent_name,
                (SELECT COUNT(*) FROM products WHERE category_id = c.category_id) AS product_count
            FROM categories c
            LEFT JOIN categories p ON c.parent_category_id = p.category_id
            ORDER BY c.name
        """)
        categories = cursor.fetchall()
        return jsonify(categories), 200
    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@categories_bp.route('/api/categories', methods=['POST'])
@roles_required('admin', 'manager')
def add_category():
    """Create a new category"""
    data = request.get_json()
    if not data or 'name' not in data:
        return jsonify({'error': 'Category name is required'}), 400

    name = data['name'].strip()
    if not name:
        return jsonify({'error': 'Category name cannot be empty'}), 400

    parent_category_id = data.get('parent_category_id')

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT category_id FROM categories WHERE name = %s", (name,))
        if cursor.fetchone():
            return jsonify({'error': f"Category '{name}' already exists"}), 409

        if parent_category_id:
            cursor.execute("SELECT category_id FROM categories WHERE category_id = %s", (parent_category_id,))
            if not cursor.fetchone():
                return jsonify({'error': 'Parent category not found'}), 404

        cursor.execute(
            "INSERT INTO categories (name, parent_category_id) VALUES (%s, %s)",
            (name, parent_category_id)
        )
        conn.commit()
        new_id = cursor.lastrowid

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='categories',
            action_type='create',
            description=f"Created category '{name}' (ID #{new_id})"
        )

        return jsonify({'message': 'Category created successfully', 'category_id': new_id}), 201

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@categories_bp.route('/api/categories/<int:category_id>', methods=['PUT'])
@roles_required('admin', 'manager')
def update_category(category_id):
    """Edit category name or parent"""
    data = request.get_json()

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM categories WHERE category_id = %s", (category_id,))
        existing = cursor.fetchone()
        if not existing:
            return jsonify({'error': 'Category not found'}), 404

        update_fields = []
        values = []

        if 'name' in data:
            new_name = data['name'].strip()
            if not new_name:
                return jsonify({'error': 'Category name cannot be empty'}), 400

            cursor.execute("SELECT category_id FROM categories WHERE name = %s AND category_id != %s", (new_name, category_id))
            if cursor.fetchone():
                return jsonify({'error': f"Category '{new_name}' already exists"}), 409

            update_fields.append("name = %s")
            values.append(new_name)

        if 'parent_category_id' in data:
            parent_id = data['parent_category_id']

            if parent_id is not None:
                if parent_id == category_id:
                    return jsonify({'error': 'A category cannot be its own parent'}), 400

                cursor.execute("SELECT category_id FROM categories WHERE category_id = %s", (parent_id,))
                if not cursor.fetchone():
                    return jsonify({'error': 'Parent category not found'}), 404

                # Prevent circular: check if the proposed parent is a descendant of this category
                cursor.execute("""
                    WITH RECURSIVE descendants AS (
                        SELECT category_id FROM categories WHERE parent_category_id = %s
                        UNION ALL
                        SELECT c.category_id FROM categories c
                        JOIN descendants d ON c.parent_category_id = d.category_id
                    )
                    SELECT category_id FROM descendants WHERE category_id = %s
                """, (category_id, parent_id))
                if cursor.fetchone():
                    return jsonify({'error': 'Circular parent relationship detected'}), 400

            update_fields.append("parent_category_id = %s")
            values.append(parent_id)

        if not update_fields:
            return jsonify({'error': 'No fields to update'}), 400

        values.append(category_id)
        cursor.execute(f"UPDATE categories SET {', '.join(update_fields)} WHERE category_id = %s", values)
        conn.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='categories',
            action_type='update',
            description=f"Updated category #{category_id}: {', '.join(update_fields)}"
        )

        return jsonify({'message': 'Category updated successfully'}), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()


@categories_bp.route('/api/categories/<int:category_id>', methods=['DELETE'])
@admin_required
def delete_category(category_id):
    """Delete category — blocked if products are assigned"""
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM categories WHERE category_id = %s", (category_id,))
        existing = cursor.fetchone()
        if not existing:
            return jsonify({'error': 'Category not found'}), 404

        cursor.execute("SELECT COUNT(*) AS cnt FROM products WHERE category_id = %s", (category_id,))
        product_count = cursor.fetchone()['cnt']
        if product_count > 0:
            return jsonify({
                'error': f'Cannot delete category — {product_count} product(s) are assigned to it. Reassign them first.'
            }), 409

        # Also check sub-categories
        cursor.execute("SELECT COUNT(*) AS cnt FROM categories WHERE parent_category_id = %s", (category_id,))
        child_count = cursor.fetchone()['cnt']
        if child_count > 0:
            return jsonify({
                'error': f'Cannot delete category — {child_count} sub-category(ies) are assigned to it. Reassign them first.'
            }), 409

        cursor.execute("DELETE FROM categories WHERE category_id = %s", (category_id,))
        conn.commit()

        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='categories',
            action_type='delete',
            description=f"Deleted category '{existing['name']}' (ID #{category_id})"
        )

        return jsonify({'message': 'Category deleted successfully'}), 200

    except Error as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cursor.close()
        conn.close()
