import sqlite3
from datetime import date, timedelta

DB_PATH = "bot.db"


def _connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                current_streak INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0,
                last_practice_date TEXT DEFAULT NULL
            )
        """)
        conn.commit()


def get_streak(user_id: int) -> tuple[int, int]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT current_streak, best_streak FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return 0, 0
    return row[0], row[1]


def update_streak(user_id: int) -> tuple[int, int]:
    today = date.today()
    yesterday = today - timedelta(days=1)

    with _connect() as conn:
        row = conn.execute(
            "SELECT current_streak, best_streak, last_practice_date FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO users (user_id, current_streak, best_streak, last_practice_date) VALUES (?, 1, 1, ?)",
                (user_id, today.isoformat()),
            )
            conn.commit()
            return 1, 1

        current, best, last_date_str = row

        if last_date_str == today.isoformat():
            return current, best

        if last_date_str == yesterday.isoformat():
            current += 1
        else:
            current = 1

        if current > best:
            best = current

        conn.execute(
            "UPDATE users SET current_streak = ?, best_streak = ?, last_practice_date = ? WHERE user_id = ?",
            (current, best, today.isoformat(), user_id),
        )
        conn.commit()
        return current, best
