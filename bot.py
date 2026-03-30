import logging
import os

from telegram import Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
from telegram.error import NetworkError

from config import TELEGRAM_TOKEN
from database import init_db
from handlers import start, button_handler, handle_user_sentence

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
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
        if isinstance(context.error, NetworkError):
            logger.warning("Сетевая ошибка (прокси/интернет): %s", context.error)
            return
        logger.error("Необработанная ошибка: %s", context.error, exc_info=context.error)

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
