import mysql.connector
import random

# ── DB Config ─────────────────────────────────────────────────────
DB_CONFIG = {
    'host':     'localhost',
    'user':     'root',
    'password': 'Add your password',          # Add your password if any
    'database': 'Add your DB Name'
}

# ── Seed Data Pools ───────────────────────────────────────────────
categories = [
    'Electronics', 'Accessories', 'Furniture', 'Networking',
    'Storage', 'Audio', 'Displays', 'Peripherals', 'Office Supplies', 'Components'
]

adjectives = [
    'Pro', 'Ultra', 'Smart', 'Slim', 'Compact', 'Premium', 'Advanced',
    'Elite', 'Max', 'Plus', 'Lite', 'Mini', 'Turbo', 'Flex', 'Edge'
]

product_bases = {
    'Electronics':     ['Laptop', 'Tablet', 'Smartphone', 'Desktop PC', 'Workstation', 'Gaming Console'],
    'Accessories':     ['Mouse', 'Keyboard', 'Webcam', 'USB Hub', 'Cable', 'Adapter', 'Charger'],
    'Furniture':       ['Desk Chair', 'Standing Desk', 'Monitor Stand', 'Laptop Tray', 'Cable Organizer'],
    'Networking':      ['Router', 'Switch', 'Access Point', 'Ethernet Card', 'Modem', 'Repeater'],
    'Storage':         ['SSD', 'HDD', 'USB Drive', 'Memory Card', 'NAS Drive', 'External SSD'],
    'Audio':           ['Headphones', 'Speaker', 'Microphone', 'Earbuds', 'Sound Card', 'Amplifier'],
    'Displays':        ['Monitor', 'Projector', 'Display Panel', 'Smart Display', 'LED Screen'],
    'Peripherals':     ['Printer', 'Scanner', 'Drawing Tablet', 'Numpad', 'Trackpad', 'Joystick'],
    'Office Supplies': ['Notebook', 'Stapler', 'Pen Set', 'Binder', 'Desk Lamp', 'Whiteboard'],
    'Components':      ['CPU', 'GPU', 'RAM Module', 'Motherboard', 'Power Supply', 'Cooling Fan']
}

descriptions = {
    'Electronics':     'High-performance device for professional and personal use.',
    'Accessories':     'Ergonomic accessory designed for daily productivity.',
    'Furniture':       'Durable office furniture built for comfort and functionality.',
    'Networking':      'Reliable networking hardware for fast and stable connections.',
    'Storage':         'High-speed storage solution for data management.',
    'Audio':           'Crystal-clear audio device for immersive sound experience.',
    'Displays':        'Vivid display with high resolution and wide color gamut.',
    'Peripherals':     'Precision peripheral device for professional workflows.',
    'Office Supplies': 'Essential office supply for organized workspaces.',
    'Components':      'High-quality internal component for system performance.'
}

version_suffixes = ['X1', 'X2', 'X3', 'V2', 'V3', 'Gen2', 'Gen3', 'SE', 'HD', '4K',
                    'Pro+', 'Max+', '2.0', '3.0', 'i5', 'i7', 'i9', 'M1', 'M2', 'R7']

price_ranges = {
    'Electronics':     (299.99,  2499.99),
    'Accessories':     (9.99,    149.99),
    'Furniture':       (49.99,   599.99),
    'Networking':      (29.99,   499.99),
    'Storage':         (19.99,   349.99),
    'Audio':           (19.99,   399.99),
    'Displays':        (149.99,  1299.99),
    'Peripherals':     (29.99,   499.99),
    'Office Supplies': (4.99,    79.99),
    'Components':      (49.99,   899.99)
}

def generate_products(count=1000):
    products = []
    used_names = set()

    while len(products) < count:
        category  = random.choice(categories)
        base      = random.choice(product_bases[category])
        adj       = random.choice(adjectives)
        suffix    = random.choice(version_suffixes)
        name      = f"{adj} {base} {suffix}"

        if name in used_names:
            continue
        used_names.add(name)

        low, high   = price_ranges[category]
        price       = round(random.uniform(low, high), 2)
        stock       = random.randint(0, 500)
        supplier_id = random.randint(1, 5)
        description = f"{adj} {descriptions[category]}"

        products.append((name, description, category, price, stock, supplier_id))

    return products

def seed():
    print("Connecting to database...")
    try:
        conn   = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print("Connected.")

        products = generate_products(1000)
        print(f"Generated {len(products)} products. Inserting...")

        query = """
            INSERT INTO products (name, description, category, price, stock_quantity, supplier_id)
            VALUES (%s, %s, %s, %s, %s, %s)
        """

        # Insert in batches of 100 for performance
        batch_size = 100
        total_inserted = 0

        for i in range(0, len(products), batch_size):
            batch = products[i:i + batch_size]
            cursor.executemany(query, batch)
            conn.commit()
            total_inserted += len(batch)
            print(f"  Inserted {total_inserted}/1000...")

        print(f"\nDone! {total_inserted} products inserted successfully.")

        # Show summary
        cursor.execute("SELECT COUNT(*) FROM products")
        total = cursor.fetchone()[0]
        print(f"Total products in database now: {total}")

        cursor.execute("""
            SELECT category, COUNT(*) as count, 
                   ROUND(AVG(price), 2) as avg_price,
                   MIN(price) as min_price,
                   MAX(price) as max_price
            FROM products 
            GROUP BY category 
            ORDER BY count DESC
        """)
        rows = cursor.fetchall()
        print("\nBreakdown by category:")
        print(f"{'Category':<20} {'Count':>6} {'Avg Price':>10} {'Min':>8} {'Max':>8}")
        print("-" * 56)
        for row in rows:
            print(f"{row[0]:<20} {row[1]:>6} ${row[2]:>9} ${row[3]:>7} ${row[4]:>7}")

        cursor.close()
        conn.close()

    except mysql.connector.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    seed()
