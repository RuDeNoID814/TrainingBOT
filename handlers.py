import logging
import random
from datetime import datetime, timezone, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from tenses import TENSES, TENSE_GROUPS
from gemini_api import generate_question, check_sentence, generate_find_error
from irregular_verbs import IRREGULAR_VERBS
from database import (
    get_streak, update_streak, save_quiz_result,
    save_production_result, get_profile_stats, get_leaderboard,
    get_leaderboard_by_group,
    get_today_daily, save_daily_question, has_answered_daily,
    save_daily_answer,
    get_leitner_progress, init_leitner, update_leitner_session,
    get_due_tenses, get_leitner_stats,
)

# Московское время (UTC+3), день начинается в 7:00
MSK = timezone(timedelta(hours=3))


def _is_new_day_streak(context) -> bool:
    """Проверяет, нужно ли показывать уведомление о streak (первая активность нового дня)."""
    now = datetime.now(MSK)
    # Текущий "учебный день" начинается в 7:00
    if now.hour < 7:
        today_start = now.replace(hour=7, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        today_start = now.replace(hour=7, minute=0, second=0, microsecond=0)

    last_shown = context.user_data.get("streak_shown_date")
    today_key = today_start.strftime("%Y-%m-%d")

    if last_shown == today_key:
        return False

    context.user_data["streak_shown_date"] = today_key
    return True

logger = logging.getLogger(__name__)

MAX_TG_MSG = 4096  # Лимит Telegram на длину сообщения


async def _safe_edit(query, text: str, reply_markup=None, parse_mode="HTML"):
    """edit_message_text с защитой от слишком длинного текста."""
    if len(text) <= MAX_TG_MSG:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return

    # Обрезаем текст до лимита, оставляя место для "..."
    cut = text[:MAX_TG_MSG - 50] + "\n\n<i>... (обрезано)</i>"
    await query.edit_message_text(cut, reply_markup=reply_markup, parse_mode=parse_mode)


QUESTIONS_PER_SESSION = 10
RANDOM_QUESTIONS = 12  # Рандом — ровно 12 вопросов, по одному на каждое время

# Названия времён для выделения жирным в объяснениях
_TENSE_NAMES = [t["name"] for t in TENSES.values()]


def _bold_tense_in_explanation(text: str) -> str:
    """Выделяет название времени жирным (HTML) в тексте объяснения."""
    for name in _TENSE_NAMES:
        if name in text:
            text = text.replace(name, f"<b>{name}</b>", 1)
            break
    return text


# ── /start ──────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    current, best = get_streak(user_id)
    streak_line = f"🔥 Streak: {current} дн." if current > 0 else ""

    keyboard = [
        [InlineKeyboardButton("👤 Профиль", callback_data="profile"),
         InlineKeyboardButton("🏆 Рейтинг", callback_data="leaderboard")],
        [InlineKeyboardButton("📚 Практика", callback_data="practice"),
         InlineKeyboardButton("📅 Daily", callback_data="daily")],
        [InlineKeyboardButton("🎓 Обучение", callback_data="learn_menu")],
        [InlineKeyboardButton("✍️ Написать предложение", callback_data="production_menu")],
        [InlineKeyboardButton("📋 Шпаргалка", callback_data="cheatsheet"),
         InlineKeyboardButton("ℹ️ Инфо", callback_data="info")],
    ]

    text = (
        "Привет! Я — Tense Trainer Bot.\n\n"
        "Помогу тебе выучить все 12 английских времён!\n"
        f"{streak_line}\n\n"
        "Выбери, что хочешь сделать:"
    )

    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


# ── Главное меню ────────────────────────────────────────

async def show_main_menu(query, context):
    user_id = query.from_user.id
    current, best = get_streak(user_id)
    streak_line = f"🔥 Streak: {current} дн." if current > 0 else ""

    keyboard = [
        [InlineKeyboardButton("👤 Профиль", callback_data="profile"),
         InlineKeyboardButton("🏆 Рейтинг", callback_data="leaderboard")],
        [InlineKeyboardButton("📚 Практика", callback_data="practice"),
         InlineKeyboardButton("📅 Daily", callback_data="daily")],
        [InlineKeyboardButton("🎓 Обучение", callback_data="learn_menu")],
        [InlineKeyboardButton("✍️ Написать предложение", callback_data="production_menu")],
        [InlineKeyboardButton("📋 Шпаргалка", callback_data="cheatsheet"),
         InlineKeyboardButton("ℹ️ Инфо", callback_data="info")],
    ]

    await query.edit_message_text(
        f"Главное меню\n{streak_line}\n\nВыбери, что хочешь сделать:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Выбор группы времён ────────────────────────────────

async def show_groups(query, context):
    keyboard = [
        [InlineKeyboardButton("📖 Времена", callback_data="tenses_menu")],
        [InlineKeyboardButton("🎲 Рандом — все 12 форм", callback_data="random_info")],
        [InlineKeyboardButton("🔍 Найди ошибку", callback_data="find_error_menu")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        "Выбери режим практики:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def show_tenses_menu(query, context):
    """Подменю выбора группы времён."""
    keyboard = [
        [InlineKeyboardButton("Present", callback_data="group_present")],
        [InlineKeyboardButton("Past", callback_data="group_past")],
        [InlineKeyboardButton("Future", callback_data="group_future")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="practice")],
    ]
    await query.edit_message_text(
        "📖 Выбери группу времён:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Выбор конкретного времени ───────────────────────────

async def show_tenses_in_group(query, group_key: str):
    tenses_list = TENSE_GROUPS[group_key]
    keyboard = []
    for t_key in tenses_list:
        name = TENSES[t_key]["name"]
        keyboard.append([InlineKeyboardButton(name, callback_data=f"tense_{t_key}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="tenses_menu")])

    group_title = {"present": "Present", "past": "Past", "future": "Future"}.get(group_key, group_key)
    await query.edit_message_text(
        f"Выбери время ({group_title}):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Карточка теории ─────────────────────────────────────

async def show_theory(query, tense_key: str):
    t = TENSES[tense_key]
    # Определяем группу для кнопки "Назад"
    group = None
    for g_key, tense_keys in TENSE_GROUPS.items():
        if tense_key in tense_keys:
            group = g_key
            break

    text = (
        f"📖 <b>{t['name']}</b>\n\n"
        f"📐 <b>Формула:</b>\n{t['formula']}\n\n"
        f"🔑 <b>Маркеры:</b>\n{t['markers']}\n\n"
        f"💬 <b>Пример:</b>\n{t['example']}\n\n"
        f"📝 <b>Формы:</b>\n{t['forms']}\n\n"
        f"✏️ <b>Окончания:</b>\n{t['endings']}"
    )
    back_data = f"group_{group}" if group else "practice"
    keyboard = [
        [InlineKeyboardButton("🎯 Начать тест", callback_data=f"quiz_{tense_key}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=back_data)],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ── Квиз: запуск и отправка вопроса ────────────────────

async def start_quiz(query, context, tense_key: str):
    context.user_data["current_tense"] = tense_key
    context.user_data["score"] = 0
    context.user_data["question_num"] = 0
    context.user_data["question_tenses"] = []
    context.user_data["question_correct"] = []
    await send_question(query, context)


async def show_random_info(query, context):
    """Экран описания рандомного квиза."""
    text = (
        "🎲 <b>Рандом — все 12 форм</b>\n\n"
        "12 вопросов — по одному на каждую видовременную форму.\n"
        "Порядок случайный. Проверь свои знания по всем временам!"
    )
    keyboard = [
        [InlineKeyboardButton("🎯 Начать", callback_data="random")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="practice")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def start_random_quiz(query, context):
    # Перемешиваем все 12 времён — по одному вопросу на каждое
    all_tenses = list(TENSES.keys())
    random.shuffle(all_tenses)
    context.user_data["current_tense"] = "random"
    context.user_data["random_tense_order"] = all_tenses
    context.user_data["score"] = 0
    context.user_data["question_num"] = 0
    context.user_data["question_tenses"] = []
    context.user_data["question_correct"] = []
    await send_question(query, context)


async def send_question(query, context):
    q_num = context.user_data["question_num"]
    is_random = context.user_data["current_tense"] == "random"
    total_questions = RANDOM_QUESTIONS if is_random else QUESTIONS_PER_SESSION

    if q_num >= total_questions:
        await show_results(query, context)
        return

    tense_key = context.user_data["current_tense"]
    if is_random:
        tense_order = context.user_data.get("random_tense_order", list(TENSES.keys()))
        tense_key = tense_order[q_num]

    user_id = query.from_user.id
    await query.edit_message_text(f"⏳ Генерирую вопрос {q_num + 1}/{total_questions}...")

    data = generate_question(tense_key, user_id=user_id)
    if data is None:
        await query.edit_message_text(
            "😔 Не удалось сгенерировать вопрос. Попробуй ещё раз.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Повторить", callback_data="next_question")],
                [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
            ]),
        )
        return

    # Трекаем реальное время для каждого вопроса (важно для random)
    context.user_data.setdefault("question_tenses", []).append(tense_key)

    options = data["options"][:]
    random.shuffle(options)

    context.user_data["correct_answer"] = data["correct"]
    context.user_data["shuffled_options"] = options
    context.user_data["explanation_ru"] = data["explanation_ru"]

    keyboard = []
    for i, opt in enumerate(options):
        keyboard.append([InlineKeyboardButton(opt, callback_data=f"answer_{i}")])

    await query.edit_message_text(
        f"❓ Вопрос {q_num + 1}/{total_questions}\n\n{data['sentence']}",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Обработка ответа ───────────────────────────────────

async def handle_answer(query, context, answer_index: int):
    options = context.user_data.get("shuffled_options", [])
    correct = context.user_data.get("correct_answer", "")
    explanation = context.user_data.get("explanation_ru", "")

    if answer_index >= len(options):
        return

    chosen = options[answer_index]
    context.user_data["question_num"] += 1

    q_num = context.user_data["question_num"]
    is_random = context.user_data.get("current_tense") == "random"
    total_questions = RANDOM_QUESTIONS if is_random else QUESTIONS_PER_SESSION
    is_last = q_num >= total_questions

    explanation_fmt = _bold_tense_in_explanation(explanation)
    if chosen == correct:
        context.user_data["score"] += 1
        context.user_data.setdefault("question_correct", []).append(True)
        text = f"✅ Правильно! Ответ: {correct}\n\n💡 {explanation_fmt}"
    else:
        context.user_data.setdefault("question_correct", []).append(False)
        text = (
            f"❌ Неправильно!\n\n"
            f"Твой ответ: {chosen}\n"
            f"Правильный: {correct}\n\n"
            f"💡 {explanation_fmt}"
        )

    if is_last:
        keyboard = [[InlineKeyboardButton("📊 Результаты", callback_data="next_question")]]
    else:
        keyboard = [
            [InlineKeyboardButton("➡️ Следующий вопрос", callback_data="next_question")],
            [InlineKeyboardButton("🚪 Завершить тест", callback_data="finish_quiz")],
        ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ── Результаты ──────────────────────────────────────────

async def show_results(query, context):
    score = context.user_data.get("score", 0)
    is_random = context.user_data.get("current_tense") == "random"
    total_q = RANDOM_QUESTIONS if is_random else QUESTIONS_PER_SESSION
    answered = context.user_data.get("question_num", total_q)
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name or ""
    current, best = update_streak(user_id, username)

    # Сохраняем результаты по реальным временам (не "random")
    question_tenses = context.user_data.get("question_tenses", [])
    question_correct = context.user_data.get("question_correct", [])

    if question_tenses:
        # Группируем по временам
        from collections import Counter
        tense_scores: dict[str, list[int, int]] = {}
        for i, t_key in enumerate(question_tenses):
            if t_key not in tense_scores:
                tense_scores[t_key] = [0, 0]
            tense_scores[t_key][1] += 1
            if i < len(question_correct) and question_correct[i]:
                tense_scores[t_key][0] += 1
        for t_key, (correct, total) in tense_scores.items():
            save_quiz_result(user_id, t_key, correct, total)
    else:
        # Fallback для старого формата
        tense_key = context.user_data.get("current_tense", "present_simple")
        save_quiz_result(user_id, tense_key, score, answered)

    # Процент для оценки (от отвеченных вопросов)
    pct = (score / answered * 100) if answered > 0 else 0

    if pct <= 30:
        emoji = "📖"
        comment = "Нужно подтянуть! Попробуй повторить теорию."
    elif pct <= 60:
        emoji = "👍"
        comment = "Неплохо! Но есть куда расти."
    elif pct <= 90:
        emoji = "🎉"
        comment = "Отлично! Ты почти идеален!"
    else:
        emoji = "🏆"
        comment = "Идеально! Ты мастер!"

    text = f"{emoji} Результат: {score}/{answered}\n\n{comment}"

    # Streak показываем только при первой активности нового дня
    if _is_new_day_streak(context):
        text += f"\n\n🔥 Streak: {current} дн.!"

    keyboard = [
        [InlineKeyboardButton("🔄 Ещё раз", callback_data="try_again")],
        [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


# ── Досрочное завершение теста ─────────────────────────

async def confirm_finish(query, context):
    score = context.user_data.get("score", 0)
    q_num = context.user_data.get("question_num", 0)
    is_random = context.user_data.get("current_tense") == "random"
    total_questions = RANDOM_QUESTIONS if is_random else QUESTIONS_PER_SESSION

    text = (
        f"Ты ответил на {q_num} из {total_questions} вопросов.\n"
        f"Текущий счёт: {score}/{q_num}\n\n"
        "Что сделать?"
    )
    keyboard = [
        [InlineKeyboardButton("💾 Сохранить и завершить", callback_data="finish_save")],
        [InlineKeyboardButton("🗑 Сбросить результат", callback_data="finish_reset")],
        [InlineKeyboardButton("↩️ Продолжить тест", callback_data="next_question")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def finish_save(query, context):
    """Сохраняет streak и показывает результат."""
    await show_results(query, context)


async def finish_reset(query, context):
    """Сбрасывает результат и возвращает в меню."""
    context.user_data.pop("score", None)
    context.user_data.pop("question_num", None)
    context.user_data.pop("current_tense", None)
    await show_main_menu(query, context)


# ── Production — пользователь пишет предложение ───────

async def show_production_menu(query, context):
    """Меню выбора времени для написания предложения."""
    keyboard = [
        [InlineKeyboardButton("🎲 Случайное время", callback_data="prod_random")],
    ]
    for group_name, tense_keys in TENSE_GROUPS.items():
        row = []
        for t_key in tense_keys:
            short_name = TENSES[t_key]["name"].replace(" Perfect Continuous", " PC").replace(" Continuous", " Cont.").replace(" Perfect", " Perf.")
            row.append(InlineKeyboardButton(short_name, callback_data=f"prod_{t_key}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")])

    await query.edit_message_text(
        "✍️ Выбери время, в котором хочешь написать предложение:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def start_production(query, context, tense_key: str):
    if tense_key == "random":
        tense_key = random.choice(list(TENSES.keys()))
    context.user_data["production_tense"] = tense_key
    context.user_data["awaiting_sentence"] = True

    tense_name = TENSES[tense_key]["name"]
    formula = TENSES[tense_key]["formula"]

    text = (
        f"✍️ Напиши своё предложение в <b>{tense_name}</b>\n\n"
        f"📐 Напоминание: {formula}\n\n"
        "Просто напиши предложение на английском в чат, и я проверю!"
    )
    keyboard = [[InlineKeyboardButton("⬅️ Назад", callback_data="production_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def handle_user_sentence(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сначала проверяем мини-задание обучения
    if context.user_data.get("awaiting_learn_sentence"):
        await handle_learn_sentence(update, context)
        return

    if not context.user_data.get("awaiting_sentence"):
        return

    context.user_data["awaiting_sentence"] = False
    tense_key = context.user_data.get("production_tense", "present_simple")
    tense_name = TENSES[tense_key]["name"]
    user_text = update.message.text.strip()

    await update.message.reply_text("⏳ Проверяю твоё предложение...")

    result = check_sentence(tense_key, user_text)

    if result is None:
        keyboard = [
            [InlineKeyboardButton("🔄 Попробовать ещё", callback_data="production_menu")],
            [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
        ]
        await update.message.reply_text(
            "😔 Не удалось проверить. Попробуй ещё раз.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    is_correct = result.get("is_correct", False)
    corrected = result.get("corrected", "")
    feedback = result.get("feedback_ru", "")

    save_production_result(update.effective_user.id, tense_key, is_correct)

    if is_correct:
        text = (
            f"✅ Отлично! Правильно — <b>{tense_name}</b>\n\n"
            f"Твоё предложение: {user_text}\n\n"
            f"💡 {feedback}"
        )
    else:
        text = (
            f"❌ Не совсем верно\n\n"
            f"Твоё: {user_text}\n"
            f"Исправленное: {corrected}\n\n"
            f"💡 {feedback}"
        )

    keyboard = [
        [InlineKeyboardButton("✍️ Написать ещё", callback_data="production_menu")],
        [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ── Профиль ───────────────────────────────────────────

async def show_profile(query, context):
    user_id = query.from_user.id
    name = query.from_user.first_name or "Пользователь"
    stats = get_profile_stats(user_id)

    total_pct = round(stats["total_correct"] / stats["total_questions"] * 100) if stats["total_questions"] > 0 else 0

    # Уровень
    if stats["total_quizzes"] == 0:
        level = "🌱 Новичок"
    elif total_pct < 50:
        level = "📗 Начинающий"
    elif total_pct < 75:
        level = "📘 Средний"
    elif total_pct < 90:
        level = "📙 Продвинутый"
    else:
        level = "📕 Мастер"

    text = (
        f"👤 <b>{name}</b>\n"
        f"{level}\n\n"
        f"🔥 Streak: {stats['current_streak']} дн. (лучший: {stats['best_streak']})\n"
        f"📝 Вопросов отвечено: {stats['total_questions']}\n"
        f"✅ Правильных: {stats['total_correct']}/{stats['total_questions']}"
    )
    if stats["total_questions"] > 0:
        text += f" ({total_pct}%)"

    if stats["prod_total"] > 0:
        prod_pct = round(stats["prod_correct"] / stats["prod_total"] * 100)
        text += f"\n✍️ Предложений: {stats['prod_correct']}/{stats['prod_total']} ({prod_pct}%)"

    # Прогресс обучения (Лейтнер)
    leitner = get_leitner_progress(user_id)
    if leitner:
        mastered = sum(1 for v in leitner.values() if v["box"] == 5)
        total_studied = len(leitner)
        text += f"\n\n🎓 <b>Обучение:</b> {mastered}/12 выучено"
        if mastered == 12:
            text += "\n🏆 Все 12 времён выучены!"
        elif mastered > 0:
            mastered_names = [TENSES[k]["name"] for k, v in leitner.items() if v["box"] == 5]
            text += "\n✅ " + ", ".join(mastered_names)

    # Статистика по временам
    if stats["tense_stats"]:
        text += "\n\n📊 <b>По временам:</b>"
        for t_key, ts in stats["tense_stats"].items():
            tense_name = TENSES.get(t_key, {}).get("name", t_key)
            bar = "🟩" if ts["pct"] >= 70 else "🟨" if ts["pct"] >= 40 else "🟥"
            text += f"\n{bar} {tense_name}: {ts['pct']}% ({ts['correct']}/{ts['total']})"

    keyboard = [
        [InlineKeyboardButton("🏆 Рейтинг", callback_data="leaderboard")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="main_menu")],
    ]
    await _safe_edit(query, text, reply_markup=InlineKeyboardMarkup(keyboard))


# ── Рейтинг ──────────────────────────────────────────

async def show_leaderboard(query, context, group: str = None):
    user_id = query.from_user.id

    if group:
        tense_keys = TENSE_GROUPS[group]
        group_title = {"present": "Present", "past": "Past", "future": "Future"}[group]
        leaders = get_leaderboard_by_group(tense_keys, 10)
        title = f"🏆 <b>Рейтинг — {group_title}</b>\n\n"
    else:
        leaders = get_leaderboard(10)
        title = "🏆 <b>Глобальный рейтинг</b>\n\n"

    if not leaders:
        text = f"{title}Рейтинг пока пуст.\n\nПройди хотя бы один тест!"
    else:
        text = title
        medals = ["🥇", "🥈", "🥉"]
        for i, p in enumerate(leaders):
            medal = medals[i] if i < 3 else f"{i + 1}."
            name = p["username"]
            marker = " ← ты" if p["user_id"] == user_id else ""
            text += f"{medal} <b>{name}</b> — {p['pct']}% ({p['correct']}/{p['total']}) 🔥{p['best_streak']}{marker}\n"

    keyboard = [
        [InlineKeyboardButton("🌍 Глобальный", callback_data="leaderboard"),
         InlineKeyboardButton("Present", callback_data="lb_present"),
         InlineKeyboardButton("Past", callback_data="lb_past"),
         InlineKeyboardButton("Future", callback_data="lb_future")],
        [InlineKeyboardButton("👤 Мой профиль", callback_data="profile")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ── Шпаргалка ──────────────────────────────────────────

async def show_cheatsheet(query):
    lines = ["📋 Шпаргалка — все 12 времён\n"]
    for key, t in TENSES.items():
        lines.append(f"▪️ {t['name']}\n   {t['formula']}\n   {t['example']}\n")
    text = "\n".join(lines)

    keyboard = [
        [InlineKeyboardButton("📕 Неправильные глаголы", callback_data="irreg_verbs")],
        [InlineKeyboardButton("⬅️ В меню", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


# Группы неправильных глаголов для навигации
_IRREG_GROUPS = ["abc", "abb", "aba", "aaa"]
_IRREG_GROUP_TITLES = {
    "abc": "🔴 A-B-C (все разные)",
    "abb": "🟠 A-B-B (2-я = 3-я)",
    "aba": "🟡 A-B-A (1-я = 3-я)",
    "aaa": "🟢 A-A-A (все одинаковые)",
}


async def show_irreg_verbs_menu(query):
    """Главное меню неправильных глаголов — выбор группы."""
    total = sum(len(g["verbs"]) for g in IRREGULAR_VERBS.values())
    text = (
        f"📕 <b>Неправильные глаголы</b> ({total} шт.)\n\n"
        "Глаголы сгруппированы по типу изменения форм:\n"
        "V1 (базовая) → V2 (прошедшее) → V3 (причастие)\n\n"
        "Выбери группу:"
    )

    keyboard = []
    for gk in _IRREG_GROUPS:
        group = IRREGULAR_VERBS[gk]
        count = len(group["verbs"])
        keyboard.append([InlineKeyboardButton(
            f"{_IRREG_GROUP_TITLES[gk]} ({count})",
            callback_data=f"irreg_{gk}_0",
        )])
    keyboard.append([InlineKeyboardButton("⬅️ К шпаргалке", callback_data="cheatsheet")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_irreg_verbs_group(query, group_key: str, page: int = 0):
    """Показывает группу неправильных глаголов с пагинацией."""
    group = IRREGULAR_VERBS.get(group_key)
    if not group:
        await show_irreg_verbs_menu(query)
        return

    verbs = group["verbs"]
    per_page = 15
    total_pages = (len(verbs) + per_page - 1) // per_page
    page = max(0, min(page, total_pages - 1))

    start = page * per_page
    end = min(start + per_page, len(verbs))
    page_verbs = verbs[start:end]

    title = _IRREG_GROUP_TITLES.get(group_key, group_key)
    text = f"📕 <b>{title}</b>\n{group['description']}\n\n"
    text += "<code>V1          V2          V3</code>\n"

    for v1, v2, v3, ru in page_verbs:
        text += f"<code>{v1:<11} {v2:<11} {v3}</code>\n  <i>{ru}</i>\n"

    if total_pages > 1:
        text += f"\n📄 Стр. {page + 1}/{total_pages}"

    keyboard = []
    # Пагинация
    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"irreg_{group_key}_{page - 1}"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton("➡️", callback_data=f"irreg_{group_key}_{page + 1}"))
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("📕 Все группы", callback_data="irreg_verbs")])
    keyboard.append([InlineKeyboardButton("⬅️ К шпаргалке", callback_data="cheatsheet")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ── Streak ──────────────────────────────────────────────

async def show_streak(query):
    user_id = query.from_user.id
    current, best = get_streak(user_id)

    text = (
        "🔥 Твой streak\n\n"
        f"Текущий: {current} дн.\n"
        f"Лучший: {best} дн.\n\n"
        "Проходи хотя бы 1 тест в день, чтобы не потерять streak!"
    )

    keyboard = [[InlineKeyboardButton("⬅️ В меню", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


# ── Найди ошибку ─────────────────────────────────────

async def show_find_error_menu(query, context):
    """Выбор времени для режима 'Найди ошибку'."""
    keyboard = [
        [InlineKeyboardButton("🎲 Случайное время", callback_data="fe_random")],
    ]
    for group_name, tense_keys in TENSE_GROUPS.items():
        row = []
        for t_key in tense_keys:
            short = TENSES[t_key]["name"].replace(" Perfect Continuous", " PC").replace(" Continuous", " Cont.").replace(" Perfect", " Perf.")
            row.append(InlineKeyboardButton(short, callback_data=f"fe_{t_key}"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="practice")])

    await query.edit_message_text(
        "🔍 <b>Найди ошибку</b>\n\n"
        "Тебе покажут предложение с ошибкой во времени.\n"
        "Выбери правильный вариант исправления!\n\n"
        "Выбери время:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def send_find_error(query, context, tense_key: str):
    if tense_key == "random":
        tense_key = random.choice(list(TENSES.keys()))

    user_id = query.from_user.id
    context.user_data["fe_tense"] = tense_key

    await query.edit_message_text("⏳ Генерирую задание...")

    data = generate_find_error(tense_key, user_id=user_id)
    if data is None:
        await query.edit_message_text(
            "😔 Не удалось сгенерировать задание. Попробуй позже.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Повторить", callback_data=f"fe_{tense_key}")],
                [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
            ]),
        )
        return

    options = data["options"][:]
    random.shuffle(options)

    context.user_data["fe_correct"] = data["correct"]
    context.user_data["fe_options"] = options
    context.user_data["fe_explanation"] = data["explanation_ru"]

    keyboard = []
    for i, opt in enumerate(options):
        keyboard.append([InlineKeyboardButton(opt, callback_data=f"fe_ans_{i}")])

    tense_name = TENSES[tense_key]["name"]
    await query.edit_message_text(
        f"🔍 <b>Найди ошибку</b> ({tense_name})\n\n"
        f"❌ {data['sentence']}\n\n"
        "Выбери правильный вариант исправления:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def handle_find_error_answer(query, context, answer_index: int):
    options = context.user_data.get("fe_options", [])
    correct = context.user_data.get("fe_correct", "")
    explanation = context.user_data.get("fe_explanation", "")
    tense_key = context.user_data.get("fe_tense", "present_simple")

    if answer_index >= len(options):
        return

    chosen = options[answer_index]
    is_correct = chosen == correct
    user_id = query.from_user.id

    # Сохраняем результат
    save_quiz_result(user_id, tense_key, int(is_correct), 1)

    if is_correct:
        explanation_fmt = _bold_tense_in_explanation(explanation)
        text = f"✅ Правильно! Ответ: {correct}\n\n💡 {explanation_fmt}"
    else:
        explanation_fmt = _bold_tense_in_explanation(explanation)
        text = (
            f"❌ Неправильно!\n\n"
            f"Твой ответ: {chosen}\n"
            f"Правильный: {correct}\n\n"
            f"💡 {explanation_fmt}"
        )

    keyboard = [
        [InlineKeyboardButton("🔍 Ещё задание", callback_data=f"fe_{tense_key}")],
        [InlineKeyboardButton("🔍 Другое время", callback_data="find_error_menu")],
        [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ── Daily-вопрос ─────────────────────────────────────

async def show_daily(query, context):
    """Показывает daily-вопрос (генерирует если нет на сегодня)."""
    user_id = query.from_user.id

    daily = get_today_daily()

    if daily is None:
        # Генерируем daily на сегодня — случайное время, случайный тип
        tense_key = random.choice(list(TENSES.keys()))
        qtype = random.choice(["quiz", "find_error"])

        await query.edit_message_text("⏳ Генерирую вопрос дня...")

        if qtype == "find_error":
            data = generate_find_error(tense_key, user_id=user_id)
        else:
            data = generate_question(tense_key, user_id=user_id)

        if data is None:
            await query.edit_message_text(
                "😔 Не удалось сгенерировать вопрос дня. Попробуй позже.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
                ]),
            )
            return

        daily_id = save_daily_question(tense_key, qtype, data)
        daily = {"daily_id": daily_id, "tense_key": tense_key, "qtype": qtype, **data}

    # Проверяем: уже отвечал?
    if has_answered_daily(user_id, daily["daily_id"]):
        tense_name = TENSES.get(daily["tense_key"], {}).get("name", daily["tense_key"])
        # Считаем время до следующего daily (7:00 MSK)
        now = datetime.now(MSK)
        if now.hour < 7:
            next_daily = now.replace(hour=7, minute=0, second=0, microsecond=0)
        else:
            next_daily = (now + timedelta(days=1)).replace(hour=7, minute=0, second=0, microsecond=0)
        diff = next_daily - now
        hours_left = diff.seconds // 3600
        mins_left = (diff.seconds % 3600) // 60

        # Показываем вопрос + правильный ответ
        if daily.get("qtype") == "find_error":
            q_label = "🔍 Найди ошибку:"
        else:
            q_label = "❓ Вопрос:"

        explanation_fmt = _bold_tense_in_explanation(daily.get("explanation_ru", ""))

        await query.edit_message_text(
            f"📅 <b>Вопрос дня</b> ({tense_name})\n\n"
            f"{q_label}\n{daily['sentence']}\n\n"
            f"✅ Правильный ответ: <b>{daily['correct']}</b>\n"
            f"💡 {explanation_fmt}\n\n"
            f"✅ Ты уже ответил на вопрос дня!\n"
            f"⏰ Новый вопрос через {hours_left} ч. {mins_left} мин.\n"
            f"🔄 Обновление ежедневно в 7:00 МСК",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
            ]),
            parse_mode="HTML",
        )
        return

    # Показываем вопрос
    tense_name = TENSES.get(daily["tense_key"], {}).get("name", daily["tense_key"])
    options = daily["options"][:]
    random.shuffle(options)

    context.user_data["daily_id"] = daily["daily_id"]
    context.user_data["daily_correct"] = daily["correct"]
    context.user_data["daily_options"] = options
    context.user_data["daily_explanation"] = daily["explanation_ru"]
    context.user_data["daily_tense"] = daily["tense_key"]
    context.user_data["daily_qtype"] = daily["qtype"]

    keyboard = []
    for i, opt in enumerate(options):
        keyboard.append([InlineKeyboardButton(opt, callback_data=f"daily_ans_{i}")])
    keyboard.append([InlineKeyboardButton("⬅️ В меню", callback_data="main_menu")])

    if daily["qtype"] == "find_error":
        header = f"🔍 Найди ошибку ({tense_name})"
        sentence_prefix = "❌"
    else:
        header = f"❓ Вопрос ({tense_name})"
        sentence_prefix = ""

    await query.edit_message_text(
        f"📅 <b>Вопрос дня</b>\n{header}\n\n"
        f"{sentence_prefix} {daily['sentence']}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def handle_daily_answer(query, context, answer_index: int):
    options = context.user_data.get("daily_options", [])
    correct = context.user_data.get("daily_correct", "")
    explanation = context.user_data.get("daily_explanation", "")
    daily_id = context.user_data.get("daily_id")
    tense_key = context.user_data.get("daily_tense", "present_simple")
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name or ""

    if answer_index >= len(options):
        return

    chosen = options[answer_index]
    is_correct = chosen == correct

    # Сохраняем ответ + streak
    save_daily_answer(user_id, daily_id, is_correct)
    save_quiz_result(user_id, tense_key, int(is_correct), 1)
    update_streak(user_id, username)

    if is_correct:
        explanation_fmt = _bold_tense_in_explanation(explanation)
        text = f"📅 <b>Вопрос дня</b>\n\n✅ Правильно! Ответ: {correct}\n\n💡 {explanation_fmt}"
    else:
        explanation_fmt = _bold_tense_in_explanation(explanation)
        text = (
            f"📅 <b>Вопрос дня</b>\n\n"
            f"❌ Неправильно!\n\n"
            f"Твой ответ: {chosen}\n"
            f"Правильный: {correct}\n\n"
            f"💡 {explanation_fmt}"
        )

    # Streak
    if _is_new_day_streak(context):
        current, best = get_streak(user_id)
        text += f"\n\n🔥 Streak: {current} дн.!"

    keyboard = [
        [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ── Информация ──────────────────────────────────────

async def show_info(query, context):
    text = (
        "ℹ️ <b>Информация</b>\n\n"

        "🏅 <b>Ранги</b>\n"
        "Ранг зависит от общего % правильных ответов:\n"
        "🌱 Новичок — ещё нет ответов\n"
        "📗 Начинающий — менее 50%\n"
        "📘 Средний — 50–74%\n"
        "📙 Продвинутый — 75–89%\n"
        "📕 Мастер — 90% и выше\n\n"

        "📊 <b>Цвета в профиле</b>\n"
        "Показывают результат по каждому времени:\n"
        "🟩 Зелёный — 70% и выше\n"
        "🟨 Жёлтый — 40–69%\n"
        "🟥 Красный — менее 40%\n"
        "Статистика считается за всё время.\n\n"

        "📅 <b>Вопрос дня (Daily)</b>\n"
        "Новый вопрос каждый день в 07:00 МСК.\n"
        "Один вопрос — общий для всех.\n\n"

        "🔥 <b>Streak</b>\n"
        "Серия дней подряд с активностью.\n"
        "Учебный день начинается в 07:00 МСК.\n"
        "Пройди хотя бы 1 тест или ответь на daily.\n\n"

        "📦 <b>Обучение (Лейтнер)</b>\n"
        "Система интервального повторения:\n"
        "Коробка 1 🔴 — повторение сразу\n"
        "Коробка 2 🟠 — через 1 день\n"
        "Коробка 3 🟡 — через 3 дня\n"
        "Коробка 4 🟢 — через 7 дней\n"
        "Коробка 5 ✅ — через 14 дней (выучено)\n\n"
        "📏 <b>Как продвигаться:</b>\n"
        "• Сессия засчитана при ≥80% (4/5 правильно)\n"
        "• 3 засчитанных сессии → следующая коробка\n"
        "• Сессия <80% → возврат в коробку 1\n"
        "• Повторение доступно только когда пришёл срок\n"
        "• Минимум 11 дней до коробки 5 (1+3+7)"
    )

    keyboard = [[InlineKeyboardButton("⬅️ В меню", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ── Обучение (Лейтнер) ──────────────────────────────

LEARN_QUESTIONS = 5  # Вопросов за сессию обучения

# Эмодзи для коробок Лейтнера
_BOX_EMOJI = {1: "🔴", 2: "🟠", 3: "🟡", 4: "🟢", 5: "✅"}
_BOX_LABEL = {1: "Новое", 2: "Повтор", 3: "Знакомое", 4: "Уверенно", 5: "Выучено"}


async def show_learn_menu(query, context):
    """Главное меню обучения с прогрессом по временам."""
    user_id = query.from_user.id
    progress = get_leitner_progress(user_id)
    stats = get_leitner_stats(user_id)
    due = get_due_tenses(user_id)

    # Если нет прогресса — первый вход, показываем приветствие
    if not progress:
        text = (
            "🎓 <b>Обучение</b>\n\n"
            "Здесь ты будешь изучать времена по системе интервального повторения.\n\n"
            "📦 Каждое время начинает в коробке 1 (новое).\n"
            "✅ 3 правильных ответа подряд → следующая коробка.\n"
            "❌ Ошибка → возврат в коробку 1.\n"
            "🔄 Чем выше коробка, тем реже повторение.\n\n"
            "Выбери время для начала:"
        )
    else:
        due_text = f"🔔 Пора повторить: {len(due)}" if due else "✅ Всё повторено на сегодня!"
        mastered = stats["boxes"].get(5, 0)
        text = (
            f"🎓 <b>Обучение</b>\n\n"
            f"📊 Изучено: {stats['total']}/12 времён\n"
            f"✅ Выучено (коробка 5): {mastered}\n"
            f"{due_text}\n"
        )

    keyboard = []

    # Кнопка "Что повторить?" если есть due
    if due:
        keyboard.append([InlineKeyboardButton(f"🔄 Повторить ({len(due)})", callback_data="learn_review")])

    # Список времён с прогрессом
    for group_name, tense_keys in TENSE_GROUPS.items():
        row = []
        for t_key in tense_keys:
            t_name = TENSES[t_key]["name"].replace(" Perfect Continuous", " PC").replace(" Continuous", " Cont.").replace(" Perfect", " Perf.")
            if t_key in progress:
                box = progress[t_key]["box"]
                emoji = _BOX_EMOJI.get(box, "⬜")
            else:
                emoji = "⬜"
            row.append(InlineKeyboardButton(f"{emoji} {t_name}", callback_data=f"learn_{t_key}"))
        keyboard.append(row)

    keyboard.append([InlineKeyboardButton("⬅️ В меню", callback_data="main_menu")])

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def start_learn_session(query, context, tense_key: str):
    """Показывает теорию по времени (без инициализации Лейтнера — только при квизе)."""
    user_id = query.from_user.id
    progress = get_leitner_progress(user_id)
    p = progress.get(tense_key, {"box": 1, "correct_streak": 0})

    t = TENSES[tense_key]
    box = p["box"]
    streak = p["correct_streak"]
    emoji = _BOX_EMOJI.get(box, "⬜")
    label = _BOX_LABEL.get(box, "")

    text = (
        f"🎓 <b>{t['name']}</b>\n\n"
        f"📦 Коробка: {emoji} {box} ({label})\n"
        f"🎯 Прогресс: {streak}/3 правильных подряд\n\n"
        f"📐 <b>Формула:</b>\n{t['formula']}\n\n"
        f"🔑 <b>Маркеры:</b>\n{t['markers']}\n\n"
        f"💬 <b>Пример:</b>\n{t['example']}\n\n"
        f"📝 <b>Формы:</b>\n{t['forms']}\n\n"
        f"✏️ <b>Окончания:</b>\n{t['endings']}"
    )

    keyboard = [
        [InlineKeyboardButton("✍️ Практика: напиши предложение", callback_data=f"learn_prod_{tense_key}")],
        [InlineKeyboardButton("🎯 Начать квиз", callback_data=f"learn_quiz_{tense_key}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="learn_menu")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def start_learn_quiz(query, context, tense_key: str):
    """Запускает квиз в рамках обучения (5 вопросов)."""
    user_id = query.from_user.id
    init_leitner(user_id, tense_key)
    context.user_data["learn_tense"] = tense_key
    context.user_data["learn_score"] = 0
    context.user_data["learn_q_num"] = 0
    context.user_data["learn_results"] = []  # список True/False
    await send_learn_question(query, context)


async def send_learn_question(query, context):
    q_num = context.user_data["learn_q_num"]
    is_final = context.user_data.get("learn_is_final", False)
    total = FINAL_TEST_QUESTIONS if is_final else LEARN_QUESTIONS

    if q_num >= total:
        if is_final:
            await show_learn_final_results(query, context)
        else:
            await show_learn_results(query, context)
        return

    tense_key = context.user_data["learn_tense"]
    user_id = query.from_user.id
    mode_label = "🏅 Финальный тест" if is_final else "🎓 Обучение"

    await query.edit_message_text(f"{mode_label} — Вопрос {q_num + 1}/{total}...")

    data = generate_question(tense_key, user_id=user_id)
    if data is None:
        await query.edit_message_text(
            "😔 Не удалось сгенерировать вопрос. Попробуй позже.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Повторить", callback_data="learn_next_q")],
                [InlineKeyboardButton("🎓 К обучению", callback_data="learn_menu")],
            ]),
        )
        return

    options = data["options"][:]
    random.shuffle(options)

    context.user_data["learn_correct"] = data["correct"]
    context.user_data["learn_options"] = options
    context.user_data["learn_explanation"] = data["explanation_ru"]
    context.user_data["learn_sentence"] = data["sentence"]

    keyboard = []
    for i, opt in enumerate(options):
        keyboard.append([InlineKeyboardButton(opt, callback_data=f"learn_ans_{i}")])
    # Подсказка только в обучении, не в финальном тесте
    if not is_final:
        keyboard.append([InlineKeyboardButton("💡 Подсказка", callback_data="learn_hint")])

    tense_name = TENSES[tense_key]["name"]
    await query.edit_message_text(
        f"{mode_label} — {tense_name}\n"
        f"Вопрос {q_num + 1}/{total}\n\n{data['sentence']}",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML",
    )


async def handle_learn_answer(query, context, answer_index: int):
    options = context.user_data.get("learn_options", [])
    correct = context.user_data.get("learn_correct", "")
    explanation = context.user_data.get("learn_explanation", "")
    tense_key = context.user_data.get("learn_tense", "present_simple")
    user_id = query.from_user.id
    is_final = context.user_data.get("learn_is_final", False)

    if answer_index >= len(options):
        return

    chosen = options[answer_index]
    is_correct = chosen == correct
    context.user_data["learn_q_num"] += 1
    context.user_data["learn_results"].append(is_correct)

    if is_correct:
        context.user_data["learn_score"] += 1

    total = FINAL_TEST_QUESTIONS if is_final else LEARN_QUESTIONS
    q_num = context.user_data["learn_q_num"]
    is_last = q_num >= total

    t = TENSES[tense_key]
    explanation_fmt = _bold_tense_in_explanation(explanation)
    if is_correct:
        text = f"✅ Правильно! Ответ: {correct}\n\n💡 {explanation_fmt}"
    else:
        text = (
            f"❌ Неправильно!\n\n"
            f"Твой ответ: {chosen}\n"
            f"Правильный: {correct}\n\n"
            f"💡 {explanation_fmt}\n\n"
            f"📐 <b>Напоминание:</b>\n"
            f"{t['formula']}\n"
            f"🔑 {t['markers']}"
        )

    # Показываем текущий прогресс коробки (только в обычном обучении, без обновления)
    if not is_final:
        progress = get_leitner_progress(user_id)
        p = progress.get(tense_key, {"box": 1, "correct_streak": 0})
        cur_score = context.user_data.get("learn_score", 0)
        emoji = _BOX_EMOJI.get(p["box"], "⬜")
        text += f"\n\n📦 Коробка {emoji}{p['box']} | Счёт: {cur_score}/{q_num}"

    if is_last:
        keyboard = [[InlineKeyboardButton("📊 Результаты", callback_data="learn_next_q")]]
    else:
        keyboard = [
            [InlineKeyboardButton("➡️ Следующий", callback_data="learn_next_q")],
            [InlineKeyboardButton("🚪 Завершить", callback_data="learn_finish")],
        ]

    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def show_learn_results(query, context):
    """Результаты сессии обучения."""
    score = context.user_data.get("learn_score", 0)
    tense_key = context.user_data.get("learn_tense", "present_simple")
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name or ""
    answered = context.user_data.get("learn_q_num", LEARN_QUESTIONS)

    # Сохраняем в общую статистику (реально отвеченные)
    save_quiz_result(user_id, tense_key, score, answered)
    update_streak(user_id, username)

    # Обновляем Лейтнер ПО ИТОГУ СЕССИИ (не за каждый ответ)
    box, streak = update_leitner_session(user_id, tense_key, score, answered)

    pct = round(score / answered * 100) if answered > 0 else 0
    tense_name = TENSES[tense_key]["name"]
    emoji = _BOX_EMOJI.get(box, "⬜")
    label = _BOX_LABEL.get(box, "")

    text = (
        f"🎓 <b>Результат — {tense_name}</b>\n\n"
        f"✅ {score}/{answered} ({pct}%)\n"
        f"📦 Коробка: {emoji} {box} ({label})\n"
        f"🎯 Серия: {streak}/3\n"
    )

    if box == 5:
        # Проверяем: сколько всего выучено
        all_p = get_leitner_progress(user_id)
        mastered_count = sum(1 for v in all_p.values() if v["box"] == 5)

        text += (
            "\n🎉🎉🎉 <b>Время выучено!</b>\n\n"
            f"🏆 {tense_name} в коробке 5 (выучено)!\n"
            f"📊 Выучено времён: {mastered_count}/12\n"
            "🔄 Повторение через 14 дней.\n\n"
            "Пройди финальный тест из 10 вопросов, чтобы подтвердить знания!"
        )
        keyboard = [
            [InlineKeyboardButton("🏅 Финальный тест (10 вопросов)", callback_data=f"learn_final_{tense_key}")],
            [InlineKeyboardButton("🎓 К обучению", callback_data="learn_menu")],
            [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
        ]
    else:
        if pct >= 60:
            text += "\n👍 Хороший результат! Продолжай в том же духе."
        else:
            text += "\n📖 Попробуй повторить теорию и пройти ещё раз."

        keyboard = [
            [InlineKeyboardButton("🔄 Ещё раз", callback_data=f"learn_quiz_{tense_key}")],
            [InlineKeyboardButton("🎓 К обучению", callback_data="learn_menu")],
            [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
        ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def start_learn_review(query, context):
    """Повторение — берёт первое время из due-списка."""
    user_id = query.from_user.id
    due = get_due_tenses(user_id)

    if not due:
        await query.edit_message_text(
            "🎓 <b>Повторение</b>\n\n"
            "✅ Всё повторено! Возвращайся позже.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🎓 К обучению", callback_data="learn_menu")],
            ]),
            parse_mode="HTML",
        )
        return

    # Берём первое время (самая низкая коробка, самый ранний срок)
    tense_key = due[0]
    await start_learn_session(query, context, tense_key)


FINAL_TEST_QUESTIONS = 10  # Финальный тест — 10 вопросов


async def start_learn_final(query, context, tense_key: str):
    """Запускает финальный тест (10 вопросов) для подтверждения выученного времени."""
    user_id = query.from_user.id
    context.user_data["learn_tense"] = tense_key
    context.user_data["learn_score"] = 0
    context.user_data["learn_q_num"] = 0
    context.user_data["learn_results"] = []
    context.user_data["learn_is_final"] = True
    await send_learn_question(query, context)


async def show_learn_final_results(query, context):
    """Результаты финального теста."""
    score = context.user_data.get("learn_score", 0)
    tense_key = context.user_data.get("learn_tense", "present_simple")
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name or ""

    total = FINAL_TEST_QUESTIONS
    save_quiz_result(user_id, tense_key, score, total)
    update_streak(user_id, username)

    pct = round(score / total * 100)
    tense_name = TENSES[tense_key]["name"]

    if pct >= 80:
        text = (
            f"🏅 <b>Финальный тест — {tense_name}</b>\n\n"
            f"✅ {score}/{total} ({pct}%)\n\n"
            f"🎉 Великолепно! Ты подтвердил знание {tense_name}!\n"
            "Это время полностью в твоём арсенале! 💪"
        )
    elif pct >= 60:
        text = (
            f"🏅 <b>Финальный тест — {tense_name}</b>\n\n"
            f"✅ {score}/{total} ({pct}%)\n\n"
            "👍 Неплохо, но есть над чем поработать.\n"
            "Попробуй повторить теорию и пройти финальный тест снова."
        )
    else:
        text = (
            f"🏅 <b>Финальный тест — {tense_name}</b>\n\n"
            f"✅ {score}/{total} ({pct}%)\n\n"
            "📖 Стоит вернуться к теории и попрактиковаться.\n"
            "Не сдавайся — повторение путь к успеху!"
        )

    keyboard = [
        [InlineKeyboardButton("🔄 Пройти снова", callback_data=f"learn_final_{tense_key}")],
        [InlineKeyboardButton("🎓 К обучению", callback_data="learn_menu")],
        [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
    ]
    context.user_data.pop("learn_is_final", None)
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def start_learn_production(query, context, tense_key: str):
    """Мини-задание: напиши предложение в рамках обучения."""
    context.user_data["learn_prod_tense"] = tense_key
    context.user_data["awaiting_learn_sentence"] = True

    t = TENSES[tense_key]
    text = (
        f"✍️ <b>Мини-задание — {t['name']}</b>\n\n"
        f"Напиши предложение, используя <b>{t['name']}</b>.\n\n"
        f"📐 Формула: {t['formula']}\n"
        f"🔑 Маркеры: {t['markers']}\n\n"
        "Просто напиши предложение на английском в чат!"
    )
    keyboard = [
        [InlineKeyboardButton("⏭ Пропустить → квиз", callback_data=f"learn_quiz_{tense_key}")],
        [InlineKeyboardButton("⬅️ К теории", callback_data=f"learn_{tense_key}")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


async def handle_learn_sentence(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка предложения, написанного в рамках обучения."""
    if not context.user_data.get("awaiting_learn_sentence"):
        return False  # Не наш обработчик

    context.user_data["awaiting_learn_sentence"] = False
    tense_key = context.user_data.get("learn_prod_tense", "present_simple")
    tense_name = TENSES[tense_key]["name"]
    user_text = update.message.text.strip()

    await update.message.reply_text("⏳ Проверяю твоё предложение...")

    result = check_sentence(tense_key, user_text)

    if result is None:
        keyboard = [
            [InlineKeyboardButton("✍️ Попробовать ещё", callback_data=f"learn_prod_{tense_key}")],
            [InlineKeyboardButton("⏭ К квизу", callback_data=f"learn_quiz_{tense_key}")],
        ]
        await update.message.reply_text(
            "😔 Не удалось проверить. Попробуй ещё раз.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return True

    is_correct = result.get("is_correct", False)
    corrected = result.get("corrected", "")
    feedback = result.get("feedback_ru", "")

    save_production_result(update.effective_user.id, tense_key, is_correct)

    if is_correct:
        text = (
            f"✅ Отлично! Правильно — <b>{tense_name}</b>\n\n"
            f"Твоё предложение: {user_text}\n\n"
            f"💡 {feedback}\n\n"
            "Теперь переходи к квизу!"
        )
    else:
        text = (
            f"❌ Не совсем верно\n\n"
            f"Твоё: {user_text}\n"
            f"Исправленное: {corrected}\n\n"
            f"💡 {feedback}\n\n"
            "Попробуй ещё раз или переходи к квизу."
        )

    keyboard = [
        [InlineKeyboardButton("✍️ Написать ещё", callback_data=f"learn_prod_{tense_key}")],
        [InlineKeyboardButton("🎯 Начать квиз", callback_data=f"learn_quiz_{tense_key}")],
        [InlineKeyboardButton("⬅️ К теории", callback_data=f"learn_{tense_key}")],
    ]
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    return True


async def show_learn_hint(query, context):
    """Показывает подсказку (формулу + маркеры + пример) во время квиза обучения."""
    tense_key = context.user_data.get("learn_tense", "present_simple")
    t = TENSES[tense_key]

    text = (
        f"💡 <b>Подсказка — {t['name']}</b>\n\n"
        f"📐 <b>Формула:</b> {t['formula']}\n"
        f"🔑 <b>Маркеры:</b> {t['markers']}\n"
        f"💬 <b>Пример:</b> {t['example']}\n\n"
        "Вернись к вопросу и выбери ответ."
    )

    keyboard = [[InlineKeyboardButton("⬅️ К вопросу", callback_data="learn_back_to_q")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")


# ── Главный роутер callback-ов ──────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await show_main_menu(query, context)

    elif data == "practice":
        await show_groups(query, context)

    elif data == "tenses_menu":
        await show_tenses_menu(query, context)

    elif data == "random_info":
        await show_random_info(query, context)

    elif data.startswith("group_"):
        group = data.replace("group_", "")
        await show_tenses_in_group(query, group)

    elif data.startswith("tense_"):
        tense_key = data.replace("tense_", "")
        await show_theory(query, tense_key)

    elif data.startswith("quiz_"):
        tense_key = data.replace("quiz_", "")
        await start_quiz(query, context, tense_key)

    elif data == "random":
        await start_random_quiz(query, context)

    elif data.startswith("answer_"):
        idx = int(data.replace("answer_", ""))
        await handle_answer(query, context, idx)

    elif data == "next_question":
        if "question_num" not in context.user_data:
            await show_main_menu(query, context)
            return
        await send_question(query, context)

    elif data == "production_menu":
        await show_production_menu(query, context)

    elif data.startswith("prod_"):
        tense_key = data.replace("prod_", "")
        await start_production(query, context, tense_key)

    elif data == "finish_quiz":
        await confirm_finish(query, context)

    elif data == "finish_save":
        await finish_save(query, context)

    elif data == "finish_reset":
        await finish_reset(query, context)

    elif data == "try_again":
        tense_key = context.user_data.get("current_tense", "random")
        await start_quiz(query, context, tense_key)

    elif data == "profile":
        await show_profile(query, context)

    elif data == "leaderboard":
        await show_leaderboard(query, context)

    elif data.startswith("lb_"):
        group = data.replace("lb_", "")
        await show_leaderboard(query, context, group=group)

    elif data == "find_error_menu":
        await show_find_error_menu(query, context)

    elif data.startswith("fe_ans_"):
        if "fe_correct" not in context.user_data:
            await show_find_error_menu(query, context)
            return
        idx = int(data.replace("fe_ans_", ""))
        await handle_find_error_answer(query, context, idx)

    elif data.startswith("fe_"):
        tense_key = data.replace("fe_", "")
        await send_find_error(query, context, tense_key)

    elif data == "daily":
        await show_daily(query, context)

    elif data.startswith("daily_ans_"):
        idx = int(data.replace("daily_ans_", ""))
        await handle_daily_answer(query, context, idx)

    elif data == "learn_menu":
        await show_learn_menu(query, context)

    elif data == "learn_review":
        await start_learn_review(query, context)

    elif data.startswith("learn_final_"):
        tense_key = data.replace("learn_final_", "")
        await start_learn_final(query, context, tense_key)

    elif data.startswith("learn_prod_"):
        tense_key = data.replace("learn_prod_", "")
        await start_learn_production(query, context, tense_key)

    elif data.startswith("learn_quiz_"):
        tense_key = data.replace("learn_quiz_", "")
        await start_learn_quiz(query, context, tense_key)

    elif data.startswith("learn_ans_"):
        if "learn_q_num" not in context.user_data:
            await show_learn_menu(query, context)
            return
        idx = int(data.replace("learn_ans_", ""))
        await handle_learn_answer(query, context, idx)

    elif data == "learn_hint":
        if "learn_q_num" not in context.user_data:
            await show_learn_menu(query, context)
            return
        await show_learn_hint(query, context)

    elif data == "learn_back_to_q":
        if "learn_q_num" not in context.user_data or "learn_sentence" not in context.user_data:
            await show_learn_menu(query, context)
            return
        # Восстанавливаем вопрос из контекста
        tense_key = context.user_data.get("learn_tense", "present_simple")
        q_num = context.user_data["learn_q_num"]
        is_final = context.user_data.get("learn_is_final", False)
        total = FINAL_TEST_QUESTIONS if is_final else LEARN_QUESTIONS
        options = context.user_data.get("learn_options", [])
        sentence = context.user_data.get("learn_sentence", "")
        mode_label = "🏅 Финальный тест" if is_final else "🎓 Обучение"
        tense_name = TENSES[tense_key]["name"]

        keyboard = []
        for i, opt in enumerate(options):
            keyboard.append([InlineKeyboardButton(opt, callback_data=f"learn_ans_{i}")])
        if not is_final:
            keyboard.append([InlineKeyboardButton("💡 Подсказка", callback_data="learn_hint")])

        await query.edit_message_text(
            f"{mode_label} — {tense_name}\n"
            f"Вопрос {q_num + 1}/{total}\n\n{sentence}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )

    elif data == "learn_next_q":
        if "learn_q_num" not in context.user_data:
            await show_learn_menu(query, context)
            return
        await send_learn_question(query, context)

    elif data == "learn_finish":
        if "learn_q_num" not in context.user_data:
            await show_learn_menu(query, context)
            return
        is_final = context.user_data.get("learn_is_final", False)
        if is_final:
            await show_learn_final_results(query, context)
        else:
            await show_learn_results(query, context)

    elif data.startswith("learn_"):
        tense_key = data.replace("learn_", "")
        if tense_key in TENSES:
            await start_learn_session(query, context, tense_key)

    elif data == "cheatsheet":
        await show_cheatsheet(query)

    elif data == "irreg_verbs":
        await show_irreg_verbs_menu(query)

    elif data.startswith("irreg_"):
        # irreg_abc_0, irreg_abb_1, etc.
        parts = data.split("_")
        if len(parts) == 3:
            group_key = parts[1]
            page = int(parts[2])
            await show_irreg_verbs_group(query, group_key, page)
        else:
            await show_irreg_verbs_menu(query)

    elif data == "info":
        await show_info(query, context)

    elif data == "streak":
        await show_streak(query)
