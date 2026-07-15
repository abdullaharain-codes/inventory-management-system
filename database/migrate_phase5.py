"""
Migration: Phase 5 — Stock Ledger table + new product columns
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mysql.connector
from config import DB_CONFIG

def run():
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    print("Connected.")

    # ── 1. Stock Ledger table ──────────────────────────────────────
    print("\n--- Step 1: Create stock_ledger table ---")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stock_ledger (
            ledger_id       INT PRIMARY KEY AUTO_INCREMENT,
            product_id      INT DEFAULT NULL,
            product_name    VARCHAR(100) NOT NULL,
            movement_type   ENUM('sale','bill_sale','refund','adjustment','purchase','opening_balance') NOT NULL,
            quantity_change INT NOT NULL,
            quantity_before INT NOT NULL,
            quantity_after  INT NOT NULL,
            reference_id    INT DEFAULT NULL,
            reference_type  VARCHAR(20) DEFAULT NULL,
            actor_user_id   INT DEFAULT NULL,
            actor_name      VARCHAR(100) DEFAULT NULL,
            notes           TEXT DEFAULT NULL,
            created_at      TIMESTAMP NULL DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_ledger_product_id (product_id),
            INDEX idx_ledger_movement_type (movement_type),
            INDEX idx_ledger_created_at (created_at),
            CONSTRAINT fk_ledger_product
                FOREIGN KEY (product_id) REFERENCES products(product_id)
                ON DELETE SET NULL,
            CONSTRAINT fk_ledger_user
                FOREIGN KEY (actor_user_id) REFERENCES users(user_id)
                ON DELETE SET NULL
        ) ENGINE=InnoDB
    """)
    conn.commit()
    print("  stock_ledger table ready.")

    # ── 2. New product columns ─────────────────────────────────────
    print("\n--- Step 2: Add minimum_stock_threshold and reorder_quantity ---")
    for col_name, col_def in [
        ("minimum_stock_threshold", "INT DEFAULT 10"),
        ("reorder_quantity", "INT DEFAULT 50"),
    ]:
        try:
            cursor.execute(f"ALTER TABLE products ADD COLUMN {col_name} {col_def}")
            conn.commit()
            print(f"  Added column '{col_name}' ({col_def})")
        except mysql.connector.Error as e:
            if "Duplicate column" in str(e):
                print(f"  Column '{col_name}' already exists. Skipping.")
            else:
                raise

    cursor.close()
    conn.close()
    print("\nMigration complete.")

if __name__ == '__main__':
    run()
