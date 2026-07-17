# routes/auth.py
import re
import jwt
import bcrypt
import secrets
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify, render_template, redirect, make_response
from db.connection import get_db_connection
from mysql.connector import Error
from config import (
    JWT_SECRET_KEY, JWT_ACCESS_TOKEN_EXPIRES, JWT_REFRESH_TOKEN_EXPIRES,
    MAX_LOGIN_ATTEMPTS, LOCKOUT_MINUTES, IS_PRODUCTION
)
from utils.activity_logger import log_activity
from utils.notifier import create_notification

auth_bp = Blueprint('auth', __name__)


# ── Helpers ───────────────────────────────────────────────────────

def _generate_access_token(user_id, role):
    payload = {
        'user_id': user_id,
        'role':    role,
        'type':    'access',
        'exp':     datetime.utcnow() + timedelta(seconds=JWT_ACCESS_TOKEN_EXPIRES)
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm='HS256')


def _generate_refresh_token(user_id):
    payload = {
        'user_id': user_id,
        'type':    'refresh',
        'exp':     datetime.utcnow() + timedelta(seconds=JWT_REFRESH_TOKEN_EXPIRES)
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm='HS256')


def _set_auth_cookies(response, access_token, refresh_token):
    """Set tokens in secure HttpOnly cookies."""
    is_prod = IS_PRODUCTION
    response.set_cookie(
        'access_token', access_token,
        httponly=True, secure=is_prod, samesite='Lax',
        max_age=JWT_ACCESS_TOKEN_EXPIRES
    )
    response.set_cookie(
        'refresh_token', refresh_token,
        httponly=True, secure=is_prod, samesite='Lax',
        max_age=JWT_REFRESH_TOKEN_EXPIRES
    )
    return response


def _clear_auth_cookies(response):
    response.delete_cookie('access_token')
    response.delete_cookie('refresh_token')
    return response


def _validate_password_strength(password):
    """
    Returns (True, None) if strong, (False, error_message) if weak.
    Rules: 8+ chars, uppercase, lowercase, digit, special char.
    """
    if len(password) < 8:
        return False, 'Password must be at least 8 characters'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter'
    if not re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter'
    if not re.search(r'\d', password):
        return False, 'Password must contain at least one number'
    if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-]', password):
        return False, 'Password must contain at least one special character'
    return True, None


def _sanitize_string(value, max_length=255):
    """Strip HTML tags and limit length — basic XSS prevention."""
    if not isinstance(value, str):
        return ''
    value = re.sub(r'<[^>]+>', '', value)   # strip tags
    value = value.strip()[:max_length]
    return value


def _safe_error(generic_msg='Invalid credentials'):
    """
    Return a generic message to prevent user enumeration.
    Never reveal whether email exists.
    """
    return jsonify({'error': generic_msg}), 401


# ── Page Routes ───────────────────────────────────────────────────

@auth_bp.route('/login')
def login_page():
    return render_template('login.html')


@auth_bp.route('/register')
def register_page():
    return render_template('register.html')


@auth_bp.route('/forgot-password')
def forgot_password_page():
    return render_template('forgot_password.html')


@auth_bp.route('/reset-password')
def reset_password_page():
    token = request.args.get('token', '')
    return render_template('reset_password.html', token=token)


# ── API: Register ─────────────────────────────────────────────────

@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json() or {}

    name     = _sanitize_string(data.get('name', ''), 100)
    email    = _sanitize_string(data.get('email', ''), 100).lower()
    password = data.get('password', '')
    role     = 'staff'

    # Validate inputs
    if not name or len(name) < 2:
        return jsonify({'error': 'Name must be at least 2 characters'}), 400
    if not re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email):
        return jsonify({'error': 'Invalid email address'}), 400

    ok, msg = _validate_password_strength(password)
    if not ok:
        return jsonify({'error': msg}), 400

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        cursor = conn.cursor(dictionary=True)

        # Check duplicate email — return same message to prevent enumeration
        cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({'error': 'Registration failed. Please check your details.'}), 400

        # Hash password with bcrypt (cost factor 12)
        password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt(rounds=12)
        ).decode('utf-8')

        cursor.execute("""
            INSERT INTO users (name, email, password_hash, role)
            VALUES (%s, %s, %s, %s)
        """, (name, email, password_hash, role))
        conn.commit()

        return jsonify({'message': 'Account created successfully'}), 201

    except Error as e:
        conn.rollback()
        return jsonify({'error': 'Registration failed'}), 500
    finally:
        cursor.close()
        conn.close()


