import sqlite3
import os

db_path = os.path.join(os.getcwd(), 'instance', 'auralis.db')

def migrate():
    if not os.path.exists(db_path):
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        print("Checking for existing columns in 'schedules' table...")
        cursor.execute("PRAGMA table_info(schedules)")
        columns = [column[1] for column in cursor.fetchall()]

        if 'access_code' not in columns:
            print("Adding 'access_code' column to 'schedules' table...")
            cursor.execute("ALTER TABLE schedules ADD COLUMN access_code TEXT")
            print("Creating unique index for 'access_code'...")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_access_code ON schedules(access_code)")
        
        if 'join_link' not in columns:
            print("Adding 'join_link' column to 'schedules' table...")
            cursor.execute("ALTER TABLE schedules ADD COLUMN join_link TEXT")

        conn.commit()
        print("Migration successful: 'access_code' and 'join_link' added to 'schedules'.")
    except Exception as e:
        print(f"Migration error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    migrate()
