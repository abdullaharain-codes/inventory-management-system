from flask import Flask, render_template, redirect, request, make_response
from flask_cors import CORS
from routes.products import products_bp
from routes.categories import categories_bp
from routes.suppliers import suppliers_bp
from routes.sales import sales_bp
from routes.billing import billing_bp
from routes.auth import auth_bp
from routes.users import users_bp
from routes.activity_logs import activity_logs_bp
from routes.inventory import inventory_bp
from routes.adjustments import adjustments_bp
from routes.purchases import purchases_bp
from routes.notifications import notifications_bp
from routes.reports import reports_bp
from middleware.auth_middleware import login_required, admin_required, roles_required
from config import SECRET_KEY, FLASK_DEBUG

app = Flask(__name__)
app.secret_key = SECRET_KEY
CORS(app, supports_credentials=True)
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5MB max upload

# ── Security Headers ──────────────────────────────────────────────
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options']    = 'nosniff'
    response.headers['X-Frame-Options']            = 'SAMEORIGIN'
    response.headers['X-XSS-Protection']           = '1; mode=block'
    response.headers['Referrer-Policy']            = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy']         = 'geolocation=(), microphone=()'
    # Prevent browser caching of HTML pages (no-store for bfcache)
    if response.content_type and 'text/html' in response.content_type:
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma']        = 'no-cache'
        response.headers['Expires']       = '0'
    return response

# ── Register Blueprints ───────────────────────────────────────────
app.register_blueprint(auth_bp)
app.register_blueprint(products_bp)
app.register_blueprint(categories_bp)
app.register_blueprint(suppliers_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(users_bp)
app.register_blueprint(inventory_bp)
app.register_blueprint(activity_logs_bp)
app.register_blueprint(adjustments_bp)
app.register_blueprint(purchases_bp)
app.register_blueprint(notifications_bp)
app.register_blueprint(reports_bp)

# ── Public Routes ─────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect('/dashboard')

# ── Protected Page Routes ─────────────────────────────────────────
@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/products')
@login_required
def products_page():
    return render_template('products.html')

@app.route('/categories')
@login_required
def categories_page():
    return render_template('categories.html')

@app.route('/suppliers')
@login_required
def suppliers_page():
    return render_template('suppliers.html')

@app.route('/sales')
@login_required
def sales_page():
    return render_template('sales.html')

@app.route('/billing')
@login_required
def billing_page():
    return render_template('billing.html')

@app.route('/bill-history')
@login_required
def bill_history_page():
    return render_template('bill_history.html')

@app.route('/pending-payments')
@login_required
def pending_payments_page():
    return render_template('pending_payments.html')

@app.route('/daily-summary')
@login_required
def daily_summary_page():
    return render_template('daily_summary.html')

@app.route('/reports')
@roles_required('admin', 'manager')
def reports_page():
    return render_template('reports.html')

@app.route('/inventory')
@login_required
def inventory_page():
    return render_template('inventory.html')

@app.route('/notifications')
@roles_required('admin', 'manager')
def notifications_page():
    return render_template('notifications.html')

# ── Admin-Only Routes ─────────────────────────────────────────────
@app.route('/admin/users')
@admin_required
def admin_users_page():
    return render_template('admin_users.html')

@app.route('/activity-logs')
@admin_required
def activity_logs_page():
    return render_template('activity_logs.html')

@app.route('/settings')
@admin_required
def settings_page():
    return render_template('settings.html')

@app.route('/adjustments')
@login_required
def adjustments_page():
    return render_template('adjustments.html')

@app.route('/purchases')
@login_required
def purchases_page():
    return render_template('purchases.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=FLASK_DEBUG, threaded=True)