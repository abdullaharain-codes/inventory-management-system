from db.connection import get_db_connection
from mysql.connector import Error
from utils.notification_broadcaster import publish as broadcast


def create_notification(title, message, notification_type, target_role='all',
                       user_id=None, related_id=None, related_type=None):
    """
    Insert a row into notifications and publish to SSE subscribers.

    Fails silently — prints to console but never raises,
    so a notification failure never interrupts the calling route.
    """
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            print("[notifier] Database connection failed")
            return
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO notifications
                (user_id, target_role, title, message, notification_type,
                 related_id, related_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (user_id, target_role, title, message, notification_type,
              related_id, related_type))
        conn.commit()
        notif_id = cursor.lastrowid
        try:
            broadcast({
                'notification_id': notif_id,
                'user_id': user_id,
                'target_role': target_role,
                'title': title,
                'message': message,
                'notification_type': notification_type,
                'related_id': related_id,
                'related_type': related_type,
            })
        except Exception as be:
            print(f"[notifier] Broadcast failed (non-fatal): {be}")
    except Error as e:
        print(f"[notifier] Failed to create notification: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()


def check_and_notify_low_stock(product_id):
    """Query current stock for a product and create a low_stock or out_of_stock
    notification if thresholds are breached.  Opens its own connection so it
    can be called after the caller has committed."""
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT name, stock_quantity, minimum_stock_threshold "
            "FROM products WHERE product_id = %s",
            (product_id,)
        )
        prod = cursor.fetchone()
        if not prod:
            return
        stock    = prod['stock_quantity']
        threshold = prod['minimum_stock_threshold'] or 10
        name     = prod['name']

        if stock == 0:
            create_notification(
                title='Out of Stock',
                message=f"{name} is now out of stock.",
                notification_type='out_of_stock',
                target_role='all',
                related_id=product_id,
                related_type='product'
            )
        elif stock <= threshold:
            create_notification(
                title='Low Stock Alert',
                message=f"{name} has only {stock} units in stock (threshold: {threshold}).",
                notification_type='low_stock',
                target_role='all',
                related_id=product_id,
                related_type='product'
            )
    except Error as e:
        print(f"[notifier] Low stock check failed for product #{product_id}: {e}")
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
