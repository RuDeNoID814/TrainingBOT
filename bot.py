import loggingа
import os

from telegram.ext import Application, CommandHandler, CallbackQueryHandler

from config import TELEGRAM_TOKEN
from database import init_db
from handlers import start, button_handler

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

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Бот запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()
