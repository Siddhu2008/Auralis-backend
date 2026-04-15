import sqlite3
import os

db_path = r'e:\A-Auralis\backend\instance\auralis.db'

def update_db():
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Update users table
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(20)")
        print("Added 'phone' to 'users'")
    except sqlite3.OperationalError:
        print("'phone' already exists in 'users'")

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN bio TEXT")
        print("Added 'bio' to 'users'")
    except sqlite3.OperationalError:
        print("'bio' already exists in 'users'")

    # Update user_settings table
    settings_cols = [
        ("two_factor_enabled", "BOOLEAN DEFAULT 0"),
        ("auto_send_emails", "BOOLEAN DEFAULT 0"),
        ("auto_schedule_meetings", "BOOLEAN DEFAULT 0"),
        ("auto_create_tasks", "BOOLEAN DEFAULT 1")
    ]

    for col_name, col_type in settings_cols:
        try:
            cursor.execute(f"ALTER TABLE user_settings ADD COLUMN {col_name} {col_type}")
            print(f"Added '{col_name}' to 'user_settings'")
        except sqlite3.OperationalError:
            print(f"'{col_name}' already exists in 'user_settings'")

    conn.commit()
    conn.close()
    print("Database update complete.")

if __name__ == "__main__":
    update_db()
