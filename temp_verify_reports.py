import sys, json
sys.path.insert(0, '.')
import requests

BASE = 'http://127.0.0.1:5000'
ADMIN = ('admin@test.com', 'Admin@123')
STAFF = ('staff@test.com', 'Staff@123')

def login(email, password):
    s = requests.Session()
    r = s.post(f'{BASE}/api/auth/login', json={'email': email, 'password': password})
    return s, r.status_code

def p(label, obj):
    print(f"\n{'='*70}")
    print(f"  {label}")
    print('='*70)
    print(json.dumps(obj, indent=2, default=str))

# ============================================================
# 1. Login as admin
# ============================================================
print("\n### 1. LOGIN AS ADMIN ###")
admin_s, code = login(*ADMIN)
print(f"Admin login: HTTP {code}")

staff_s, code = login(*STAFF)
print(f"Staff login: HTTP {code}")

# ============================================================
# 2. Sales report — daily
# ============================================================
print("\n### 2A. GET /api/reports/sales (daily) ###")
r = admin_s.get(f'{BASE}/api/reports/sales', params={
    'date_from': '2026-07-10', 'date_to': '2026-07-13', 'granularity': 'daily'
})
print(f"Status: {r.status_code}")
data = r.json()
p("SALES REPORT — DAILY", data)

# ============================================================
# 2B. Sales report — monthly
# ============================================================
print("\n### 2B. GET /api/reports/sales (monthly) ###")
r = admin_s.get(f'{BASE}/api/reports/sales', params={
    'date_from': '2026-07-01', 'date_to': '2026-07-31', 'granularity': 'monthly'
})
print(f"Status: {r.status_code}")
data_monthly = r.json()
p("SALES REPORT — MONTHLY", data_monthly)

# ============================================================
# 2C. Stock report
# ============================================================
print("\n### 2C. GET /api/reports/stock ###")
r = admin_s.get(f'{BASE}/api/reports/stock', params={
    'date_from': '2026-07-10', 'date_to': '2026-07-13'
})
print(f"Status: {r.status_code}")
data_stock = r.json()
# Print summary + first 20 by_product
stock_summary = data_stock['period_summary']
p("STOCK PERIOD SUMMARY", stock_summary)
print(f"\nTotal by_product rows: {len(data_stock['by_product'])}")
print("First 20 by_product:")
for row in data_stock['by_product'][:20]:
    print(f"  #{row['product_id']} {row['product_name'][:30]:<30} open={row['opening_stock']} in={row['stock_in']} out={row['stock_out']} close={row['closing_stock']} reconciled={row['reconciled']}")
print(f"\nmovement_breakdown:")
for m in data_stock['movement_breakdown']:
    print(f"  {m['movement_type']}: {m['count']} movements, qty={m['total_quantity']}")

# ============================================================
# 2D. Profit report
# ============================================================
print("\n### 2D. GET /api/reports/profit ###")
r = admin_s.get(f'{BASE}/api/reports/profit', params={
    'date_from': '2026-07-10', 'date_to': '2026-07-13'
})
print(f"Status: {r.status_code}")
data_profit = r.json()
p("PROFIT PERIOD SUMMARY", data_profit['period_summary'])
print(f"\nby_product rows: {len(data_profit['by_product'])}")
print("First 10 products:")
for row in data_profit['by_product'][:10]:
    print(f"  #{row['product_id']} {row['product_name'][:30]:<30} qty={row['quantity_sold']} rev={row['revenue']} cost={row['cost']} profit={row['profit']} margin={row['margin_percent']}%")

# ============================================================
# 3. Sanity-check sales
# ============================================================
print("\n\n### 3. SALES SANITY CHECK ###")
from db.connection import get_db_connection
conn = get_db_connection()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT SUM(grand_total) as manual_revenue FROM bills WHERE bill_date BETWEEN '2026-07-10' AND '2026-07-13'")
manual = cur.fetchone()['manual_revenue']
api_revenue = data['period_summary']['total_revenue']
print(f"Manual SUM(grand_total): {manual}")
print(f"API total_revenue:       {api_revenue}")
print(f"MATCH: {float(manual) == float(api_revenue)}")

