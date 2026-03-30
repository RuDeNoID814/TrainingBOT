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

    # Прокси подхватывается из окружения (Hiddify и т.д.)
    # На хостинге переменных нет → прокси не используется
    proxy_url = os.getenv("https_proxy") or os.getenv("HTTPS_PROXY")

    builder = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
    )

    if proxy_url:
        logger.info("Используется прокси: %s", proxy_url)
        builder = builder.proxy(proxy_url).get_updates_proxy(proxy_url)
    else:
        logger.info("Прокси не обнаружен, прямое подключение")

    app = builder.build()

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
        # Игнорируем "Message is not modified" (двойной клик на кнопку)
        if isinstance(context.error, BadRequest):
            if "Message is not modified" in str(context.error):
                return
            if "Query is too old" in str(context.error):
                return

        # Сетевые ошибки — только логируем
        if isinstance(context.error, NetworkError):
            logger.warning("Сетевая ошибка (прокси/интернет): %s", context.error)
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

    app.add_handler(CommandHandler("start", start))
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
