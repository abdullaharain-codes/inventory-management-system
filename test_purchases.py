# test_purchases.py — tests for purchase order receive workflow
# Run with: python test_purchases.py
import json, sys, random, string, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app
from config import DB_CONFIG
import mysql.connector

def unique_tag():
    return ''.join(random.choices(string.ascii_lowercase, k=6))

# ── Helpers (matching test_rbac.py pattern) ──────────────────────
def login(client, email, password):
    return client.post('/api/auth/login', json={'email': email, 'password': password})

def get_cookies(resp):
    cookies = {}
    for h in resp.headers.getlist('Set-Cookie'):
        parts = h.split(';')[0]
        if '=' in parts:
            k, v = parts.split('=', 1)
            cookies[k] = v
    return cookies

def authed_request(client, method, path, cookies, json_data=None):
    headers = {'Content-Type': 'application/json'} if json_data else {}
    token = cookies.get('access_token', '')
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if json_data:
        return client.open(path, method=method, headers=headers,
                          data=json.dumps(json_data),
                          content_type='application/json')
    return client.open(path, method=method, headers=headers)

def get_db():
    return mysql.connector.connect(**DB_CONFIG)

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

def find_supplier_and_product():
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT supplier_id FROM suppliers LIMIT 1")
    s = c.fetchone()
    c.execute("SELECT product_id, stock_quantity FROM products LIMIT 1")
    p = c.fetchone()
    c.close(); conn.close()
    return (s[0] if s else None), (p[0] if p else None), (p[1] if p else 0)

# ── Tests ────────────────────────────────────────────────────

with app.test_client() as client:
    print('=' * 60)
    print('PURCHASE ORDER RECEIVE TESTS')
    print('=' * 60)

    sid, pid, stock_before = find_supplier_and_product()
    if not sid or not pid:
        print('  [SKIP] No supplier/product in DB')
        sys.exit(0)

    # Login as Admin
    a_resp = login(client, **ADMIN)
    check('Admin login OK', a_resp.status_code == 200)
    a_cookies = get_cookies(a_resp)

    # ── Create approved PO with 1 line item ──────────────────
    tag = unique_tag()
    r = authed_request(client, 'POST', '/api/purchase-orders', a_cookies, json_data={
        'supplier_id': sid,
        'notes': f'Receive test {tag}',
        'items': [{'product_id': pid, 'quantity_ordered': 10, 'unit_cost': 50.00}]
    })
    sj = r.get_json() or {}
    check('Create PO = 201', r.status_code == 201, str(sj))
    if r.status_code != 201:
        sys.exit(1)
    po_id = sj['po_id']

    # Fetch PO detail to get item_id (create resp doesn't include items)
    r = authed_request(client, 'GET', f'/api/purchase-orders/{po_id}', a_cookies)
    sj = r.get_json() or {}
    check('Fetch PO detail = 200', r.status_code == 200, str(sj))
    item_id = sj['items'][0]['item_id']

    r = authed_request(client, 'PUT', f'/api/purchase-orders/{po_id}/submit', a_cookies)
    check('Submit PO = 200', r.status_code == 200)

    r = authed_request(client, 'PUT', f'/api/purchase-orders/{po_id}/approve', a_cookies)
    check('Approve PO = 200', r.status_code == 200)

    # ── (a) Staff gets 403 ──────────────────────────────────
    s_resp = login(client, **STAFF)
    s_cookies = get_cookies(s_resp)
    r = authed_request(client, 'PUT', f'/api/purchase-orders/{po_id}/receive', s_cookies,
                       json_data={'items': [{'item_id': item_id, 'quantity_received': 1}]})
    check('(a) Staff receive = 403', r.status_code == 403)

    # ── (b) Receive > ordered = 400 ─────────────────────────
    r = authed_request(client, 'PUT', f'/api/purchase-orders/{po_id}/receive', a_cookies,
                       json_data={'items': [{'item_id': item_id, 'quantity_received': 15}]})
    sj = r.get_json() or {}
    check('(b) Receive > ordered = 400', r.status_code == 400, str(sj))
    check('(b) Error msg mentions ordered/cannot',
          any(w in sj.get('error', '').lower() for w in ['ordered', 'cannot', 'over']), str(sj))

    # ── (c) Partial receive → partially_received ────────────
    r = authed_request(client, 'PUT', f'/api/purchase-orders/{po_id}/receive', a_cookies,
                       json_data={'items': [{'item_id': item_id, 'quantity_received': 4}]})
    sj = r.get_json() or {}
    check('(c) Partial receive = 200', r.status_code == 200, str(sj))
    check('(c) Status = partially_received', sj.get('status') == 'partially_received', str(sj))
    check('(c) Item qty_received = 4', sj.get('items', [{}])[0].get('quantity_received') == 4, str(sj))

    # ── (d) Receive remaining → received ────────────────────
    r = authed_request(client, 'PUT', f'/api/purchase-orders/{po_id}/receive', a_cookies,
                       json_data={'items': [{'item_id': item_id, 'quantity_received': 6}]})
    sj = r.get_json() or {}
    check('(d) Final receive = 200', r.status_code == 200, str(sj))
    check('(d) Status = received',         sj.get('status') == 'received', str(sj))
    check('(d) Item qty_received = 10',    sj.get('items', [{}])[0].get('quantity_received') == 10, str(sj))

    # ── (e) Draft & cancelled rejected ──────────────────────
    tag2 = unique_tag()
    r = authed_request(client, 'POST', '/api/purchase-orders', a_cookies, json_data={
        'supplier_id': sid,
        'notes': f'Draft PO {tag2}',
        'items': [{'product_id': pid, 'quantity_ordered': 5, 'unit_cost': 30.00}]
    })
    sj2 = r.get_json() or {}
    po2_id = sj2['po_id']

    # Fetch PO2 detail for item_id
    r = authed_request(client, 'GET', f'/api/purchase-orders/{po2_id}', a_cookies)
    sj2 = r.get_json() or {}
    check('Fetch PO2 detail = 200', r.status_code == 200, str(sj2))
    item2_id = sj2['items'][0]['item_id']

    r = authed_request(client, 'PUT', f'/api/purchase-orders/{po2_id}/receive', a_cookies,
                       json_data={'items': [{'item_id': item2_id, 'quantity_received': 1}]})
    sj2 = r.get_json() or {}
    check('(e) Receive on draft = 400', r.status_code == 400, str(sj2))

    r = authed_request(client, 'PUT', f'/api/purchase-orders/{po2_id}/submit', a_cookies)
    check('Submit PO2 = 200', r.status_code == 200)
    r = authed_request(client, 'PUT', f'/api/purchase-orders/{po2_id}/cancel', a_cookies)
    check('Cancel PO2 = 200', r.status_code == 200)

    r = authed_request(client, 'PUT', f'/api/purchase-orders/{po2_id}/receive', a_cookies,
                       json_data={'items': [{'item_id': item2_id, 'quantity_received': 1}]})
    sj2 = r.get_json() or {}
    check('(e) Receive on cancelled = 400', r.status_code == 400, str(sj2))

    # ── Summary ──────────────────────────────────────────────
    print('\n' + '=' * 60)
    total = passed + failed
    print(f'RESULTS: {passed}/{total} passed, {failed}/{total} failed')
    if failed:
        print('Some tests FAILED -- review [FAIL] lines above')
    else:
        print('ALL TESTS PASSED')
    print('=' * 60)
    sys.exit(1 if failed else 0)