# ── API: Login ────────────────────────────────────────────────────

@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    data     = request.get_json() or {}
    email    = _sanitize_string(data.get('email', ''), 100).lower()
    password = data.get('password', '')

    if not email or not password:
        return _safe_error('Email and password are required')

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT user_id, name, email, password_hash, role,
                   is_active, failed_attempts, locked_until
            FROM users WHERE email = %s
        """, (email,))
        user = cursor.fetchone()

        # Prevent user enumeration — same response whether user exists or not
        if not user:
            return _safe_error()

        if not user['is_active']:
            log_activity(user['user_id'], user['role'], 'auth', 'login_failed', 'Account is disabled')
            return _safe_error('Account is disabled')

        # Check lockout
        if user['locked_until'] and datetime.utcnow() < user['locked_until']:
            log_activity(user['user_id'], user['role'], 'auth', 'login_failed', 'Account is locked')
            remaining = int((user['locked_until'] - datetime.utcnow()).total_seconds() / 60) + 1
            return jsonify({
                'error': f'Account locked. Try again in {remaining} minute(s).'
            }), 429

        # Verify password
        password_matches = bcrypt.checkpw(
            password.encode('utf-8'),
            user['password_hash'].encode('utf-8')
        )

        if not password_matches:
            # Increment failed attempts
            new_attempts = user['failed_attempts'] + 1
            if new_attempts >= MAX_LOGIN_ATTEMPTS:
                locked_until = datetime.utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
                cursor.execute("""
                    UPDATE users
                    SET failed_attempts = %s, locked_until = %s
                    WHERE user_id = %s
                """, (new_attempts, locked_until, user['user_id']))
                conn.commit()
                log_activity(user['user_id'], user['role'], 'auth', 'login_failed', 'Account locked due to too many failed attempts')
                return jsonify({
                    'error': f'Too many failed attempts. Account locked for {LOCKOUT_MINUTES} minutes.'
                }), 429
            else:
                cursor.execute(
                    "UPDATE users SET failed_attempts = %s WHERE user_id = %s",
                    (new_attempts, user['user_id'])
                )
                conn.commit()
                remaining_attempts = MAX_LOGIN_ATTEMPTS - new_attempts
                log_activity(user['user_id'], user['role'], 'auth', 'login_failed', f'Invalid password ({remaining_attempts} attempts remaining)')
                return jsonify({
                    'error': f'Invalid credentials. {remaining_attempts} attempt(s) remaining.'
                }), 401

        # Success — reset failed attempts
        cursor.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE user_id = %s",
            (user['user_id'],)
        )
        conn.commit()

        access_token  = _generate_access_token(user['user_id'], user['role'])
        refresh_token = _generate_refresh_token(user['user_id'])

        log_activity(user['user_id'], user['role'], 'auth', 'login', f"User '{user['name']}' ({user['email']}) logged in")

        if user['role'] in ('manager', 'staff'):
            create_notification(
                title='Staff Login',
                message=f"{user['name']} ({user['role']}) logged in.",
                notification_type='staff_login',
                target_role='admin',
                related_id=user['user_id'],
                related_type='user'
            )

        response = make_response(jsonify({
            'message': 'Login successful',
            'user': {
                'name':  user['name'],
                'email': user['email'],
                'role':  user['role']
            }
        }))
        return _set_auth_cookies(response, access_token, refresh_token)

    except Error as e:
        return jsonify({'error': 'Login failed'}), 500
    finally:
        cursor.close()
        conn.close()


# ── API: Logout ───────────────────────────────────────────────────

@auth_bp.route('/api/auth/logout', methods=['POST'])
def logout():
    response = make_response(jsonify({'message': 'Logged out successfully'}))
    return _clear_auth_cookies(response)


# ── API: Refresh Token ────────────────────────────────────────────

@auth_bp.route('/api/auth/refresh', methods=['POST'])
def refresh_token():
    token = request.cookies.get('refresh_token')
    if not token:
        return jsonify({'error': 'No refresh token'}), 401

    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
        if payload.get('type') != 'refresh':
            return jsonify({'error': 'Invalid token type'}), 401
    except jwt.ExpiredSignatureError:
        return jsonify({'error': 'Refresh token expired. Please login again.'}), 401
    except jwt.InvalidTokenError:
        return jsonify({'error': 'Invalid refresh token'}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, role, is_active FROM users WHERE user_id = %s",
            (payload['user_id'],)
        )
        user = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not user or not user['is_active']:
        return jsonify({'error': 'User not found or disabled'}), 401

    new_access_token = _generate_access_token(user['user_id'], user['role'])
    response = make_response(jsonify({'message': 'Token refreshed'}))
    response.set_cookie(
        'access_token', new_access_token,
        httponly=True, secure=False, samesite='Lax',
        max_age=JWT_ACCESS_TOKEN_EXPIRES
    )
    return response


# ── API: Forgot Password ──────────────────────────────────────────

@auth_bp.route('/api/auth/forgot-password', methods=['POST'])
def forgot_password():
    data  = request.get_json() or {}
    email = _sanitize_string(data.get('email', ''), 100).lower()

    # Always return same message — prevent enumeration
    generic_msg = {'message': 'If this email exists, a reset link has been sent.'}

    if not email:
        return jsonify(generic_msg), 200

    conn = get_db_connection()
    if not conn:
        return jsonify(generic_msg), 200

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT user_id FROM users WHERE email = %s AND is_active = 1", (email,))
        user = cursor.fetchone()

        if user:
            reset_token  = secrets.token_urlsafe(32)
            token_expiry = datetime.utcnow() + timedelta(hours=1)

            # Store token hash in DB (never store raw token)
            import hashlib
            token_hash = hashlib.sha256(reset_token.encode()).hexdigest()

            cursor.execute("""
                UPDATE users
                SET reset_token = %s, reset_token_expiry = %s
                WHERE user_id = %s
            """, (token_hash, token_expiry, user['user_id']))
            conn.commit()

            # In production: send email with reset link instead
            # reset_url = f"http://yoursite.com/reset-password?token={reset_token}"

        return jsonify(generic_msg), 200

    except Error:
        return jsonify(generic_msg), 200
    finally:
        cursor.close()
        conn.close()


# ── API: Reset Password ───────────────────────────────────────────

@auth_bp.route('/api/auth/reset-password', methods=['POST'])
def reset_password():
    data         = request.get_json() or {}
    raw_token    = data.get('token', '')
    new_password = data.get('password', '')

    if not raw_token or not new_password:
        return jsonify({'error': 'Token and new password are required'}), 400

    ok, msg = _validate_password_strength(new_password)
    if not ok:
        return jsonify({'error': msg}), 400

    import hashlib
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500

    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT user_id, reset_token_expiry
            FROM users
            WHERE reset_token = %s AND is_active = 1
        """, (token_hash,))
        user = cursor.fetchone()

        if not user:
            return jsonify({'error': 'Invalid or expired reset token'}), 400

        if datetime.utcnow() > user['reset_token_expiry']:
            return jsonify({'error': 'Reset token has expired. Please request a new one.'}), 400

        new_hash = bcrypt.hashpw(
            new_password.encode('utf-8'),
            bcrypt.gensalt(rounds=12)
        ).decode('utf-8')

        cursor.execute("""
            UPDATE users
            SET password_hash = %s, reset_token = NULL,
                reset_token_expiry = NULL, failed_attempts = 0
            WHERE user_id = %s
        """, (new_hash, user['user_id']))
        conn.commit()

        return jsonify({'message': 'Password reset successfully. You can now login.'}), 200

    except Error:
        return jsonify({'error': 'Password reset failed'}), 500
    finally:
        cursor.close()
        conn.close()


# ── API: Get Current User ─────────────────────────────────────────

@auth_bp.route('/api/auth/me', methods=['GET'])
def get_current_user():
    """Returns current logged-in user info from token."""
    from middleware.auth_middleware import get_token_from_request
    token = get_token_from_request()
    if not token:
        return jsonify({'error': 'Not authenticated'}), 401
    try:
        import jwt as pyjwt
        payload = pyjwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
    except Exception:
        return jsonify({'error': 'Invalid token'}), 401

    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database error'}), 500
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT user_id, name, email, role FROM users WHERE user_id = %s AND is_active = 1",
            (payload['user_id'],)
        )
        user = cursor.fetchone()
    finally:
        cursor.close()
        conn.close()

    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(user), 200