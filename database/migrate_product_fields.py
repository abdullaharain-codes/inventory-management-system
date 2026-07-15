"""
Migration: Phase 3 — Add SKU, barcode, unit_of_measure, tax_rate, image_path to products
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mysql.connector
from config import DB_CONFIG

def run():
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    print("Connected.")

    alterations = [
        ("sku",             "VARCHAR(50) DEFAULT NULL"),
        ("barcode",         "VARCHAR(50) DEFAULT NULL"),
        ("unit_of_measure", "VARCHAR(20) DEFAULT 'pcs'"),
        ("tax_rate",        "DECIMAL(5,2) DEFAULT 0.00"),
        ("image_path",      "VARCHAR(255) DEFAULT NULL"),
    ]

    for col_name, col_def in alterations:
        try:
            cursor.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_def} AFTER supplier_id")
            conn.commit()
            print(f"  Added column '{col_name}' ({col_def})")
        except mysql.connector.Error as e:
            if "Duplicate column" in str(e):
                print(f"  Column '{col_name}' already exists. Skipping.")
            else:
                raise

    # Add UNIQUE indexes for sku and barcode
    for col_name in ('sku', 'barcode'):
        try:
            cursor.execute(f"ALTER TABLE products ADD UNIQUE INDEX idx_products_{col_name} ({col_name})")
            conn.commit()
            print(f"  Added UNIQUE index on '{col_name}'")
        except mysql.connector.Error as e:
            if "Duplicate key name" in str(e) or "already exists" in str(e):
                print(f"  UNIQUE index on '{col_name}' already exists. Skipping.")
            else:
                raise

    cursor.close()
    conn.close()
    print("\nMigration complete.")

if __name__ == '__main__':
    run()
