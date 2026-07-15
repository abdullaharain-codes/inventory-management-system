"""
Seed Script: Categories (10), Suppliers (30), Products (1000+)
- Pakistani business data, PKR prices, low-stock & expiry items included
"""
import sys, os, random
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mysql.connector
from config import DB_CONFIG

# ── 10 Categories ───────────────────────────────────────────────────
CATEGORIES = [
    'Electronics', 'Accessories', 'Furniture', 'Networking',
    'Storage', 'Audio', 'Displays', 'Peripherals', 'Office Supplies', 'Components'
]

# ── 30 Pakistani Suppliers ──────────────────────────────────────────
PAKISTAN_SUPPLIERS = [
    {"name": "Al-Fatah Electronics",       "contact": "Khalid Mahmood",  "phone": "0300-111-0001", "email": "info@alfatah.com.pk",       "trn": "PK-TRN-1001", "terms": "Net 30",  "address": "Abdullah Haroon Road, Saddar, Karachi"},
    {"name": "Pak Tech Distributors",       "contact": "Ahmed Raza",     "phone": "0300-111-0002", "email": "orders@paktectech.com.pk",  "trn": "PK-TRN-1002", "terms": "Net 45",  "address": "Shahrah-e-Faisal, Karachi"},
    {"name": "Lahore Computer Store",       "contact": "Usman Ghani",    "phone": "0300-111-0003", "email": "sales@lcs.com.pk",          "trn": "PK-TRN-1003", "terms": "COD",    "address": "Hafeez Centre, The Mall, Lahore"},
    {"name": "Islamabad Business Solutions","contact": "Sadia Khan",     "phone": "0300-111-0004", "email": "info@ibsol.com.pk",         "trn": "PK-TRN-1004", "terms": "Net 30",  "address": "Blue Area, Islamabad"},
    {"name": "Sialkot Sports & Electronics","contact": "Imran Ali",      "phone": "0300-111-0005", "email": "imran@sialkotelec.com.pk",  "trn": "PK-TRN-1005", "terms": "Net 60",  "address": "Sialkot Road, Gujranwala"},
    {"name": "Karachi Wholesale Market",    "contact": "Rashid Mehmood", "phone": "0300-111-0006", "email": "rashid@kwholesale.com.pk",  "trn": "PK-TRN-1006", "terms": "Net 30",  "address": "Jodia Bazaar, Karachi"},
    {"name": "Faisalabad Industrial Supply","contact": "Tariq Javed",    "phone": "0300-111-0007", "email": "tariq@fis.com.pk",          "trn": "PK-TRN-1007", "terms": "Net 45",  "address": "Millat Road, Faisalabad"},
    {"name": "Rawalpindi Traders",          "contact": "Hassan Nawaz",   "phone": "0300-111-0008", "email": "hassan@rawalpinidi.com.pk", "trn": "PK-TRN-1008", "terms": "COD",    "address": "Raja Bazaar, Rawalpindi"},
    {"name": "Multan Electronics Hub",      "contact": "Zafar Iqbal",    "phone": "0300-111-0009", "email": "zafar@multanelec.com.pk",   "trn": "PK-TRN-1009", "terms": "Net 30",  "address": "Hussain Agahi, Multan"},
    {"name": "Peshawar Tech Bazaar",        "contact": "Junaid Khan",    "phone": "0300-111-0010", "email": "junaid@peshawartech.pk",    "trn": "PK-TRN-1010", "terms": "COD",    "address": "Khyber Bazaar, Peshawar"},
    {"name": "Quetta Computer Zone",        "contact": "Abdul Samad",    "phone": "0300-111-0011", "email": "samad@quettacomputer.pk",   "trn": "PK-TRN-1011", "terms": "Net 30",  "address": "Jinnah Road, Quetta"},
    {"name": "Hyderabad Electronics",       "contact": "Naveed Ahmed",   "phone": "0300-111-0012", "email": "naveed@hyderelec.com.pk",   "trn": "PK-TRN-1012", "terms": "Net 45",  "address": "Bhatti Chowk, Hyderabad"},
    {"name": "Gujranwala Electrical Store", "contact": "Shahid Iqbal",   "phone": "0300-111-0013", "email": "shahid@gujranwala.com.pk",  "trn": "PK-TRN-1013", "terms": "Net 30",  "address": "G.T. Road, Gujranwala"},
    {"name": "Sargodha Office Solutions",   "contact": "Asif Mahmood",   "phone": "0300-111-0014", "email": "asif@sargodhaoffice.pk",    "trn": "PK-TRN-1014", "terms": "Net 30",  "address": "University Road, Sargodha"},
    {"name": "Bahawalpur Trading Co.",      "contact": "Riaz Hussain",   "phone": "0300-111-0015", "email": "riaz@bahawalpurco.pk",      "trn": "PK-TRN-1015", "terms": "COD",    "address": "Circular Road, Bahawalpur"},
    {"name": "Abbottabad Tech Hub",         "contact": "Kamran Khan",    "phone": "0300-111-0016", "email": "kamran@abbottabadtech.pk",  "trn": "PK-TRN-1016", "terms": "Net 30",  "address": "Mall Road, Abbottabad"},
    {"name": "Sahiwal Electronics Mart",    "contact": "Fahad Younis",   "phone": "0300-111-0017", "email": "fahad@sahiwalmart.pk",      "trn": "PK-TRN-1017", "terms": "Net 45",  "address": "Railway Road, Sahiwal"},
    {"name": "Sukkur Digital Store",        "contact": "Waseem Akram",   "phone": "0300-111-0018", "email": "waseem@sukkurdigital.pk",   "trn": "PK-TRN-1018", "terms": "Net 30",  "address": "Station Road, Sukkur"},
    {"name": "Larkana Electronics",         "contact": "Ali Raza",       "phone": "0300-111-0019", "email": "ali@larkanatech.com.pk",    "trn": "PK-TRN-1019", "terms": "COD",    "address": "Bakers Road, Larkana"},
    {"name": "Rahim Yar Khan Traders",      "contact": "Sajid Hussain",  "phone": "0300-111-0020", "email": "sajid@rykhan.com.pk",       "trn": "PK-TRN-1020", "terms": "Net 30",  "address": "Jinnah Road, Rahim Yar Khan"},
    {"name": "Mardan Computer Mall",        "contact": "Hameed Ullah",   "phone": "0300-111-0021", "email": "hameed@mardanmall.com.pk",   "trn": "PK-TRN-1021", "terms": "Net 45",  "address": "Sopar Bazaar, Mardan"},
    {"name": "Kohat Electronics Centre",    "contact": "Danish Khan",    "phone": "0300-111-0022", "email": "danish@kohatcentre.com.pk",  "trn": "PK-TRN-1022", "terms": "COD",    "address": "Jail Road, Kohat"},
    {"name": "Mirpur Tech Store",           "contact": "Raja Farooq",    "phone": "0300-111-0023", "email": "raja@mirpurtech.com.pk",    "trn": "PK-TRN-1023", "terms": "Net 30",  "address": "Allama Iqbal Road, Mirpur"},
    {"name": "Gilgit Electronics",          "contact": "Jamshed Ali",    "phone": "0300-111-0024", "email": "jamshed@giligitelec.pk",    "trn": "PK-TRN-1024", "terms": "Net 30",  "address": "River View Road, Gilgit"},
    {"name": "Sawat Trading Company",       "contact": "Fazal Wahab",    "phone": "0300-111-0025", "email": "fazal@swattrading.com.pk",  "trn": "PK-TRN-1025", "terms": "COD",    "address": "Saidu Sharif Road, Swat"},
    {"name": "Dera Ghazi Khan Electronics",  "contact": "Aamir Sohail",  "phone": "0300-111-0026", "email": "aamir@dgkhan.com.pk",       "trn": "PK-TRN-1026", "terms": "Net 45",  "address": "Kutchery Road, D.G. Khan"},
    {"name": "Nawabshah Digital Hub",       "contact": "Zahid Mehmood",  "phone": "0300-111-0027", "email": "zahid@nawabshahdigital.pk", "trn": "PK-TRN-1027", "terms": "Net 30",  "address": "Qasimabad, Nawabshah"},
    {"name": "Chiniot Office Furnishings",  "contact": "Naeem Ahmed",    "phone": "0300-111-0028", "email": "naeem@chiniotoffice.pk",    "trn": "PK-TRN-1028", "terms": "Net 30",  "address": "Chak No. 5, Chiniot"},
    {"name": "Jhelum Electronics Hub",      "contact": "Mohsin Raza",    "phone": "0300-111-0029", "email": "mohsin@jhelumelec.com.pk",  "trn": "PK-TRN-1029", "terms": "COD",    "address": "G.T. Road, Jhelum"},
    {"name": "Kasur Tech Point",            "contact": "Irfan Ali",      "phone": "0300-111-0030", "email": "irfan@kasurtech.com.pk",    "trn": "PK-TRN-1030", "terms": "Net 30",  "address": "Main Bazaar, Kasur"},
]

