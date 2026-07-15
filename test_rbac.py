# test_rbac.py — comprehensive permission tests for Phase B
# Run with: python test_rbac.py
import json, sys, random, string, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from config import DB_CONFIG
import mysql.connector

def unique_tag():
    return ''.join(random.choices(string.ascii_lowercase, k=6))

# ── Helper: login & get cookies ──────────────────────────────────
def login(client, email, password):
    resp = client.post('/api/auth/login', json={'email': email, 'password': password})
    return resp

def get_cookies(resp):
    cookies = {}
    for h in resp.headers.getlist('Set-Cookie'):
        parts = h.split(';')[0]
        if '=' in parts:
            k, v = parts.split('=', 1)
            cookies[k] = v
    return cookies

def get_valid_product_id(client, cookies, min_stock=0):
    """Fetch a product that actually exists in the DB."""
    import mysql.connector
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    if min_stock > 0:
        cursor.execute("SELECT product_id FROM products WHERE stock_quantity >= %s LIMIT 1", (min_stock,))
    else:
        cursor.execute("SELECT product_id FROM products LIMIT 1")
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        return row[0]
    return None

def authed_request(client, method, path, cookies, json_data=None):
    headers = {'Content-Type': 'application/json'} if json_data else {}
    token = cookies.get('access_token', '')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if json_data:
        return client.open(path, method=method, headers=headers,
                          data=json.dumps(json_data),
                          content_type='application/json')
    else:
        return client.open(path, method=method, headers=headers)

# ── Login credentials ───────────────────────────────────────────
MANAGER = {'email': 'manager@test.com', 'password': 'Manager@123'}
STAFF   = {'email': 'staff@test.com',   'password': 'Staff@123'}
ADMIN   = {'email': 'admin@test.com',   'password': 'Admin@123'}

passed = 0
failed = 0

def check(label, ok, detail=''):
    global passed, failed
    if ok:
        print(f'  [PASS] {label}')
        passed += 1
    else:
        print(f'  [FAIL] {label}  -- {detail}')
        failed += 1

