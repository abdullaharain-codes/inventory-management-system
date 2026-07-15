import mysql.connector
import bcrypt
from config import DB_CONFIG

def seed_admin():
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        email = 'admin@test.com'
        password = 'Admin@123'
        password_hash = bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt(rounds=12)
        ).decode('utf-8')

        cursor.execute("SELECT user_id FROM users WHERE email = %s", (email,))
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "UPDATE users SET name = %s, password_hash = %s, role = %s, is_active = 1, failed_attempts = 0, locked_until = NULL WHERE email = %s",
                ('Admin User', password_hash, 'admin', email)
            )
            conn.commit()
            print(f"Updated user: {email} (role: admin)")
        else:
            cursor.execute("""
                INSERT INTO users (name, email, password_hash, role, is_active)
                VALUES (%s, %s, %s, %s, 1)
            """, ('Admin User', email, password_hash, 'admin'))
            conn.commit()
            print(f"Created user: {email} (role: admin)")

        cursor.execute("SELECT user_id, name, email, role FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        print(f"Verified: ID={user[0]}, Name={user[1]}, Email={user[2]}, Role={user[3]}")
        print("Seed complete. Login with: admin@test.com / Admin@123")

    except mysql.connector.Error as e:
        print(f"Database error: {e}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

if __name__ == '__main__':
    seed_admin()
