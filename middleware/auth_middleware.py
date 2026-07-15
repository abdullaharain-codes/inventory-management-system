# middleware/auth_middleware.py
from functools import wraps
from flask import request, jsonify, redirect, make_response
import jwt
import os
from config import JWT_SECRET_KEY
from db.connection import get_db_connection


def _decode_token(token):
    """Decode and validate a JWT token."""
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])


def get_token_from_request():
    """
    Try to get JWT from:
    1. Authorization: Bearer <token> header
    2. access_token cookie
    """
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header.split(' ', 1)[1]
    return request.cookies.get('access_token')


def login_required(f):
    """
    Decorator — protects API routes and page routes.
    API routes (starting with /api/) return JSON 401.
    Page routes redirect to /login.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        token = get_token_from_request()

        if not token:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect('/login')

        try:
            payload = _decode_token(token)
        except jwt.ExpiredSignatureError:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Token expired', 'code': 'TOKEN_EXPIRED'}), 401
            return redirect('/login')
        except jwt.InvalidTokenError:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Invalid token'}), 401
            return redirect('/login')

        # Verify user still exists and is active
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database error'}), 500
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT user_id, name, email, role, is_active FROM users WHERE user_id = %s",
                (payload['user_id'],)
            )
            user = cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

        if not user or not user['is_active']:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Account not found or disabled'}), 401
            return redirect('/login')

        # Attach user to request context
        request.current_user = user
        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    """Decorator — restricts route to admin role only."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if request.current_user.get('role') != 'admin':
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Admin access required'}), 403
            return redirect('/dashboard')
        return f(*args, **kwargs)
    return decorated


def staff_or_admin_required(f):
    """Decorator — allows both admin and staff."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        role = request.current_user.get('role')
        if role not in ('admin', 'staff'):
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Access denied'}), 403
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated


def roles_required(*allowed_roles):
    """
    Flexible decorator — allows only specified roles.
    Usage: @roles_required('admin', 'manager')
    Combines login_required + role check.
    Returns 403 JSON for API routes, redirect to /dashboard for page routes.
    """
    def decorator(f):
        @wraps(f)
        @login_required
        def decorated(*args, **kwargs):
            role = request.current_user.get('role')
            if role not in allowed_roles:
                if request.path.startswith('/api/'):
                    return jsonify({'error': 'Access denied. Required role: ' + ', '.join(allowed_roles)}), 403
                return redirect('/dashboard')
            return f(*args, **kwargs)
        return decorated
    return decorator