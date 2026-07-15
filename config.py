import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────
DB_CONFIG = {
    'host':              os.getenv('DB_HOST', 'localhost'),
    'user':              os.getenv('DB_USER', 'root'),
    'password':          os.getenv('DB_PASSWORD', ''),
    'database':          os.getenv('DB_NAME', 'inventory_db'),
    'raise_on_warnings': True
}

# ── JWT ───────────────────────────────────────────────────────────
JWT_SECRET_KEY             = os.getenv('JWT_SECRET_KEY', 'fallback-secret-change-in-prod')
JWT_ACCESS_TOKEN_EXPIRES   = int(os.getenv('JWT_ACCESS_TOKEN_EXPIRES',  900))    # 15 min
JWT_REFRESH_TOKEN_EXPIRES  = int(os.getenv('JWT_REFRESH_TOKEN_EXPIRES', 604800)) # 7 days

# ── Flask ─────────────────────────────────────────────────────────
SECRET_KEY  = os.getenv('SECRET_KEY', 'flask-secret-change-in-prod')
FLASK_ENV   = os.getenv('FLASK_ENV', 'development')
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True') == 'True'

# ── Security ──────────────────────────────────────────────────────
MAX_LOGIN_ATTEMPTS = int(os.getenv('MAX_LOGIN_ATTEMPTS', 5))
LOCKOUT_MINUTES    = int(os.getenv('LOCKOUT_MINUTES', 15))