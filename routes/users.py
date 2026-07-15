from flask import Blueprint, request, jsonify
from db.connection import get_db_connection
from mysql.connector import Error
import bcrypt
import re
from middleware.auth_middleware import admin_required
from routes.auth import _validate_password_strength, _sanitize_string
from utils.activity_logger import log_activity
from utils.notifier import create_notification

users_bp = Blueprint('users', __name__)


def _serialize_user(user):
    """Strip out password_hash and convert types for JSON response."""
    if not user:
        return None
    return {
        'user_id':    user['user_id'],
        'name':       user['name'],
        'email':      user['email'],
        'role':       user['role'],
        'is_active':  bool(user['is_active']),
        'created_at': user['created_at'].isoformat() if user.get('created_at') else None
    }


# ── List all users ─────────────────────────────────────────────

@users_bp.route('/api/users', methods=['GET'])
@admin_required
def get_all_users():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, name, email, role, is_active, created_at "
            "FROM users ORDER BY created_at DESC"
        )
        users = [_serialize_user(u) for u in cursor.fetchall()]
        return jsonify(users), 200
    except Error:
        return jsonify({'error': 'Failed to fetch users'}), 500
    finally:
        cursor.close()
        conn.close()


# ── Get single user ────────────────────────────────────────────

@users_bp.route('/api/users/<int:user_id>', methods=['GET'])
@admin_required
def get_user(user_id):
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, name, email, role, is_active, created_at "
            "FROM users WHERE user_id = %s", (user_id,)
        )
        user = cursor.fetchone()
        if not user:
            return jsonify({'error': 'User not found'}), 404
        return jsonify(_serialize_user(user)), 200
    except Error:
        return jsonify({'error': 'Failed to fetch user'}), 500
    finally:
        cursor.close()
        conn.close()


# ── Create user ────────────────────────────────────────────────

@users_bp.route('/api/users', methods=['POST'])
@admin_required
def create_user():
    data = request.get_json() or {}

    name     = _sanitize_string(data.get('name', ''), 100)
    email    = _sanitize_string(data.get('email', ''), 100).lower()
    password = data.get('password', '')
    role     = data.get('role', 'staff')

    if not name or len(name) < 2:
        return jsonify({'error': 'Name must be at least 2 characters'}), 400
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({'error': 'Invalid email address'}), 400
    if role not in ('admin', 'manager', 'staff'):
        return jsonify({'error': 'Role must be admin, manager, or staff'}), 400

    ok, msg = _validate_password_strength(password)
    if not ok:
        return jsonify({'error': msg}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({'error': 'A user with this email already exists'}), 400

        password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt(rounds=12)
        ).decode('utf-8')

        cursor.execute("""
            INSERT INTO users (name, email, password_hash, role)
            VALUES (%s, %s, %s, %s)
        """, (name, email, password_hash, role))
        conn.commit()

        new_id = cursor.lastrowid
        cursor.execute(
            "SELECT user_id, name, email, role, is_active, created_at "
            "FROM users WHERE user_id = %s", (new_id,)
        )
        user = cursor.fetchone()
        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='users',
            action_type='create',
            description=f"Created user '{name}' ({email}) with role '{role}'"
        )
        create_notification(
            title='User Created',
            message=f"{request.current_user['name']} created user '{name}' ({email}) with role '{role}'.",
            notification_type='user_created',
            target_role='admin',
            related_id=new_id,
            related_type='user'
        )
        return jsonify(_serialize_user(user)), 201

    except Error:
        conn.rollback()
        return jsonify({'error': 'Failed to create user'}), 500
    finally:
        cursor.close()
        conn.close()


# ── Update user (name, email, role) ────────────────────────────

