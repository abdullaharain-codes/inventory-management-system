from db.connection import get_db_connection


def get_company_info():
    """Return company_info row (id=1) as a dict, with safe defaults
    if the table or row does not exist."""
    defaults = {
        'company_name': 'Inventory Management System',
        'address': '',
        'phone': '',
        'gst_number': None,
        'logo_path': None,
        'tagline': None,
        'invoice_format': 'a4',
    }
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        if not conn:
            return defaults
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM company_info WHERE id = 1")
        row = cursor.fetchone()
        if not row:
            return defaults
        return {
            'company_name':   row.get('company_name') or defaults['company_name'],
            'address':        row.get('address') or '',
            'phone':          row.get('phone') or '',
            'gst_number':     row.get('gst_number'),
            'logo_path':      row.get('logo_path'),
            'tagline':        row.get('tagline'),
            'invoice_format': row.get('invoice_format') or 'a4',
        }
    except Exception:
        return defaults
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
