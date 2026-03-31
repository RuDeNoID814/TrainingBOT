import logging
import os
import traceback

from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from telegram.error import NetworkError, BadRequest

from dotenv import load_dotenv
load_dotenv()

from config import TELEGRAM_TOKEN, ADMIN_ID
from database import init_db
from handlers import start, button_handler, handle_user_sentence

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    # Диагностика переменных окружения
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не найден! Проверьте переменные окружения.")
        logger.error("Доступные переменные: %s", [k for k in os.environ if 'TOKEN' in k.upper() or 'BOT' in k.upper() or 'TELEGRAM' in k.upper()])
        return

    init_db()
    from database import DB_PATH as _db_path
    logger.info("БД: %s (exists=%s)", os.path.abspath(_db_path), os.path.exists(_db_path))

    # Прокси подхватывается из окружения (Hiddify и т.д.)
    # На хостинге переменных нет → прокси не используется
    proxy_url = os.getenv("https_proxy") or os.getenv("HTTPS_PROXY")

    builder = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .connect_timeout(15)
        .read_timeout(15)
        .write_timeout(15)
        .pool_timeout(10)
    )

    if proxy_url:
        logger.info("Используется прокси: %s", proxy_url)
        builder = builder.proxy(proxy_url).get_updates_proxy(proxy_url)
    else:
        logger.info("Прокси не обнаружен, прямое подключение")

    app = builder.build()

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        err_str = str(context.error)

        # Conflict — два инстанса бота, тихо игнорируем
        if "Conflict" in type(context.error).__name__ or "terminated by other getUpdates" in err_str:
            return

        # Игнорируем "Message is not modified" (двойной клик на кнопку)
        if isinstance(context.error, BadRequest):
            if "Message is not modified" in err_str:
                return
            if "Query is too old" in err_str:
                return

        # Сетевые ошибки — только логируем
        if isinstance(context.error, NetworkError):
            logger.warning("Сетевая ошибка: %s", context.error)
            return

        logger.error("Необработанная ошибка: %s", context.error, exc_info=context.error)

        # Отправляем ошибку админу в Telegram
        if ADMIN_ID:
            try:
                tb = traceback.format_exception(type(context.error), context.error, context.error.__traceback__)
                tb_text = "".join(tb)[-3000:]  # Последние 3000 символов трейсбека

                user_info = ""
                if isinstance(update, Update) and update.effective_user:
                    u = update.effective_user
                    user_info = f"User: {u.id} (@{u.username or u.first_name})\n"

                msg = (
                    f"⚠️ <b>Ошибка в боте</b>\n\n"
                    f"{user_info}"
                    f"<pre>{tb_text[:3500]}</pre>"
                )
                await context.bot.send_message(ADMIN_ID, msg[:4096], parse_mode="HTML")
            except Exception:
                logger.error("Не удалось отправить ошибку админу")

    # Единая админ-команда /bd
    async def admin_bd(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
            return
        from database import DB_PATH, clear_all_stats

        args = context.args[0] if context.args else ""

        if args == "download":
            if os.path.exists(DB_PATH):
                await update.message.reply_document(document=open(DB_PATH, "rb"), filename="bot.db")
            else:
                await update.message.reply_text("БД не найдена")

        elif args == "reset":
            if os.path.exists(DB_PATH):
                os.remove(DB_PATH)
                for ext in ("-wal", "-shm"):
                    p = DB_PATH + ext
                    if os.path.exists(p):
                        os.remove(p)
            init_db()
            await update.message.reply_text("🗑 БД полностью сброшена и пересоздана.")

        elif args == "clear":
            clear_all_stats()
            await update.message.reply_text("📊 Статистика сброшена. Вопросы сохранены.")

        elif args == "path":
            exists = os.path.exists(DB_PATH)
            size = os.path.getsize(DB_PATH) if exists else 0
            await update.message.reply_text(f"📂 Путь: <code>{DB_PATH}</code>\nСуществует: {exists}\nРазмер: {size} байт", parse_mode="HTML")

        else:
            await update.message.reply_text(
                "🛠 <b>Команды БД:</b>\n\n"
                "/bd download — скачать БД\n"
                "/bd clear — сброс статистики (вопросы останутся)\n"
                "/bd reset — полный сброс БД\n"
                "/bd path — путь и размер БД",
                parse_mode="HTML",
            )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("bd", admin_bd))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_user_sentence))
    app.add_error_handler(error_handler)

    logger.info("Бот запущен!")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query"],
    )


if __name__ == "__main__":
    main()
