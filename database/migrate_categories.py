"""
Migration Script: Phase 2 — Category Management

1. Creates categories table (if not exists)
2. Normalizes existing free-text categories (trim, merge duplicates) and inserts rows
3. Adds category_id column to products (if not exists)
4. Backfills products.category_id by matching old text category to new normalized name
5. Does NOT drop old category column (kept as fallback)
6. Reports counts
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mysql.connector
import re
from config import DB_CONFIG

NORMALIZED = {
    'accessories':     'Accessories',
    'audio':           'Audio',
    'components':      'Components',
    'displays':        'Displays',
    'electronics':     'Electronics',
    'electronic':      'Electronics',
    'furniture':       'Furniture',
    'networking':      'Networking',
    'office supplies': 'Office Supplies',
    'peripherals':     'Peripherals',
    'sounds':          'Audio',
    'storage':         'Storage',
}

def run():
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    print("Connected.")

    # ── 1. Create categories table ──────────────────────────────
    print("\n--- Step 1: Create categories table ---")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            category_id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(100) NOT NULL UNIQUE,
            parent_category_id INT DEFAULT NULL,
            created_at TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT fk_category_parent
                FOREIGN KEY (parent_category_id) REFERENCES categories(category_id)
                ON DELETE SET NULL
        ) ENGINE=InnoDB
    """)
    conn.commit()
    print("  categories table ready.")

    # ── 2. Collect distinct old values and normalize ────────────
    print("\n--- Step 2: Normalize existing categories ---")
    cursor.execute("SELECT DISTINCT category FROM products WHERE category IS NOT NULL")
    raw = [row[0] for row in cursor.fetchall()]
    print(f"  Raw distinct categories ({len(raw)}): {raw}")

    normalized_flat = {}
    for val in raw:
        key = val.strip().lower()
        target = NORMALIZED.get(key, val.strip())
        normalized_flat[val] = target
        print(f"    '{val}' -> '{target}'")

    # ── 3. Insert normalized categories ─────────────────────────
    print("\n--- Step 3: Insert normalized categories ---")
    unique_targets = sorted(set(normalized_flat.values()))
    print(f"  Unique categories to insert: {unique_targets}")

    for name in unique_targets:
        try:
            cursor.execute(
                "INSERT INTO categories (name) VALUES (%s) ON DUPLICATE KEY UPDATE name = name",
                (name,)
            )
        except Exception as e:
            print(f"  Error inserting '{name}': {e}")

    conn.commit()

    # Show what we got
    cursor.execute("SELECT category_id, name FROM categories ORDER BY category_id")
    inserted = cursor.fetchall()
    print(f"  Categories in table: {inserted}")

    # ── 4. Add category_id to products ──────────────────────────
    print("\n--- Step 4: Add category_id column to products ---")
    try:
        cursor.execute("""
            ALTER TABLE products
            ADD COLUMN category_id INT DEFAULT NULL AFTER category,
            ADD CONSTRAINT fk_product_category
                FOREIGN KEY (category_id) REFERENCES categories(category_id)
                ON DELETE SET NULL
        """)
        conn.commit()
        print("  category_id column added (nullable).")
    except Exception as e:
        if "Duplicate column" in str(e):
            print("  category_id column already exists. Skipping.")
        else:
            raise

    # ── 5. Backfill ─────────────────────────────────────────────
    print("\n--- Step 5: Backfill products.category_id ---")
    # Build a lookup: normalized name -> id
    cursor.execute("SELECT category_id, name FROM categories")
    name_to_id = {row[1].strip().lower(): row[0] for row in cursor.fetchall()}

    for old_val, target in normalized_flat.items():
        cat_id = name_to_id.get(target.strip().lower())
        if not cat_id:
            print(f"  WARNING: No category_id found for target '{target}'")
            continue

        # Match old text value case-insensitively, trimmed
        cursor.execute("""
            UPDATE products
            SET category_id = %s
            WHERE TRIM(category) = %s AND category_id IS NULL
        """, (cat_id, old_val.strip()))
        affected = cursor.rowcount
        if affected > 0:
            print(f"    '{old_val}' -> '{target}' (id={cat_id}): {affected} products updated")
        else:
            # Try case-insensitive match
            cursor.execute("""
                UPDATE products
                SET category_id = %s
                WHERE LOWER(TRIM(category)) = LOWER(TRIM(%s)) AND category_id IS NULL
            """, (cat_id, old_val.strip()))
            affected2 = cursor.rowcount
            if affected2 > 0:
                print(f"    '{old_val}' -> '{target}' (id={cat_id}) [case-insensitive]: {affected2} products updated")

    conn.commit()

    # ── 6. Report ───────────────────────────────────────────────
    print("\n--- Step 6: Report ---")
    cursor.execute("SELECT COUNT(*) FROM categories")
    cat_count = cursor.fetchone()[0]
    print(f"  Total categories created: {cat_count}")

    cursor.execute("SELECT COUNT(*) FROM products WHERE category_id IS NOT NULL")
    backfilled = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM products WHERE category_id IS NULL")
    null_cat = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM products WHERE category IS NULL")
    null_text = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM products")
    total = cursor.fetchone()[0]

    print(f"  Total products: {total}")
    print(f"  Products with category_id (backfilled): {backfilled}")
    print(f"  Products with NULL category_id: {null_cat}")
    print(f"  Products with NULL text category: {null_text}")

    if null_cat > null_text:
        print("  NOTE: Some products had a text category but no matching normalized category — they remain NULL.")
    if null_text > 0:
        print(f"  NOTE: {null_text} products had NULL text category and remain unassigned.")

    # ── 7. Verify ───────────────────────────────────────────────
    print("\n--- Step 7: Verification Spot Checks ---")
    cursor.execute("""
        SELECT p.name, p.category, c.name AS cat_name
        FROM products p
        LEFT JOIN categories c ON p.category_id = c.category_id
        WHERE p.category_id IS NOT NULL
        LIMIT 10
    """)
    samples = cursor.fetchall()
    for s in samples:
        print(f"    '{s[0]}' - old: '{s[1]}' -> new: '{s[2]}'")

    # Check a few that should still be NULL
    cursor.execute("""
        SELECT p.name, p.category
        FROM products p
        WHERE p.category_id IS NULL
        LIMIT 5
    """)
    null_samples = cursor.fetchall()
    if null_samples:
        print(f"  NULL category_id samples:")
        for s in null_samples:
            print(f"    '{s[0]}' — old text: '{s[1]}'")

    cursor.close()
    conn.close()

    print("\nMigration complete.")

if __name__ == '__main__':
    run()
