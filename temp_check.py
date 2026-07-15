import sys
sys.path.insert(0, '.')
from db.connection import get_db_connection

conn = get_db_connection()
cur = conn.cursor(dictionary=True)

# Bills data range and summary
cur.execute("""
    SELECT MIN(bill_date) as min_date, MAX(bill_date) as max_date,
           COUNT(*) as bill_count,
           SUM(grand_total) as total_revenue,
           SUM(subtotal) as total_subtotal,
           SUM(discount_amount) as total_discount,
           SUM(gst_amount) as total_gst
    FROM bills
""")
print("=== BILLS SUMMARY ===")
for k, v in cur.fetchone().items():
    print(f"  {k}: {v}")

# Bill items summary
cur.execute("""
    SELECT COUNT(*) as item_count, COUNT(DISTINCT product_id) as unique_products,
           SUM(quantity) as total_qty, SUM(item_total) as total_item_revenue
    FROM bill_items
""")
print("\n=== BILL ITEMS SUMMARY ===")
for k, v in cur.fetchone().items():
    print(f"  {k}: {v}")

# Payment methods
cur.execute("""
    SELECT payment_method, COUNT(*) as cnt, SUM(grand_total) as revenue
    FROM bills GROUP BY payment_method
""")
print("\n=== PAYMENT METHODS ===")
for r in cur.fetchall():
    print(f"  {r['payment_method']}: {r['cnt']} bills, Rs.{r['revenue']}")

# Stock ledger summary
cur.execute("""
    SELECT MIN(created_at) as min_date, MAX(created_at) as max_date,
           COUNT(*) as total_movements,
           SUM(CASE WHEN quantity_change > 0 THEN quantity_change ELSE 0 END) as total_in,
           SUM(CASE WHEN quantity_change < 0 THEN ABS(quantity_change) ELSE 0 END) as total_out
    FROM stock_ledger
""")
print("\n=== STOCK LEDGER SUMMARY ===")
for k, v in cur.fetchone().items():
    print(f"  {k}: {v}")

# Stock ledger movement types
cur.execute("""
    SELECT movement_type, COUNT(*) as cnt, SUM(ABS(quantity_change)) as total_qty
    FROM stock_ledger GROUP BY movement_type
""")
print("\n=== MOVEMENT TYPES ===")
for r in cur.fetchall():
    print(f"  {r['movement_type']}: {r['cnt']} movements, qty={r['total_qty']}")

# Products with cost_price
cur.execute("""
    SELECT COUNT(*) as total,
           SUM(CASE WHEN cost_price IS NOT NULL THEN 1 ELSE 0 END) as has_cost,
           SUM(CASE WHEN cost_price IS NULL THEN 1 ELSE 0 END) as no_cost
    FROM products
""")
print("\n=== COST PRICE STATUS ===")
for k, v in cur.fetchone().items():
    print(f"  {k}: {v}")

# Sample bills to see dates
cur.execute("SELECT bill_id, bill_date, grand_total, payment_method FROM bills ORDER BY bill_date LIMIT 5")
print("\n=== SAMPLE BILLS (first 5) ===")
for r in cur.fetchall():
    print(f"  #{r['bill_id']} {r['bill_date']} Rs.{r['grand_total']} ({r['payment_method']})")

cur.execute("SELECT bill_id, bill_date, grand_total, payment_method FROM bills ORDER BY bill_date DESC LIMIT 5")
print("\n=== SAMPLE BILLS (last 5) ===")
for r in cur.fetchall():
    print(f"  #{r['bill_id']} {r['bill_date']} Rs.{r['grand_total']} ({r['payment_method']})")

# Sample stock_ledger
cur.execute("SELECT ledger_id, product_id, product_name, movement_type, quantity_change, quantity_before, quantity_after, created_at FROM stock_ledger ORDER BY created_at LIMIT 5")
print("\n=== SAMPLE STOCK LEDGER (first 5) ===")
for r in cur.fetchall():
    print(f"  #{r['ledger_id']} prod={r['product_id']} '{r['product_name']}' type={r['movement_type']} change={r['quantity_change']} before={r['quantity_before']} after={r['quantity_after']} at={r['created_at']}")

cur.close()
conn.close()
