import os
import sqlite3
from datetime import date, timedelta, datetime, timezone

# БД хранится в data/ — эта папка в git, можно скачать через /db и запушить обратно
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(_DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(_DATA_DIR, "bot.db")

# Московское время (UTC+3), учебный день начинается в 7:00
MSK = timezone(timedelta(hours=3))


def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _today_msk() -> date:
    """Текущая 'учебная' дата по МСК (день начинается в 7:00)."""
    now = datetime.now(MSK)
    if now.hour < 7:
        return (now - timedelta(days=1)).date()
    return now.date()


def init_db():
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT DEFAULT '',
                current_streak INTEGER DEFAULT 0,
                best_streak INTEGER DEFAULT 0,
                last_practice_date TEXT DEFAULT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tense_key TEXT NOT NULL,
                score INTEGER NOT NULL,
                total INTEGER NOT NULL,
                finished_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS production_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                tense_key TEXT NOT NULL,
                is_correct INTEGER NOT NULL,
                finished_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS question_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tense_key TEXT NOT NULL,
                sentence TEXT NOT NULL,
                correct TEXT NOT NULL,
                options TEXT NOT NULL,
                explanation_ru TEXT NOT NULL,
                qtype TEXT DEFAULT 'quiz',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL UNIQUE,
                tense_key TEXT NOT NULL,
                qtype TEXT NOT NULL,
                question_data TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_answers (
                user_id INTEGER NOT NULL,
                daily_id INTEGER NOT NULL,
                is_correct INTEGER NOT NULL,
                answered_at TEXT NOT NULL,
                PRIMARY KEY (user_id, daily_id),
                FOREIGN KEY (daily_id) REFERENCES daily_questions(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_seen_questions (
                user_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                seen_at TEXT NOT NULL,
                PRIMARY KEY (user_id, question_id),
                FOREIGN KEY (question_id) REFERENCES question_cache(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS leitner_progress (
                user_id INTEGER NOT NULL,
                tense_key TEXT NOT NULL,
                box INTEGER DEFAULT 1,
                next_review TEXT NOT NULL,
                last_studied TEXT,
                correct_streak INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, tense_key)
            )
        """)
        # Миграции для существующих таблиц
        try:
            conn.execute("ALTER TABLE users ADD COLUMN username TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("ALTER TABLE question_cache ADD COLUMN qtype TEXT DEFAULT 'quiz'")
        except sqlite3.OperationalError:
            pass
        conn.commit()


# ── Streak ────────────────────────────────────────────

def get_streak(user_id: int) -> tuple[int, int]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT current_streak, best_streak FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return 0, 0
    return row[0], row[1]


def update_streak(user_id: int, username: str = "") -> tuple[int, int]:
    today = _today_msk()
    yesterday = today - timedelta(days=1)

    with _connect() as conn:
        row = conn.execute(
            "SELECT current_streak, best_streak, last_practice_date FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()

        if row is None:
            conn.execute(
                "INSERT INTO users (user_id, username, current_streak, best_streak, last_practice_date) VALUES (?, ?, 1, 1, ?)",
                (user_id, username, today.isoformat()),
            )
            conn.commit()
            return 1, 1

        current, best, last_date_str = row

        # Обновляем username при каждом обращении
        if username:
            conn.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))

        if last_date_str == today.isoformat():
            conn.commit()
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


# ── Quiz results ──────────────────────────────────────

def save_quiz_result(user_id: int, tense_key: str, score: int, total: int):
    now = datetime.now(MSK).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO quiz_results (user_id, tense_key, score, total, finished_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, tense_key, score, total, now),
        )
        conn.commit()


def save_production_result(user_id: int, tense_key: str, is_correct: bool):
    now = datetime.now(MSK).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO production_results (user_id, tense_key, is_correct, finished_at) VALUES (?, ?, ?, ?)",
            (user_id, tense_key, int(is_correct), now),
        )
        conn.commit()


# ── Question cache ────────────────────────────────────

def save_question_to_cache(tense_key: str, question: dict, qtype: str = "quiz") -> int | None:
    """Сохраняет вопрос в кэш (дедупликация по sentence+qtype). Возвращает id вопроса."""
    import json
    now = datetime.now(MSK).isoformat()
    sentence = question["sentence"]
    with _connect() as conn:
        row = conn.execute(
            "SELECT id FROM question_cache WHERE tense_key = ? AND sentence = ? AND qtype = ?",
            (tense_key, sentence, qtype),
        ).fetchone()
        if row:
            return row[0]
        cursor = conn.execute(
            "INSERT INTO question_cache (tense_key, sentence, correct, options, explanation_ru, qtype, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tense_key, sentence, question["correct"],
             json.dumps(question["options"]), question["explanation_ru"], qtype, now),
        )
        conn.commit()
        return cursor.lastrowid


def get_cached_question(tense_key: str, user_id: int, qtype: str = "quiz") -> dict | None:
    """Берёт случайный вопрос из кэша, который этот пользователь ещё не видел."""
    import json
    import random as _rnd

    with _connect() as conn:
        rows = conn.execute("""
            SELECT qc.id, qc.sentence, qc.correct, qc.options, qc.explanation_ru
            FROM question_cache qc
            WHERE qc.tense_key = ? AND qc.qtype = ?
              AND qc.id NOT IN (
                  SELECT question_id FROM user_seen_questions WHERE user_id = ?
              )
        """, (tense_key, qtype, user_id)).fetchall()

    if not rows:
        return None

    row = _rnd.choice(rows)
    mark_question_seen(user_id, row[0])

    return {
        "sentence": row[1],
        "correct": row[2],
        "options": json.loads(row[3]),
        "explanation_ru": row[4],
    }


def get_recent_sentences(tense_key: str, limit: int = 10) -> list[str]:
    """Возвращает последние N предложений из кэша для данного времени."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT sentence FROM question_cache WHERE tense_key = ? ORDER BY id DESC LIMIT ?",
            (tense_key, limit),
        ).fetchall()
    return [r[0] for r in rows]


def mark_question_seen(user_id: int, question_id: int):
    """Помечает вопрос как показанный пользователю."""
    now = datetime.now(MSK).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_seen_questions (user_id, question_id, seen_at) VALUES (?, ?, ?)",
            (user_id, question_id, now),
        )
        conn.commit()


# ── Daily questions ───────────────────────────────────

def get_today_daily() -> dict | None:
    """Возвращает daily-вопрос на сегодня (или None если нет)."""
    import json
    today = _today_msk().isoformat()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, tense_key, qtype, question_data FROM daily_questions WHERE date = ?",
            (today,),
        ).fetchone()
    if not row:
        return None
    return {
        "daily_id": row[0],
        "tense_key": row[1],
        "qtype": row[2],
        **json.loads(row[3]),
    }


def save_daily_question(tense_key: str, qtype: str, question_data: dict) -> int:
    """Сохраняет daily-вопрос на сегодня."""
    import json
    today = _today_msk().isoformat()
    now = datetime.now(MSK).isoformat()
    with _connect() as conn:
        cursor = conn.execute(
            "INSERT OR IGNORE INTO daily_questions (date, tense_key, qtype, question_data, created_at) VALUES (?, ?, ?, ?, ?)",
            (today, tense_key, qtype, json.dumps(question_data), now),
        )
        conn.commit()
        if cursor.lastrowid:
            return cursor.lastrowid
        row = conn.execute("SELECT id FROM daily_questions WHERE date = ?", (today,)).fetchone()
        return row[0]


def has_answered_daily(user_id: int, daily_id: int) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM daily_answers WHERE user_id = ? AND daily_id = ?",
            (user_id, daily_id),
        ).fetchone()
    return row is not None