# Also check monthly
cur.execute("SELECT SUM(grand_total) as manual_revenue FROM bills WHERE bill_date BETWEEN '2026-07-01' AND '2026-07-31'")
manual_m = cur.fetchone()['manual_revenue']
api_m = data_monthly['period_summary']['total_revenue']
print(f"\nMonthly manual: {manual_m}")
print(f"Monthly API:    {api_m}")
print(f"MATCH: {float(manual_m) == float(api_m)}")

# ============================================================
# 4. Sanity-check stock: pick 3 products
# ============================================================
print("\n\n### 4. STOCK SANITY CHECK ###")
# Pick products that have stock movements
test_pids = [row['product_id'] for row in data_stock['by_product'] if int(row['stock_in']) > 0 or int(row['stock_out']) > 0][:3]
for pid in test_pids:
    api_row = next(r for r in data_stock['by_product'] if r['product_id'] == pid)

    # Manual opening: quantity_before of latest ledger row before date_from
    cur.execute("""
        SELECT quantity_before FROM stock_ledger
        WHERE product_id = %s AND DATE(created_at) < '2026-07-10'
        ORDER BY ledger_id DESC LIMIT 1
    """, (pid,))
    open_row = cur.fetchone()
    manual_open = open_row['quantity_before'] if open_row else 0

    # Manual closing: quantity_after of latest ledger row at/before date_to
    cur.execute("""
        SELECT quantity_after FROM stock_ledger
        WHERE product_id = %s AND DATE(created_at) <= '2026-07-13'
        ORDER BY ledger_id DESC LIMIT 1
    """, (pid,))
    close_row = cur.fetchone()
    manual_close = close_row['quantity_after'] if close_row else 0

    # Manual stock_in / stock_out
    cur.execute("""
        SELECT
            COALESCE(SUM(CASE WHEN quantity_change > 0 THEN quantity_change ELSE 0 END), 0) as si,
            COALESCE(SUM(CASE WHEN quantity_change < 0 THEN ABS(quantity_change) ELSE 0 END), 0) as so
        FROM stock_ledger
        WHERE product_id = %s AND DATE(created_at) BETWEEN '2026-07-10' AND '2026-07-13'
    """, (pid,))
    mov = cur.fetchone()

    print(f"\nProduct #{pid}:")
    print(f"  API:    open={api_row['opening_stock']} in={api_row['stock_in']} out={api_row['stock_out']} close={api_row['closing_stock']} reconciled={api_row['reconciled']}")
    print(f"  Manual: open={manual_open} in={mov['si']} out={mov['so']} close={manual_close} reconciled={manual_open + mov['si'] - mov['so'] == manual_close}")

# Count all reconciled=false
unreconciled = [r for r in data_stock['by_product'] if not r['reconciled']]
print(f"\nTotal products in by_product: {len(data_stock['by_product'])}")
print(f"Products with reconciled=false: {len(unreconciled)}")
for u in unreconciled:
    expected = u['opening_stock'] + u['stock_in'] - u['stock_out']
    print(f"  #{u['product_id']} {u['product_name']}: open={u['opening_stock']} + in={u['stock_in']} - out={u['stock_out']} = {expected}, but close={u['closing_stock']}")

cur.close()
conn.close()

# ============================================================
# 5. Sanity-check profit
# ============================================================
print("\n\n### 5. PROFIT SANITY CHECK ###")
ps = data_profit['period_summary']
print(f"products_excluded_no_cost_price: {ps['products_excluded_no_cost_price']}")
print(f"total_revenue: {ps['total_revenue']}")
print(f"total_cost: {ps['total_cost']}")
print(f"total_profit: {ps['total_profit']}")
print(f"avg_margin_percent: {ps['avg_margin_percent']}%")

