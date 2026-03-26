import logging
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from tenses import TENSES, TENSE_GROUPS
from gemini_api import generate_question
from database import get_streak, update_streak

logger = logging.getLogger(__name__)

QUESTIONS_PER_SESSION = 10

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
        [InlineKeyboardButton("📚 Практика", callback_data="practice"),
         InlineKeyboardButton("🎲 Рандом", callback_data="random")],
        [InlineKeyboardButton("📋 Шпаргалка", callback_data="cheatsheet"),
         InlineKeyboardButton("🔥 Мой streak", callback_data="streak")],
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
        [InlineKeyboardButton("📚 Практика", callback_data="practice"),
         InlineKeyboardButton("🎲 Рандом", callback_data="random")],
        [InlineKeyboardButton("📋 Шпаргалка", callback_data="cheatsheet"),
         InlineKeyboardButton("🔥 Мой streak", callback_data="streak")],
    ]

    await query.edit_message_text(
        f"Главное меню\n{streak_line}\n\nВыбери, что хочешь сделать:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Выбор группы времён ────────────────────────────────

async def show_groups(query, context):
    keyboard = [
        [InlineKeyboardButton("Present", callback_data="group_present")],
        [InlineKeyboardButton("Past", callback_data="group_past")],
        [InlineKeyboardButton("Future", callback_data="group_future")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="main_menu")],
    ]
    await query.edit_message_text(
        "Choose a tense group:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Выбор конкретного времени ───────────────────────────

async def show_tenses_in_group(query, group_key: str):
    tenses_list = TENSE_GROUPS[group_key]
    keyboard = []
    for t_key in tenses_list:
        name = TENSES[t_key]["name"]
        keyboard.append([InlineKeyboardButton(name, callback_data=f"tense_{t_key}")])
    keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="practice")])

    await query.edit_message_text(
        "Choose a tense:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# ── Карточка теории ─────────────────────────────────────

async def show_theory(query, tense_key: str):
    t = TENSES[tense_key]
    text = (
        f"📖 {t['name']}\n\n"
        f"📐 Формула: {t['formula']}\n\n"
        f"🔑 Маркеры: {t['markers']}\n\n"
        f"💬 Пример: {t['example']}\n\n"
        f"📝 Формы:\n{t['forms']}"
    )
    keyboard = [
        [InlineKeyboardButton("🎯 Начать тест", callback_data=f"quiz_{tense_key}")],
        [InlineKeyboardButton("⬅️ Назад", callback_data="practice")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


# ── Квиз: запуск и отправка вопроса ────────────────────

async def start_quiz(query, context, tense_key: str):
    context.user_data["current_tense"] = tense_key
    context.user_data["score"] = 0
    context.user_data["question_num"] = 0
    await send_question(query, context)


async def start_random_quiz(query, context):
    context.user_data["current_tense"] = "random"
    context.user_data["score"] = 0
    context.user_data["question_num"] = 0
    await send_question(query, context)


async def send_question(query, context):
    q_num = context.user_data["question_num"]

    if q_num >= QUESTIONS_PER_SESSION:
        await show_results(query, context)
        return

    tense_key = context.user_data["current_tense"]
    if tense_key == "random":
        tense_key = random.choice(list(TENSES.keys()))

    await query.edit_message_text(f"⏳ Генерирую вопрос {q_num + 1}/{QUESTIONS_PER_SESSION}...")

    data = generate_question(tense_key)
    if data is None:
        await query.edit_message_text(
            "😔 Не удалось сгенерировать вопрос. Попробуй ещё раз.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Повторить", callback_data="next_question")],
                [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
            ]),
        )
        return

    options = data["options"][:]
    random.shuffle(options)

    context.user_data["correct_answer"] = data["correct"]
    context.user_data["shuffled_options"] = options
    context.user_data["explanation_ru"] = data["explanation_ru"]

    keyboard = []
    for i, opt in enumerate(options):
        keyboard.append([InlineKeyboardButton(opt, callback_data=f"answer_{i}")])

    await query.edit_message_text(
        f"❓ Вопрос {q_num + 1}/{QUESTIONS_PER_SESSION}\n\n{data['sentence']}",
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
    is_last = q_num >= QUESTIONS_PER_SESSION

    if chosen == correct:
        context.user_data["score"] += 1
        text = f"✅ Правильно! Ответ: {correct}"
    else:
        # Выделяем название времени жирным в объяснении
        explanation_fmt = _bold_tense_in_explanation(explanation)
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
    answered = context.user_data.get("question_num", QUESTIONS_PER_SESSION)
    user_id = query.from_user.id
    current, best = update_streak(user_id)

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

    text = (
        f"{emoji} Результат: {score}/{answered}\n\n"
        f"{comment}\n\n"
        f"🔥 Streak: {current} дн. (лучший: {best})"
    )

    keyboard = [
        [InlineKeyboardButton("🔄 Ещё раз", callback_data="try_again")],
        [InlineKeyboardButton("🏠 В меню", callback_data="main_menu")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


# ── Досрочное завершение теста ─────────────────────────

async def confirm_finish(query, context):
    score = context.user_data.get("score", 0)
    q_num = context.user_data.get("question_num", 0)

    text = (
        f"Ты ответил на {q_num} из {QUESTIONS_PER_SESSION} вопросов.\n"
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


# ── Шпаргалка ──────────────────────────────────────────

async def show_cheatsheet(query):
    lines = ["📋 Шпаргалка — все 12 времён\n"]
    for key, t in TENSES.items():
        lines.append(f"▪️ {t['name']}\n   {t['formula']}\n   {t['example']}\n")
    text = "\n".join(lines)

    keyboard = [[InlineKeyboardButton("⬅️ В меню", callback_data="main_menu")]]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


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


# ── Главный роутер callback-ов ──────────────────────────

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "main_menu":
        await show_main_menu(query, context)

    elif data == "practice":
        await show_groups(query, context)

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

    elif data == "finish_quiz":
        await confirm_finish(query, context)

    elif data == "finish_save":
        await finish_save(query, context)

    elif data == "finish_reset":
        await finish_reset(query, context)

    elif data == "try_again":
        tense_key = context.user_data.get("current_tense", "random")
        await start_quiz(query, context, tense_key)

    elif data == "cheatsheet":
        await show_cheatsheet(query)

    elif data == "streak":
        await show_streak(query)
