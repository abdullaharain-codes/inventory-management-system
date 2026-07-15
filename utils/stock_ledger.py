from db.connection import get_db_connection
from mysql.connector import Error


def log_stock_movement(product_id, product_name, movement_type, quantity_change,
                       quantity_before, reference_id=None, reference_type=None,
                       actor_user_id=None, actor_name=None, notes=None):
    quantity_after = quantity_before + quantity_change
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            print("[stock_ledger] Database connection failed")
            return
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO stock_ledger
                (product_id, product_name, movement_type, quantity_change,
                 quantity_before, quantity_after, reference_id, reference_type,
                 actor_user_id, actor_name, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (product_id, product_name, movement_type, quantity_change,
              quantity_before, quantity_after, reference_id, reference_type,
              actor_user_id, actor_name, notes))
        conn.commit()
    except Error as e:
        print(f"[stock_ledger] Failed to log movement: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
