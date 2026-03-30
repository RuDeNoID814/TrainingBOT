import os

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# ID администратора для получения уведомлений об ошибках
_admin = os.getenv("ADMIN_ID", "")
ADMIN_ID = int(_admin) if _admin.isdigit() else None