# ── Product Generation Pools ────────────────────────────────────────
ADJECTIVES = ['Pro', 'Ultra', 'Smart', 'Slim', 'Compact', 'Premium', 'Advanced',
              'Elite', 'Max', 'Plus', 'Lite', 'Mini', 'Turbo', 'Flex', 'Edge']

VERSIONS = ['X1', 'X2', 'X3', 'V2', 'V3', 'Gen2', 'Gen3', 'SE', 'HD', '4K',
            'Pro+', 'Max+', '2.0', '3.0', 'i5', 'i7', 'i9', 'M1', 'M2', 'R7']

PRODUCT_BASES = {
    'Electronics':     ['Laptop', 'Tablet', 'Smartphone', 'Desktop PC', 'Workstation', 'Gaming Console'],
    'Accessories':     ['Mouse', 'Keyboard', 'Webcam', 'USB Hub', 'Cable', 'Adapter', 'Charger'],
    'Furniture':       ['Desk Chair', 'Standing Desk', 'Monitor Stand', 'Laptop Tray', 'Cable Organizer'],
    'Networking':      ['Router', 'Switch', 'Access Point', 'Ethernet Card', 'Modem', 'Repeater'],
    'Storage':         ['SSD', 'HDD', 'USB Drive', 'Memory Card', 'NAS Drive', 'External SSD'],
    'Audio':           ['Headphones', 'Speaker', 'Microphone', 'Earbuds', 'Sound Card', 'Amplifier'],
    'Displays':        ['Monitor', 'Projector', 'Display Panel', 'Smart Display', 'LED Screen'],
    'Peripherals':     ['Printer', 'Scanner', 'Drawing Tablet', 'Numpad', 'Trackpad', 'Joystick'],
    'Office Supplies': ['Notebook', 'Stapler', 'Pen Set', 'Binder', 'Desk Lamp', 'Whiteboard'],
    'Components':      ['CPU', 'GPU', 'RAM Module', 'Motherboard', 'Power Supply', 'Cooling Fan'],
}