@users_bp.route('/api/users/<int:user_id>', methods=['PUT'])
@admin_required
def update_user(user_id):
    current_user = request.current_user
    data = request.get_json() or {}

    # Safety: admin cannot change their own role
    if user_id == current_user['user_id']:
        new_role = data.get('role')
        if new_role and new_role != current_user['role']:
            return jsonify({'error': 'You cannot change your own role.'}), 400

    name  = _sanitize_string(data.get('name', ''), 100)
    email = _sanitize_string(data.get('email', ''), 100).lower()
    role  = data.get('role', '')

    if not name or len(name) < 2:
        return jsonify({'error': 'Name must be at least 2 characters'}), 400
    if email and not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({'error': 'Invalid email address'}), 400
    if role and role not in ('admin', 'manager', 'staff'):
        return jsonify({'error': 'Role must be admin, manager, or staff'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        cursor = conn.cursor(dictionary=True)

        # Verify user exists
        cursor.execute("SELECT user_id, role FROM users WHERE user_id = %s", (user_id,))
        existing = cursor.fetchone()
        if not existing:
            return jsonify({'error': 'User not found'}), 404

        # Check email uniqueness if changed
        if email:
            cursor.execute(
                "SELECT user_id FROM users WHERE email = %s AND user_id != %s",
                (email, user_id)
            )
            if cursor.fetchone():
                return jsonify({'error': 'A user with this email already exists'}), 400

        fields = []
        values = []
        if name:
            fields.append("name = %s")
            values.append(name)
        if email:
            fields.append("email = %s")
            values.append(email)
        if role:
            fields.append("role = %s")
            values.append(role)

        if not fields:
            return jsonify({'error': 'No fields to update'}), 400

        values.append(user_id)
        cursor.execute(f"UPDATE users SET {', '.join(fields)} WHERE user_id = %s", values)
        conn.commit()

        cursor.execute(
            "SELECT user_id, name, email, role, is_active, created_at "
            "FROM users WHERE user_id = %s", (user_id,)
        )
        user = cursor.fetchone()
        changed = []
        if name: changed.append(f"name='{name}'")
        if email: changed.append(f"email='{email}'")
        if role: changed.append(f"role='{role}'")
        log_activity(
            user_id=current_user['user_id'],
            user_role=current_user['role'],
            module='users',
            action_type='update',
            description=f"Updated user #{user_id}: {', '.join(changed)}"
        )
        create_notification(
            title='User Updated',
            message=f"{current_user['name']} updated user #{user_id}: {', '.join(changed)}.",
            notification_type='user_updated',
            target_role='admin',
            related_id=user_id,
            related_type='user'
        )
        return jsonify(_serialize_user(user)), 200

    except Error:
        conn.rollback()
        return jsonify({'error': 'Failed to update user'}), 500
    finally:
        cursor.close()
        conn.close()


# ── Reset password (admin) ─────────────────────────────────────

@users_bp.route('/api/users/<int:user_id>/password', methods=['PUT'])
@admin_required
def reset_user_password(user_id):
    data         = request.get_json() or {}
    new_password = data.get('new_password', '')

    ok, msg = _validate_password_strength(new_password)
    if not ok:
        return jsonify({'error': msg}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        if not cursor.fetchone():
            return jsonify({'error': 'User not found'}), 404

        password_hash = bcrypt.hashpw(
            new_password.encode('utf-8'),
            bcrypt.gensalt(rounds=12)
        ).decode('utf-8')

        cursor.execute(
            "UPDATE users SET password_hash = %s, failed_attempts = 0, "
            "locked_until = NULL WHERE user_id = %s",
            (password_hash, user_id)
        )
        conn.commit()
        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='users',
            action_type='password_reset',
            description=f"Admin reset password for user #{user_id}"
        )
        return jsonify({'message': 'Password updated successfully'}), 200

    except Error:
        conn.rollback()
        return jsonify({'error': 'Failed to update password'}), 500
    finally:
        cursor.close()
        conn.close()


# ── Toggle user active status ──────────────────────────────────

@users_bp.route('/api/users/<int:user_id>/status', methods=['PUT'])
@admin_required
def toggle_user_status(user_id):
    current_user = request.current_user

    # Safety: cannot deactivate yourself
    if user_id == current_user['user_id']:
        return jsonify({'error': 'You cannot deactivate your own account.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, role, is_active FROM users WHERE user_id = %s",
            (user_id,)
        )
        user = cursor.fetchone()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        new_status = not user['is_active']

        # Safety: prevent deactivating the last active admin
        if user['is_active'] and user['role'] == 'admin' and not new_status:
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin' AND is_active = 1"
            )
            count = cursor.fetchone()['cnt']
            if count <= 1:
                return jsonify({'error': 'Cannot deactivate the last active admin account.'}), 400

        cursor.execute(
            "UPDATE users SET is_active = %s WHERE user_id = %s",
            (int(new_status), user_id)
        )
        conn.commit()

        cursor.execute(
            "SELECT user_id, name, email, role, is_active, created_at "
            "FROM users WHERE user_id = %s", (user_id,)
        )
        updated = cursor.fetchone()
        status_label = 'activated' if updated['is_active'] else 'deactivated'
        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='users',
            action_type='status_change',
            description=f"{status_label} user #{user_id} ({updated['name']})"
        )
        return jsonify(_serialize_user(updated)), 200

    except Error:
        conn.rollback()
        return jsonify({'error': 'Failed to update user status'}), 500
    finally:
        cursor.close()
        conn.close()


# ── Delete user (alias for deactivation) ───────────────────────

@users_bp.route('/api/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    current_user = request.current_user

    if user_id == current_user['user_id']:
        return jsonify({'error': 'You cannot deactivate your own account.'}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, role, is_active FROM users WHERE user_id = %s",
            (user_id,)
        )
        user = cursor.fetchone()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        if user['is_active'] and user['role'] == 'admin':
            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin' AND is_active = 1"
            )
            count = cursor.fetchone()['cnt']
            if count <= 1:
                return jsonify({'error': 'Cannot deactivate the last active admin account.'}), 400

        cursor.execute(
            "UPDATE users SET is_active = 0 WHERE user_id = %s",
            (user_id,)
        )
        conn.commit()
        log_activity(
            user_id=request.current_user['user_id'],
            user_role=request.current_user['role'],
            module='users',
            action_type='delete',
            description=f"Deactivated (DELETE) user #{user_id}"
        )
        create_notification(
            title='User Deactivated',
            message=f"{request.current_user['name']} deactivated user #{user_id}.",
            notification_type='user_deleted',
            target_role='admin',
            related_id=user_id,
            related_type='user'
        )
        return jsonify({'message': 'User deactivated successfully'}), 200

    except Error:
        conn.rollback()
        return jsonify({'error': 'Failed to deactivate user'}), 500
    finally:
        cursor.close()
        conn.close()