# Spot-check first product
if data_profit['by_product']:
    p0 = data_profit['by_product'][0]
    print(f"\nSpot-check product #{p0['product_id']} ({p0['product_name']}):")
    print(f"  API: qty_sold={p0['quantity_sold']} revenue={p0['revenue']} cost={p0['cost']} profit={p0['profit']}")

    conn2 = get_db_connection()
    cur2 = conn2.cursor(dictionary=True)
    cur2.execute("""
        SELECT p.cost_price, SUM(bi.quantity) as qty, SUM(bi.item_total) as rev,
               SUM(bi.quantity * p.cost_price) as calc_cost,
               SUM(bi.item_total - bi.quantity * p.cost_price) as calc_profit
        FROM bill_items bi
        JOIN bills b ON b.bill_id = bi.bill_id
        JOIN products p ON p.product_id = bi.product_id
        WHERE bi.product_id = %s AND b.bill_date BETWEEN '2026-07-10' AND '2026-07-13'
        GROUP BY p.cost_price
    """, (p0['product_id'],))
    manual_p = cur2.fetchone()
    if manual_p:
        print(f"  Manual: cost_price={manual_p['cost_price']} qty={manual_p['qty']} rev={manual_p['rev']} cost={manual_p['calc_cost']} profit={manual_p['calc_profit']}")
        print(f"  MATCH: revenue={float(manual_p['rev'])==float(p0['revenue'])} cost={float(manual_p['calc_cost'])==float(p0['cost'])}")
    cur2.close()
    conn2.close()

# ============================================================
# 6. CSV endpoints
# ============================================================
print("\n\n### 6. CSV ENDPOINTS ###")
csv_tests = [
    ('Sales CSV', '/api/reports/sales/csv', {'date_from': '2026-07-10', 'date_to': '2026-07-13', 'granularity': 'daily'}),
    ('Stock CSV', '/api/reports/stock/csv', {'date_from': '2026-07-10', 'date_to': '2026-07-13'}),
    ('Profit CSV', '/api/reports/profit/csv', {'date_from': '2026-07-10', 'date_to': '2026-07-13'}),
]
for label, path, params in csv_tests:
    r = admin_s.get(f'{BASE}{path}', params=params)
    print(f"\n--- {label} (HTTP {r.status_code}) ---")
    lines = r.text.strip().split('\n')
    for line in lines[:5]:
        print(f"  {line}")
    if len(lines) > 5:
        print(f"  ... ({len(lines)} total lines)")
    # Check content-type
    ct = r.headers.get('Content-Type', '')
    disp = r.headers.get('Content-Disposition', '')
    print(f"  Content-Type: {ct}")
    print(f"  Content-Disposition: {disp}")

# ============================================================
# 7. Validation tests
# ============================================================
print("\n\n### 7. VALIDATION TESTS ###")
# date_from > date_to
r = admin_s.get(f'{BASE}/api/reports/sales', params={'date_from': '2026-07-13', 'date_to': '2026-07-10'})
print(f"date_from > date_to: HTTP {r.status_code} -> {r.json()}")

# invalid granularity
r = admin_s.get(f'{BASE}/api/reports/sales', params={'date_from': '2026-07-10', 'date_to': '2026-07-13', 'granularity': 'hourly'})
print(f"Invalid granularity: HTTP {r.status_code} -> {r.json()}")

# missing dates
r = admin_s.get(f'{BASE}/api/reports/sales', params={'date_from': '2026-07-10'})
print(f"Missing date_to: HTTP {r.status_code} -> {r.json()}")

# ============================================================
# 8. Staff role restriction
# ============================================================
print("\n\n### 8. STAFF ROLE RESTRICTION ###")
for path in ['/api/reports/sales', '/api/reports/stock', '/api/reports/profit']:
    r = staff_s.get(f'{BASE}{path}', params={'date_from': '2026-07-10', 'date_to': '2026-07-13'})
    print(f"Staff -> {path}: HTTP {r.status_code}")

# Also test CSV endpoints as staff
for path in ['/api/reports/sales/csv', '/api/reports/stock/csv', '/api/reports/profit/csv']:
    r = staff_s.get(f'{BASE}{path}', params={'date_from': '2026-07-10', 'date_to': '2026-07-13'})
    print(f"Staff -> {path}: HTTP {r.status_code}")

# ============================================================
# Done
# ============================================================
print("\n\n### VERIFICATION COMPLETE ###")
