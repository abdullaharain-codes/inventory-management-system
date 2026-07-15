from db.connection import get_db_connection
from mysql.connector import Error


def log_activity(user_id, user_role, module, action_type, description):
    """
    Insert a row into activity_logs.

    Fails silently — logs to console but never raises,
    so a logging failure never interrupts the calling route.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            print("[activity_logger] Database connection failed")
            return
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO activity_logs (user_id, user_role, module, action_type, description)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, user_role, module, action_type, description))
        conn.commit()
    except Error as e:
        print(f"[activity_logger] Failed to log activity: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