def save_daily_answer(user_id: int, daily_id: int, is_correct: bool):
    now = datetime.now(MSK).isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO daily_answers (user_id, daily_id, is_correct, answered_at) VALUES (?, ?, ?, ?)",
            (user_id, daily_id, int(is_correct), now),
        )
        conn.commit()


def get_all_user_ids() -> list[int]:
    """Все user_id для рассылки daily."""
    with _connect() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
    return [r[0] for r in rows]


# ── Leitner (обучение) ────────────────────────────────

# Интервалы повторения по коробкам (в днях)
LEITNER_INTERVALS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 14}


def get_leitner_progress(user_id: int) -> dict[str, dict]:
    """Возвращает прогресс Лейтнера для всех времён пользователя."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT tense_key, box, next_review, last_studied, correct_streak FROM leitner_progress WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    result = {}
    for tense_key, box, next_review, last_studied, correct_streak in rows:
        result[tense_key] = {
            "box": box,
            "next_review": next_review,
            "last_studied": last_studied,
            "correct_streak": correct_streak,
        }
    return result


def init_leitner(user_id: int, tense_key: str):
    """Инициализирует время в коробку 1 если ещё нет записи."""
    today = _today_msk().isoformat()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO leitner_progress (user_id, tense_key, box, next_review) VALUES (?, ?, 1, ?)",
            (user_id, tense_key, today),
        )
        conn.commit()


def update_leitner(user_id: int, tense_key: str, is_correct: bool):
    """Обновляет коробку Лейтнера после ответа (legacy, для совместимости)."""
    return update_leitner_session(user_id, tense_key, 1 if is_correct else 0, 1)


def update_leitner_session(user_id: int, tense_key: str, score: int, total: int):
    """Обновляет коробку Лейтнера по итогу сессии.

    Правила:
    - Сессия засчитана (≥80%) И next_review наступил → streak +1
    - 3 засчитанных сессии подряд → коробка вверх
    - Сессия провалена (<80%) → streak сброс, коробка в 1
    - Если next_review ещё не наступил → коробка НЕ меняется (но streak не теряется)
    """
    today = _today_msk()
    pct = round(score / total * 100) if total > 0 else 0

    with _connect() as conn:
        row = conn.execute(
            "SELECT box, correct_streak, next_review FROM leitner_progress WHERE user_id = ? AND tense_key = ?",
            (user_id, tense_key),
        ).fetchone()

        if row is None:
            init_leitner(user_id, tense_key)
            box, streak, next_review_str = 1, 0, today.isoformat()
        else:
            box, streak, next_review_str = row

        next_review_date = date.fromisoformat(next_review_str)
        is_due = today >= next_review_date  # Пора повторять?

        if pct >= 80:
            if is_due:
                # Сессия засчитана — увеличиваем серию
                streak += 1
                if streak >= 3 and box < 5:
                    box += 1
                    streak = 0
                # Устанавливаем next_review для НОВОЙ коробки
                interval = LEITNER_INTERVALS.get(box, 0)
                new_next_review = (today + timedelta(days=interval)).isoformat()
            else:
                # Ещё не пора повторять — коробка не меняется, практика «вхолостую»
                new_next_review = next_review_str
        else:
            # Провал — сброс в коробку 1
            box = 1
            streak = 0
            interval = LEITNER_INTERVALS.get(box, 0)
            new_next_review = (today + timedelta(days=interval)).isoformat()

        conn.execute("""
            UPDATE leitner_progress
            SET box = ?, next_review = ?, last_studied = ?, correct_streak = ?
            WHERE user_id = ? AND tense_key = ?
        """, (box, new_next_review, today.isoformat(), streak, user_id, tense_key))
        conn.commit()

    return box, streak


def get_due_tenses(user_id: int) -> list[str]:
    """Возвращает времена, которые пора повторить (next_review <= сегодня)."""
    today = _today_msk().isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT tense_key FROM leitner_progress WHERE user_id = ? AND next_review <= ? ORDER BY box ASC, next_review ASC",
            (user_id, today),
        ).fetchall()
    return [r[0] for r in rows]


def get_leitner_stats(user_id: int) -> dict:
    """Статистика обучения: сколько в каждой коробке, сколько пора повторить."""
    today = _today_msk().isoformat()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT tense_key, box, next_review, correct_streak FROM leitner_progress WHERE user_id = ?",
            (user_id,),
        ).fetchall()

    boxes = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    due_count = 0
    total = len(rows)
    for _, box, next_review, _ in rows:
        boxes[box] = boxes.get(box, 0) + 1
        if next_review <= today:
            due_count += 1

    return {"boxes": boxes, "due_count": due_count, "total": total}


# ── Profile stats ─────────────────────────────────────

def get_profile_stats(user_id: int) -> dict:
    with _connect() as conn:
        # Общая статистика по квизам
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(score), 0), COALESCE(SUM(total), 0) FROM quiz_results WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        total_quizzes = row[0]
        total_correct = row[1]
        total_questions = row[2]

        # Статистика по каждому времени
        tense_rows = conn.execute(
            "SELECT tense_key, SUM(score), SUM(total) FROM quiz_results WHERE user_id = ? GROUP BY tense_key",
            (user_id,),
        ).fetchall()
        tense_stats = {}
        for tense_key, correct, total in tense_rows:
            pct = round(correct / total * 100) if total > 0 else 0
            tense_stats[tense_key] = {"correct": correct, "total": total, "pct": pct}

        # Production статистика
        prod_row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(is_correct), 0) FROM production_results WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        prod_total = prod_row[0]
        prod_correct = prod_row[1]

        # Streak
        streak_row = conn.execute(
            "SELECT current_streak, best_streak FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        current_streak = streak_row[0] if streak_row else 0
        best_streak = streak_row[1] if streak_row else 0

    return {
        "total_quizzes": total_quizzes,
        "total_correct": total_correct,
        "total_questions": total_questions,
        "tense_stats": tense_stats,
        "prod_total": prod_total,
        "prod_correct": prod_correct,
        "current_streak": current_streak,
        "best_streak": best_streak,
    }


# ── Leaderboard ───────────────────────────────────────

def get_leaderboard_by_group(tense_keys: list[str], limit: int = 10) -> list[dict]:
    """Рейтинг по группе времён (Present/Past/Future)."""
    placeholders = ",".join("?" * len(tense_keys))
    with _connect() as conn:
        rows = conn.execute(f"""
            SELECT u.user_id, u.username, u.best_streak,
                   COALESCE(SUM(q.score), 0) as total_correct,
                   COALESCE(SUM(q.total), 0) as total_questions
            FROM users u
            LEFT JOIN quiz_results q ON u.user_id = q.user_id AND q.tense_key IN ({placeholders})
            GROUP BY u.user_id
            HAVING total_questions > 0
            ORDER BY total_correct * 1.0 / total_questions DESC, u.best_streak DESC
            LIMIT ?
        """, (*tense_keys, limit)).fetchall()

    result = []
    for row in rows:
        user_id, username, best_streak, correct, total = row
        pct = round(correct / total * 100) if total > 0 else 0
        result.append({
            "user_id": user_id,
            "username": username or f"User {user_id}",
            "best_streak": best_streak,
            "correct": correct,
            "total": total,
            "pct": pct,
        })
    return result


def get_leaderboard(limit: int = 10) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute("""
            SELECT u.user_id, u.username, u.current_streak, u.best_streak,
                   COALESCE(SUM(q.score), 0) as total_correct,
                   COALESCE(SUM(q.total), 0) as total_questions
            FROM users u
            LEFT JOIN quiz_results q ON u.user_id = q.user_id
            GROUP BY u.user_id
            HAVING total_questions > 0
            ORDER BY total_correct * 1.0 / total_questions DESC, u.best_streak DESC
            LIMIT ?
        """, (limit,)).fetchall()

    result = []
    for row in rows:
        user_id, username, current_streak, best_streak, correct, total = row
        pct = round(correct / total * 100) if total > 0 else 0
        result.append({
            "user_id": user_id,
            "username": username or f"User {user_id}",
            "current_streak": current_streak,
            "best_streak": best_streak,
            "correct": correct,
            "total": total,
            "pct": pct,
        })
    return result
