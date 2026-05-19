# Tense Trainer Bot

Telegram-бот для изучения 12 английских времён. Вопросы генерирует AI через OpenRouter,
прогресс хранится в SQLite. Деплой на Bothost.ru.

---

## Стек

| Слой | Что используется | Где |
|------|-----------------|-----|
| Язык | Python 3.14 | — |
| Telegram | python-telegram-bot v22 | `bot.py`, `handlers.py` |
| HTTP (AI) | httpx (sync) | `gemini_api.py` |
| AI | OpenRouter API → Gemini 2.0/2.5 Flash | `gemini_api.py` |
| БД | SQLite + WAL mode (stdlib sqlite3) | `database.py` |
| Env | python-dotenv | `config.py` |
| Хостинг | Bothost.ru (git push = деплой) | `Procfile`, `runtime.txt` |

---

## Структура файлов

```
bot.py              — точка входа: регистрация хендлеров, прокси, error handler, admin /bd
config.py           — читает .env: TELEGRAM_TOKEN, OPENROUTER_API_KEY, ADMIN_ID
handlers.py         — вся логика бота: 20+ экранов, меню, квизы, обучение, daily
gemini_api.py       — OpenRouter API: генерация вопросов, проверка предложений, fallback-цепочка
database.py         — SQLite: 9 таблиц, весь доступ к данным
tenses.py           — данные 12 времён (name, formula, markers, example, forms, endings)
irregular_verbs.py  — 85 неправильных глаголов в 4 группах (ABC, ABB, ABA, AAA)
prompts/            — промпт-шаблоны для AI (quiz, find_error, check_sentence)
data/bot.db         — SQLite-файл (в git, можно скачать /bd download)
```

---

## Модули — что где используется

### `bot.py` — точка входа
- Регистрирует хендлеры: `CommandHandler("start")`, `CallbackQueryHandler`, `MessageHandler`
- Подхватывает прокси из `HTTPS_PROXY` / `https_proxy` (для локальной разработки)
- `error_handler` — ловит все необработанные исключения, шлёт traceback админу в TG
- Команда `/bd` (только для `ADMIN_ID`): download / clear / reset / path

### `config.py` — переменные окружения
Пробует несколько имён переменной для токена: `TELEGRAM_TOKEN`, `BOT_TOKEN`,
`TELEGRAM_BOT_TOKEN`, `TOKEN`.

### `handlers.py` — вся логика интерфейса
Один большой файл (~1700 строк). Содержит:

| Функция / блок | Что делает |
|----------------|-----------|
| `_build_menu_text_and_keyboard` | Главное меню: новый юзер → инструкция, вернувшийся → streak + Leitner + подсказка |
| `show_groups` / `show_tenses_menu` | Меню Практики: режимы (Времена / Рандом / Найди ошибку / Напиши) |
| `show_theory` | Карточка теории: формула, маркеры, пример, формы, окончания |
| `start_quiz` / `send_question` / `show_results` | Квиз на конкретное время (10 вопросов) |
| `start_random_quiz` | Рандом — 12 вопросов, по одному на каждое время |
| `start_quick_training` | Быстрая тренировка — 5 случайных вопросов (~3 мин) |
| `show_daily` / `handle_daily_answer` | Daily: один вопрос на всех, генерируется раз в день |
| `show_learn_menu` / `start_learn_session` | Обучение: теория + производство + квиз с подсказками |
| `send_learn_question` / `handle_learn_answer` | Квиз обучения; подсказка убирается в финальном тесте |
| `start_learn_final` / `show_learn_final_results` | Финальный тест (10 вопросов, без подсказок) при Box 5 |
| `start_learn_production` / `handle_learn_sentence` | Мини-задание: написать предложение в рамках обучения |
| `show_production_menu` / `start_production` | Режим «Напиши предложение» из Практики |
| `show_cheatsheet` | Шпаргалка: 12 времён + 85 неправильных глаголов |
| `show_info` | Экран «Инфо» |
| `_sync_quiz_to_db` / `_restore_quiz_from_db` | Сохранение сессии квиза в БД (переживает перезапуск) |

**Количество вопросов:**
- Обычный квиз: `QUESTIONS_PER_SESSION = 10`
- Рандом: `RANDOM_QUESTIONS = 12`
- Быстрая тренировка: `QUICK_QUESTIONS = 5`

### `gemini_api.py` — AI-генерация
**Модели (fallback-цепочка):**
1. `google/gemini-2.0-flash-001`
2. `google/gemini-2.5-flash-preview`
3. `google/gemini-2.0-flash-lite-001`
4. `google/gemini-flash-1.5-8b`

При 429 модель блокируется на **1 час** (`COOLDOWN_SEC = 3600`), следующая в списке.

**Три типа генерации:**

| Функция | Назначение | Кэш в БД |
|---------|-----------|----------|
| `generate_question` | Квиз: предложение с пропуском + 4 варианта | ✅ `qtype='quiz'` |
| `generate_find_error` | Найди ошибку: предложение с ошибкой + 4 варианта | ✅ `qtype='find_error'` |
| `check_sentence` | Проверяет предложение пользователя | ❌ |

**Кэш:** если AI недоступен — берётся случайный невиданный вопрос из `question_cache`.
Каждый показанный вопрос помечается в `user_seen_questions` (дедупликация per-user).

### `database.py` — вся работа с данными

