import sqlite3
import logging
from config import DB_PATH, local_now_str

logger = logging.getLogger(__name__)

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Check if the database needs migration (old table has no chat_id column)
        try:
            cursor.execute("SELECT chat_id FROM exam_results LIMIT 1")
        except sqlite3.OperationalError as e:
            # Table doesn't exist or doesn't have chat_id column. Drop to recreate.
            logger.info("Upgrading database schema: dropping old tables...")
            cursor.execute("DROP TABLE IF EXISTS exam_results")
            cursor.execute("DROP TABLE IF EXISTS users")
        
        # 1. Users Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                surname TEXT,
                name TEXT,
                patronymic TEXT,
                passport TEXT,
                region TEXT,
                is_monitoring INTEGER DEFAULT 1,
                last_check_at TEXT,
                created_at TEXT
            )
        """)
        
        # 2. Exam Results Table (Composite key on chat_id and subject)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS exam_results (
                chat_id INTEGER,
                subject TEXT,
                exam_date TEXT,
                primary_score TEXT,
                test_score TEXT,
                status TEXT,
                appeal TEXT,
                updated_at TEXT,
                PRIMARY KEY (chat_id, subject)
            )
        """)
        conn.commit()
    logger.info("Database initialized successfully.")

# Initialize immediately on import
init_db()

# ==================== User Management ====================

def save_user(chat_id: int, surname: str, name: str, patronymic: str, passport: str, region: str = "Республика Башкортостан"):
    """
    Registers or updates a user in the database.
    """
    now_str = local_now_str("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (chat_id, surname, name, patronymic, passport, region, is_monitoring, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                surname = excluded.surname,
                name = excluded.name,
                patronymic = excluded.patronymic,
                passport = excluded.passport,
                region = excluded.region,
                is_monitoring = 1
        """, (chat_id, surname, name, patronymic, passport, region, now_str))
        conn.commit()
    logger.info(f"User {chat_id} registered/updated in database.")

def get_user(chat_id: int) -> dict or None:
    """
    Fetches details of a single user by chat_id.
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_all_users() -> list[dict]:
    """
    Fetches details of all registered users.
    """
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        return [dict(row) for row in cursor.fetchall()]

def update_user_monitoring(chat_id: int, is_monitoring: int):
    """
    Toggles the monitoring state for a specific user.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_monitoring = ? WHERE chat_id = ?", (is_monitoring, chat_id))
        conn.commit()
    logger.info(f"User {chat_id} is_monitoring updated to {is_monitoring}.")

def update_user_last_check(chat_id: int, timestamp: str):
    """
    Updates the last check timestamp for a user.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET last_check_at = ? WHERE chat_id = ?", (timestamp, chat_id))
        conn.commit()

def delete_user(chat_id: int):
    """
    Deletes user records and associated exam results.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE chat_id = ?", (chat_id,))
        cursor.execute("DELETE FROM exam_results WHERE chat_id = ?", (chat_id,))
        conn.commit()
    logger.info(f"User {chat_id} and all their results deleted from database.")

# ==================== Exam Results Management ====================

def save_results(chat_id: int, results: dict):
    """
    Saves a dictionary of results to the database for a specific user.
    Format of results:
    {
      "Subject": {
        "date": "...",
        "primary": int/str/None,
        "test": int/str/None,
        "status": "...",
        "appeal": "..."
      }
    }
    """
    now_str = local_now_str("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        for subject, data in results.items():
            primary_val = str(data["primary"]) if data["primary"] is not None else None
            test_val = str(data["test"]) if data["test"] is not None else None
            
            cursor.execute("""
                INSERT INTO exam_results (chat_id, subject, exam_date, primary_score, test_score, status, appeal, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id, subject) DO UPDATE SET
                    exam_date = excluded.exam_date,
                    primary_score = excluded.primary_score,
                    test_score = excluded.test_score,
                    status = excluded.status,
                    appeal = excluded.appeal,
                    updated_at = excluded.updated_at
            """, (
                chat_id,
                subject,
                data["date"],
                primary_val,
                test_val,
                data["status"],
                data["appeal"],
                now_str
            ))
        conn.commit()

def load_results(chat_id: int) -> dict:
    """
    Loads exam results for a specific user.
    """
    results = {}
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT subject, exam_date, primary_score, test_score, status, appeal FROM exam_results WHERE chat_id = ?", (chat_id,))
        rows = cursor.fetchall()
        for row in rows:
            subject, exam_date, primary_val, test_val, status, appeal = row
            
            def parse_val(v):
                if v is None:
                    return None
                if v.isdigit():
                    return int(v)
                return v

            results[subject] = {
                "date": exam_date,
                "primary": parse_val(primary_val),
                "test": parse_val(test_val),
                "status": status,
                "appeal": appeal
            }
    return results

def update_subject(chat_id: int, subject: str, date: str, primary, test, status: str, appeal: str):
    """
    Updates single subject details for a specific user.
    """
    now_str = local_now_str("%Y-%m-%d %H:%M:%S")
    primary_val = str(primary) if primary is not None else None
    test_val = str(test) if test is not None else None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO exam_results (chat_id, subject, exam_date, primary_score, test_score, status, appeal, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, subject) DO UPDATE SET
                exam_date = excluded.exam_date,
                primary_score = excluded.primary_score,
                test_score = excluded.test_score,
                status = excluded.status,
                appeal = excluded.appeal,
                updated_at = excluded.updated_at
        """, (chat_id, subject, date, primary_val, test_val, status, appeal, now_str))
        conn.commit()

def get_all_results(chat_id: int) -> list[dict]:
    """
    Returns all exam results for a specific user.
    """
    results_list = []
    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM exam_results WHERE chat_id = ?", (chat_id,))
        rows = cursor.fetchall()
        for row in rows:
            results_list.append(dict(row))
    return results_list
