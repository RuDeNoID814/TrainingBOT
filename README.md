# Tense Trainer Bot

Telegram-бот для изучения 12 английских времён с помощью AI-генерируемых квизов.

## Возможности

- 12 английских времён с теорией на русском языке
- AI-генерация вопросов через Gemini API (каждый раз уникальные)
- Режимы: практика по конкретному времени или рандом
- Шпаргалка по всем временам
- Streak-система (отслеживание ежедневных занятий)
- Досрочное завершение теста с сохранением/сбросом результата

## Стек

- Python 3.12+
- python-telegram-bot
- Google Gemini API (gemini-2.5-flash)
- SQLite (streak, статистика)

## Установка

```bash
git clone <repo-url>
cd TrainingBot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Настройка

Создай файл `.env` в корне проекта:

```env
TELEGRAM_TOKEN=your_telegram_bot_token
GEMINI_API_KEY=your_gemini_api_key
```

Для работы через прокси (если Telegram/Google заблокированы):

```env
HTTPS_PROXY=http://127.0.0.1:12334
```

## Запуск

```bash
python bot.py
```

## Структура проекта

```
bot.py              — точка входа, настройка Application
config.py           — загрузка переменных окружения
handlers.py         — обработчики команд и callback-кнопок
gemini_api.py       — генерация вопросов через Gemini
tenses.py           — данные по 12 временам (теория, формулы, примеры)
prompts/            — промпты для Gemini API
database.py         — SQLite: streak-система
requirements.txt    — зависимости
```