DESCRIPTIONS = {
    'Electronics':     'High-performance device for professional use.',
    'Accessories':     'Durable accessory designed for daily productivity.',
    'Furniture':       'Comfortable and sturdy office furniture.',
    'Networking':      'Reliable networking hardware for stable connectivity.',
    'Storage':         'Fast and reliable storage solution.',
    'Audio':           'Crystal-clear audio device for immersive sound.',
    'Displays':        'Vivid display with high resolution.',
    'Peripherals':     'Precision peripheral for professional workflows.',
    'Office Supplies': 'Essential supply for organized workspaces.',
    'Components':      'High-quality internal component for system builds.',
}

# PKR price ranges per category
PRICE_RANGES = {
    'Electronics':     (15000,  350000),
    'Accessories':     (300,    25000),
    'Furniture':       (3000,   95000),
    'Networking':      (1500,   55000),
    'Storage':         (2000,   45000),
    'Audio':           (1000,   60000),
    'Displays':        (12000,  180000),
    'Peripherals':     (2000,   65000),
    'Office Supplies': (150,    12000),
    'Components':      (4000,   150000),
}

UNIT_MAP = {
    'Electronics':     'pcs',
    'Accessories':     'pcs',
    'Furniture':       'pcs',
    'Networking':      'pcs',
    'Storage':         'pcs',
    'Audio':           'pcs',
    'Displays':        'pcs',
    'Peripherals':     'pcs',
    'Office Supplies': 'pcs',
    'Components':      'pcs',
}