# ── Main Test Runner ─────────────────────────────────────────────
with app.test_client() as client:
    print('=' * 60)
    print('PHASE B — RBAC PERMISSION TESTS')
    print('=' * 60)

    # 1. Login as Manager
    print('\n--- Login as Manager ---')
    m_resp = login(client, **MANAGER)
    check('Manager login OK', m_resp.status_code == 200)
    m_cookies = get_cookies(m_resp)

    pid = get_valid_product_id(client, m_cookies, min_stock=1)
    check('Found a valid product_id for testing', pid is not None)

    # 2. Manager: Products ────────────────────────────────────────
    print('\n--- Manager: Products ---')
    r = authed_request(client, 'GET', '/api/products', m_cookies)
    check('GET /api/products = 200', r.status_code == 200)

    r = authed_request(client, 'GET', f'/api/products/{pid}', m_cookies)
    check('GET /api/products/{pid} = 200', r.status_code == 200)

    tag = unique_tag()
    r = authed_request(client, 'POST', '/api/products', m_cookies,
                       json_data={'name': f'Test Product {tag}', 'price': 99.99,
                                  'stock_quantity': 10, 'supplier_id': 1})
    check('POST /api/products = 201', r.status_code == 201)
    if r.status_code == 201:
        new_pid = r.get_json().get('product_id')

    r = authed_request(client, 'PUT', f'/api/products/{new_pid}', m_cookies,
                       json_data={'price': 89.99})
    check('PUT /api/products = 200', r.status_code == 200)

    r = authed_request(client, 'DELETE', f'/api/products/{new_pid}', m_cookies)
    check('DELETE /api/products = 403 (manager cannot delete)', r.status_code == 403)

    # 3. Manager: Suppliers ───────────────────────────────────────
    print('\n--- Manager: Suppliers ---')
    r = authed_request(client, 'GET', '/api/suppliers', m_cookies)
    check('GET /api/suppliers = 200', r.status_code == 200)

    tag = unique_tag()
    r = authed_request(client, 'POST', '/api/suppliers', m_cookies,
                       json_data={'name': 'Test Supplier M', 'email': f'suppmgr_{tag}@test.com'})
    sj = r.get_json() or {}
    check('POST /api/suppliers = 201', r.status_code == 201, str(sj))
    if r.status_code == 201:
        new_sid = sj.get('supplier_id')

    r = authed_request(client, 'PUT', f'/api/suppliers/{new_sid}', m_cookies,
                       json_data={'contact_person': 'New Person'})
    check('PUT /api/suppliers = 200', r.status_code == 200)

    r = authed_request(client, 'DELETE', f'/api/suppliers/{new_sid}', m_cookies)
    check('DELETE /api/suppliers = 403 (manager cannot delete)', r.status_code == 403)

    # 4. Manager: Sales ───────────────────────────────────────────
    print('\n--- Manager: Sales ---')
    r = authed_request(client, 'GET', '/api/sales', m_cookies)
    check('GET /api/sales = 200', r.status_code == 200)

    r = authed_request(client, 'POST', '/api/sales', m_cookies,
                       json_data={'product_id': pid, 'quantity_sold': 1,
                                  'sale_price': 29.99, 'sale_date': '2026-06-28'})
    check('POST /api/sales = 201', r.status_code == 201)
    assert r.status_code == 201, f'Sale creation failed: {r.get_json()}'
    new_sale_id = r.get_json().get('sale_id')

    r = authed_request(client, 'PUT', f'/api/sales/{new_sale_id}', m_cookies,
                       json_data={'quantity_sold': 2})
    check('PUT /api/sales = 403 (manager cannot edit)', r.status_code == 403)

    r = authed_request(client, 'DELETE', f'/api/sales/{new_sale_id}', m_cookies)
    check('DELETE /api/sales = 403 (manager cannot delete)', r.status_code == 403)

    # 5. Manager: Bills / Reports ─────────────────────────────────
    print('\n--- Manager: Bills & Reports ---')
    r = authed_request(client, 'GET', '/api/bills', m_cookies)
    check('GET /api/bills = 200', r.status_code == 200)

    r = authed_request(client, 'GET', '/api/sales/summary', m_cookies)
    check('GET /api/sales/summary = 200 (reports)', r.status_code == 200)

    r = authed_request(client, 'GET', '/api/sales/daily-summary', m_cookies)
    check('GET /api/sales/daily-summary = 200 (reports)', r.status_code == 200)

    r = authed_request(client, 'GET', '/api/bills/next-number', m_cookies)
    check('GET /api/bills/next-number = 200', r.status_code == 200)

    r = authed_request(client, 'GET', '/api/pending-payments', m_cookies)
    check('GET /api/pending-payments = 200', r.status_code == 200)

    # 6. Staff Tests ──────────────────────────────────────────────
    print('\n--- Login as Staff ---')
    s_resp = login(client, **STAFF)
    check('Staff login OK', s_resp.status_code == 200)
    s_cookies = get_cookies(s_resp)

    pid2 = get_valid_product_id(client, s_cookies, min_stock=1)
    check('Found a valid product_id for staff testing', pid2 is not None)

    print('\n--- Staff: Products (view only) ---')
    r = authed_request(client, 'GET', '/api/products', s_cookies)
    check('GET /api/products = 200', r.status_code == 200)

    r = authed_request(client, 'GET', f'/api/products/{pid2}', s_cookies)
    check(f'GET /api/products/{pid2} = 200', r.status_code == 200)

    r = authed_request(client, 'POST', '/api/products', s_cookies,
                       json_data={'name': 'Staff Prod', 'price': 9.99})
    check('POST /api/products = 403 (staff cannot add)', r.status_code == 403)

    r = authed_request(client, 'PUT', '/api/products/2', s_cookies,
                       json_data={'price': 19.99})
    check('PUT /api/products = 403 (staff cannot edit)', r.status_code == 403)

    r = authed_request(client, 'DELETE', '/api/products/2', s_cookies)
    check('DELETE /api/products = 403 (staff cannot delete)', r.status_code == 403)

    print('\n--- Staff: Sales (create + view only) ---')
    r = authed_request(client, 'GET', '/api/sales', s_cookies)
    check('GET /api/sales = 200', r.status_code == 200)

    r = authed_request(client, 'POST', '/api/sales', s_cookies,
                       json_data={'product_id': pid2, 'quantity_sold': 1,
                                  'sale_price': 449.99, 'sale_date': '2026-06-28'})
    check('POST /api/sales = 201', r.status_code == 201)

    r = authed_request(client, 'GET', '/api/sales/summary', s_cookies)
    check('GET /api/sales/summary = 403 (staff no reports)', r.status_code == 403)

    r = authed_request(client, 'GET', '/api/sales/daily-summary', s_cookies)
    check('GET /api/sales/daily-summary = 403 (staff no reports)', r.status_code == 403)

    print('\n--- Staff: Suppliers (no access) ---')
    r = authed_request(client, 'GET', '/api/suppliers', s_cookies)
    check('GET /api/suppliers = 403 (staff no access)', r.status_code == 403)

    print('\n--- Staff: Bills (can view/create for POS) ---')
    r = authed_request(client, 'GET', '/api/bills', s_cookies)
    check('GET /api/bills = 200', r.status_code == 200)

    r = authed_request(client, 'GET', '/api/bills/next-number', s_cookies)
    check('GET /api/bills/next-number = 200', r.status_code == 200)

    r = authed_request(client, 'GET', '/api/pending-payments', s_cookies)
    check('GET /api/pending-payments = 403 (staff no access)', r.status_code == 403)

    r = authed_request(client, 'GET', '/api/bills/1/refunds', s_cookies)
    check('GET /api/bills/1/refunds = 403 (staff no refunds)', r.status_code == 403)

    r = authed_request(client, 'PUT', '/api/pending-payments/1', s_cookies,
                       json_data={'amount_paid': 100})
    check('PUT /api/pending-payments = 403 (staff cannot process payments)', r.status_code == 403)

    print('\n--- Staff: Admin-only financial ops ---')
    r = authed_request(client, 'POST', '/api/bills/1/refund', s_cookies,
                       json_data={'product_id': 2, 'quantity_returned': 1,
                                  'refund_amount': 29.99, 'refund_date': '2026-06-28'})
    check('POST refund = 403 (staff cannot refund)', r.status_code == 403)

    r = authed_request(client, 'PUT', '/api/bills/1', s_cookies,
                       json_data={'customer_name': 'Hack'})
    check('PUT /api/bills = 403 (staff cannot edit bills)', r.status_code == 403)

    r = authed_request(client, 'DELETE', '/api/bills/1', s_cookies)
    check('DELETE /api/bills = 403 (staff cannot delete bills)', r.status_code == 403)

    # 7. Admin basic sanity ───────────────────────────────────────
    print('\n--- Login as Admin ---')
    a_resp = login(client, **ADMIN)
    check('Admin login OK', a_resp.status_code == 200)
    a_cookies = get_cookies(a_resp)

    pid3 = get_valid_product_id(client, a_cookies, min_stock=1)
    check('Found a valid product_id for admin testing', pid3 is not None)

    print('\n--- Admin: full access sanity check ---')
    r = authed_request(client, 'POST', '/api/sales', a_cookies,
                       json_data={'product_id': pid3, 'quantity_sold': 1,
                                  'sale_price': 449.99, 'sale_date': '2026-06-28'})
    sj = r.get_json() or {}
    check('Admin POST /api/sales = 201', r.status_code == 201, str(sj))
    if r.status_code == 201:
        admin_sale_id = sj.get('sale_id')
        r = authed_request(client, 'PUT', f'/api/sales/{admin_sale_id}', a_cookies,
                           json_data={'notes': 'Admin edited'})
        sj2 = r.get_json() or {}
        check('Admin PUT /api/sales = 200', r.status_code == 200, str(sj2))

        r = authed_request(client, 'DELETE', f'/api/sales/{admin_sale_id}', a_cookies)
        sj3 = r.get_json() or {}
        check('Admin DELETE /api/sales = 200', r.status_code == 200, str(sj3))

    # Summary
    print('\n' + '=' * 60)
    total = passed + failed
    print(f'RESULTS: {passed}/{total} passed, {failed}/{total} failed')
    if failed:
        print('Some tests FAILED -- review [FAIL] lines above')
    else:
        print('ALL TESTS PASSED')
    print('=' * 60)
