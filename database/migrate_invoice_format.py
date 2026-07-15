"""
Migration: Add invoice_format column to company_info table.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mysql.connector
from config import DB_CONFIG


def run():
    conn = mysql.connector.connect(**DB_CONFIG)
    cursor = conn.cursor()
    print("Connected.")

    print("\n--- Add invoice_format column ---")
    try:
        cursor.execute("""
            ALTER TABLE company_info
            ADD COLUMN invoice_format ENUM('thermal_80mm', 'a4') NOT NULL DEFAULT 'a4'
        """)
        conn.commit()
        print("  Column invoice_format added.")
    except mysql.connector.Error as e:
        if 'Duplicate column' in str(e):
            print("  Column already exists, skipping.")
        else:
            raise

    cursor.close()
    conn.close()
    print("\nMigration complete.")


if __name__ == '__main__':
    run()
