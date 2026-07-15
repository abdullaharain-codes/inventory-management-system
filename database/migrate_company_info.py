"""
Migration: Phase 10 — company_info table for PDF invoice branding.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mysql.connector
from config import DB_CONFIG


def run():
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    print("Connected.")

    # ── 1. Create company_info table ──────────────────────────────
    print("\n--- Step 1: Create company_info table ---")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS company_info (
            id           INT PRIMARY KEY DEFAULT 1,
            company_name VARCHAR(150) NOT NULL,
            address      VARCHAR(300) NOT NULL,
            phone        VARCHAR(30) NOT NULL,
            gst_number   VARCHAR(50) DEFAULT NULL,
            logo_path    VARCHAR(255) DEFAULT NULL,
            tagline      VARCHAR(150) DEFAULT NULL,
            updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            CONSTRAINT single_row CHECK (id = 1)
        ) ENGINE=InnoDB
    """)
    conn.commit()
    print("  company_info table ready.")

    # ── 2. Seed default company info ──────────────────────────────
    print("\n--- Step 2: Seed default company info ---")
    cursor.execute("""
        INSERT INTO company_info (id, company_name, address, phone, gst_number, logo_path, tagline)
        VALUES (1, 'NovaTech Solutions',
                'Shop #12, Tech Plaza, Main Shahrah-e-Faisal, Karachi, Pakistan',
                '+92 300 1234567', 'GST-07-1234567-8',
                'static/uploads/company/logo.png', NULL)
        AS new_row
        ON DUPLICATE KEY UPDATE
            company_name = new_row.company_name,
            address      = new_row.address,
            phone        = new_row.phone,
            gst_number   = new_row.gst_number,
            logo_path    = new_row.logo_path,
            tagline      = new_row.tagline
    """)
    conn.commit()
    print("  Default company info seeded.")

    cursor.close()
    conn.close()
    print("\nMigration complete.")


if __name__ == '__main__':
    run()