**9 таблиц:**

| Таблица | Что хранит |
|---------|-----------|
| `users` | user_id, username, display_name, current_streak, best_streak, last_practice_date |
| `quiz_results` | Результаты тестов (user_id, tense_key, score, total) |
| `production_results` | Результаты «напиши предложение» (is_correct) |
| `question_cache` | Все вопросы от AI (sentence, correct, options, explanation_ru, qtype) |
| `daily_questions` | Вопрос дня: один на дату, одинаковый для всех |
| `daily_answers` | Ответил ли пользователь на daily сегодня |
| `user_seen_questions` | Какие вопросы юзер уже видел (для дедупликации) |
| `leitner_progress` | Коробка, next_review, correct_streak для каждого времени |
| `quiz_sessions` | Текущий квиз в БД (mode, question_num, score, ответы) |

**Временная зона:** МСК (UTC+3). «Учебный день» начинается в **7:00** — если сейчас < 7:00, считается вчерашний день.

**Streak:** обновляется при завершении квиза/daily. Непрерывная серия дней занятий.

### `tenses.py` — данные 12 времён
Словарь `TENSES` + группировка `TENSE_GROUPS`:
- Present: Simple, Continuous, Perfect, Perfect Continuous
- Past: Simple, Continuous, Perfect, Perfect Continuous
- Future: Simple, Continuous, Perfect, Perfect Continuous

Каждое время содержит: `name`, `formula`, `markers`, `example`, `forms`, `endings`.
Эти данные используются в теории, промптах для AI и шпаргалке.

### `irregular_verbs.py` — 85 глаголов
4 группы: **ABC** (34), **ABB** (36), **ABA** (4), **AAA** (11).
Каждый глагол: `(base, past, past_participle, перевод)`.

### `prompts/` — промпты для AI
Шаблоны, которые вызываются из `gemini_api.py`:
- `get_quiz_prompt` — для генерации квиза
- `get_find_error_prompt` — для «Найди ошибку»
- `get_check_sentence_prompt` — для проверки предложения

---

## Система Лейтнера (обучение)

Интервальное повторение — каждое из 12 времён проходит путь через 5 коробок:

```
Box 1 → Box 2 → Box 3 → Box 4 → Box 5
 0 дн   1 день  3 дня   7 дней  14 дней   (интервалы до следующего повторения)
```

**Правила продвижения:**
- Сессия **засчитана** (≥ 80% правильных) И наступил `next_review` → `correct_streak += 1`
- **3 засчитанные сессии подряд** → коробка вверх, streak сбрасывается
- Сессия **провалена** (< 80%) → коробка сбрасывается в 1, streak = 0
- Если `next_review` ещё не наступил → коробка не меняется (тренировка «вхолостую»)

**Путь обучения для одного времени:**
1. Теория (карточка с формулой)
2. Мини-задание — написать предложение (AI проверяет)
3. Квиз с **подсказками** (кнопка 💡)
4. При Box 5 → финальный тест (10 вопросов, **без подсказок**)

**Повторение:** `get_due_tenses()` возвращает времена, у которых `next_review ≤ сегодня`.
Главное меню сигнализирует «🔔 Пора повторить: N времён».

---

## Режимы практики

| Режим | Вопросов | Подсказки | Источник |
|-------|----------|-----------|---------|
| Квиз по времени | 10 | ❌ | AI + кэш |
| Рандом (все 12) | 12 (по 1 на время) | ❌ | AI + кэш |
| Быстрая тренировка | 5 | ❌ | AI + кэш |
| Обучение (Leitner) | 5 | ✅ | AI + кэш |
| Финальный тест | 10 | ❌ | AI + кэш |
| Найди ошибку | по времени | ❌ | AI + кэш |
| Напиши предложение | 1 | формула | AI (нет кэша) |
| Daily | 1 | ❌ | AI + кэш |

---

## Главное меню — 7 кнопок

```
[👤 Профиль]  [📅 Daily]
[⚡ Быстрая тренировка]
[📚 Практика] [🎓 Обучение]
[📋 Шпаргалка] [ℹ️ Инфо]
```

Новый пользователь (`total_quizzes == 0`) видит краткую инструкцию.
Вернувшийся — streak 🔥, прогресс Лейтнера, подсказку что делать дальше.

---

## Переменные окружения (`.env`)

```env
TELEGRAM_TOKEN=...          # токен бота от @BotFather
OPENROUTER_API_KEY=...      # ключ OpenRouter для AI
ADMIN_ID=...                # Telegram ID для уведомлений об ошибках

# Только для локальной разработки:
HTTPS_PROXY=http://127.0.0.1:12334
GEMINI_API_KEY=...          # прямой ключ Gemini (не используется в проде)
```

---

## Деплой

**Bothost.ru:** подключи GitHub-репо → укажи env-переменные → `git push` = автодеплой.

Файлы для хостинга:
- `Procfile` — команда запуска
- `runtime.txt` — версия Python

**Локально:**
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python bot.py
```

---

## Админ-команды (`/bd`)

| Команда | Действие |
|---------|---------|
| `/bd download` | Скачать файл `data/bot.db` |
| `/bd clear` | Сброс статистики всех пользователей (вопросы сохраняются) |
| `/bd reset` | Полный сброс БД (удаляет и пересоздаёт) |
| `/bd path` | Путь и размер файла БД |
