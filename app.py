from flask import Flask, render_template, redirect
from flask_cors import CORS
from routes.products import products_bp
from routes.suppliers import suppliers_bp
from routes.sales import sales_bp
from routes.billing import billing_bp

app = Flask(__name__)
CORS(app)

app.register_blueprint(products_bp)
app.register_blueprint(suppliers_bp)
app.register_blueprint(sales_bp)
app.register_blueprint(billing_bp)

@app.route('/')
def index():
    return redirect('/dashboard')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/products')
def products_page():
    return render_template('products.html')

@app.route('/suppliers')
def suppliers_page():
    return render_template('suppliers.html')

@app.route('/sales')
def sales_page():
    return render_template('sales.html')

@app.route('/billing')
def billing_page():
    return render_template('billing.html')

@app.route('/bill-history')
def bill_history_page():
    return render_template('bill_history.html')

@app.route('/pending-payments')        # ← NEW
def pending_payments_page():
    return render_template('pending_payments.html')

@app.route('/daily-summary')           # ← NEW
def daily_summary_page():
    return render_template('daily_summary.html')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)