def generate_sku(cat_short, index):
    return f"{cat_short}-{str(index).zfill(5)}"


def generate_barcode():
    return ''.join(str(random.randint(0, 9)) for _ in range(13))


def seed():
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        print("=" * 60)
        print("SEEDING: Categories, Suppliers & Products")
        print("=" * 60)

        # ── 1. Clear existing non-user data ─────────────────────
        print("\n--- Step 1: Clear existing seed data ---")
        for table in ['purchase_order_items', 'purchase_orders', 'stock_adjustments',
                       'stock_ledger', 'refunds', 'pending_payments', 'bill_items',
                       'bills', 'sales', 'notifications', 'activity_logs', 'products',
                       'suppliers', 'categories']:
            cursor.execute(f"DELETE FROM {table}")
            cursor.execute(f"ALTER TABLE {table} AUTO_INCREMENT = 1")
        conn.commit()
        print("  All seed tables cleared, auto-increment reset.")

        # ── 2. Insert Categories ────────────────────────────────
        print("\n--- Step 2: Insert 10 Categories ---")
        cat_short_map = {}
        for name in CATEGORIES:
            cursor.execute(
                "INSERT INTO categories (name) VALUES (%s)", (name,)
            )
            cat_id = cursor.lastrowid
            short = name.replace(' ', '_')[:4].upper()
            cat_short_map[name] = (cat_id, short)
            print(f"  Inserted category '{name}' (ID={cat_id})")
        conn.commit()

        # ── 3. Insert 30 Suppliers ──────────────────────────────
        print("\n--- Step 3: Insert 30 Pakistani Suppliers ---")
        for s in PAKISTAN_SUPPLIERS:
            cursor.execute("""
                INSERT INTO suppliers (name, contact_person, phone, email, address,
                                       tax_registration_number, payment_terms, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (s['name'], s['contact'], s['phone'], s['email'], s['address'],
                  s['trn'], s['terms'], 'Pakistani supplier — seed data'))
        conn.commit()
        print(f"  Inserted {len(PAKISTAN_SUPPLIERS)} suppliers.")

        # ── 4. Generate & Insert 1000 Products ──────────────────
        print("\n--- Step 4: Generate 1000+ Products ---")

        today = datetime.now().date()
        used_names = set()
        products_batch = []
        total_target = 1050  # a bit over 1000 to ensure we hit the mark

        while len(products_batch) < total_target:
            cat_name = random.choice(CATEGORIES)
            cat_id, cat_short = cat_short_map[cat_name]
            base = random.choice(PRODUCT_BASES[cat_name])
            adj = random.choice(ADJECTIVES)
            ver = random.choice(VERSIONS)
            name = f"{adj} {base} {ver}"

            if name in used_names:
                continue
            used_names.add(name)

            low, high = PRICE_RANGES[cat_name]
            price = round(random.uniform(low, high), 2)
            supplier_id = random.randint(1, 30)
            desc = f"{adj} {DESCRIPTIONS[cat_name]}"
            sku = generate_sku(cat_short, len(products_batch) + 1)
            barcode = generate_barcode()
            uom = UNIT_MAP[cat_name]
            tax_rate = random.choice([0, 5, 10, 12, 17])

            # Stock: mostly normal, some low-stock, some zero
            threshold = random.choice([5, 10, 15, 20])
            if len(products_batch) < 50:
                stock = random.randint(0, threshold)        # low stock
            elif len(products_batch) < 80:
                stock = 0                                    # out of stock
            else:
                stock = random.randint(threshold + 5, 500)  # normal stock

            reorder_qty = threshold * random.choice([3, 4, 5])

            # Expiry: ~10% of products get 30-60 day expiry
            expiry_date = None
            if random.random() < 0.10:
                days_ahead = random.randint(30, 60)
                expiry_date = (today + timedelta(days=days_ahead)).isoformat()

            products_batch.append((
                name, desc, None, cat_id, sku, barcode, uom, tax_rate,
                None, price, stock, threshold, reorder_qty, expiry_date,
                supplier_id
            ))

        # Insert in batches of 100
        batch_size = 100
        total_inserted = 0
        insert_sql = """
            INSERT INTO products
                (name, description, category, category_id, sku, barcode,
                 unit_of_measure, tax_rate, image_path, price, stock_quantity,
                 minimum_stock_threshold, reorder_quantity, expiry_date, supplier_id)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """

        for i in range(0, len(products_batch), batch_size):
            batch = products_batch[i:i + batch_size]
            cursor.executemany(insert_sql, batch)
            conn.commit()
            total_inserted += len(batch)
            print(f"  Inserted {total_inserted}/{len(products_batch)}...")

        print(f"\n  Done! {total_inserted} products inserted.")

        # ── 5. Summary Report ───────────────────────────────────
        print("\n" + "=" * 60)
        print("SEED SUMMARY")
        print("=" * 60)

        cursor.execute("SELECT COUNT(*) FROM categories")
        print(f"  Categories: {cursor.fetchone()[0]}")

        cursor.execute("SELECT COUNT(*) FROM suppliers")
        print(f"  Suppliers:  {cursor.fetchone()[0]}")

        cursor.execute("SELECT COUNT(*) FROM products")
        total_p = cursor.fetchone()[0]
        print(f"  Products:   {total_p}")

        cursor.execute("SELECT COUNT(*) FROM products WHERE stock_quantity <= minimum_stock_threshold AND stock_quantity > 0")
        print(f"  Low Stock:  {cursor.fetchone()[0]}")

        cursor.execute("SELECT COUNT(*) FROM products WHERE stock_quantity = 0")
        print(f"  Out of Stock: {cursor.fetchone()[0]}")

        cursor.execute("SELECT COUNT(*) FROM products WHERE expiry_date IS NOT NULL")
        print(f"  With Expiry: {cursor.fetchone()[0]}")

        cursor.execute("""
            SELECT c.name, COUNT(p.product_id) as cnt
            FROM categories c LEFT JOIN products p ON c.category_id = p.category_id
            GROUP BY c.category_id ORDER BY cnt DESC
        """)
        print("\n  Breakdown by Category:")
        for row in cursor.fetchall():
            print(f"    {row[0]:<20} → {row[1]} products")

        cursor.execute("""
            SELECT s.name, COUNT(p.product_id) as cnt
            FROM suppliers s LEFT JOIN products p ON s.supplier_id = p.supplier_id
            GROUP BY s.supplier_id ORDER BY cnt DESC LIMIT 5
        """)
        print("\n  Top 5 Suppliers by Product Count:")
        for row in cursor.fetchall():
            print(f"    {row[0]:<35} → {row[1]} products")

        print("\nSeed complete!")

    except mysql.connector.Error as e:
        print(f"Database error: {e}")
        raise
    except Exception as e:
        print(f"Error: {e}")
        raise
    finally:
        if cursor: cursor.close()
        if conn: conn.close()


if __name__ == '__main__':
    seed()
