import json
import logging
import os
import re
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

from tenses import TENSES
from prompts import get_quiz_prompt, get_check_sentence_prompt, get_find_error_prompt
from database import save_question_to_cache, get_cached_question, mark_question_seen, get_recent_sentences

logger = logging.getLogger(__name__)

# ── OpenRouter API ────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Бесплатные и дешёвые модели на OpenRouter (fallback)
MODELS = [
    "google/gemini-2.0-flash-001",
    "google/gemini-2.5-flash-preview",
    "google/gemini-2.0-flash-lite-001",
    "google/gemini-flash-1.5-8b",
]

COOLDOWN_SEC = 60 * 60  # 1 час блокировки после 429
_blocked_until: dict[str, float] = {}

# ── System instructions ──────────────────────────────
QUIZ_SYSTEM = (
    "You are an expert English grammar teacher creating quiz questions for Russian-speaking students. "
    "You always respond with valid JSON only, no markdown, no code blocks. "
    "You create diverse, creative questions using varied vocabulary, subjects, and real-life contexts. "
    "Each question tests a specific English tense with one correct answer and three plausible distractors from other tenses. "
    "Explanations are always in Russian, short and clear."
)

CHECK_SYSTEM = (
    "You are a friendly English grammar teacher checking sentences written by Russian-speaking students. "
    "You always respond with valid JSON only, no markdown, no code blocks. "
    "You give encouraging feedback in Russian. "
    "You check both grammatical correctness and whether the correct tense was used."
)

# ── JSON-инструкции для промптов ─────────────────────
QUIZ_JSON_INSTRUCTION = """
Respond with a JSON object with these fields:
- "sentence": English sentence with ___ blank and base verb in parentheses
- "correct": The correct verb form for the blank
- "options": Array of exactly 4 strings: 1 correct + 3 plausible distractors from other tenses
- "explanation_ru": Short explanation in Russian why this answer is correct, mentioning the tense name and time marker
"""

FIND_ERROR_JSON_INSTRUCTION = """
Respond with a JSON object with these fields:
- "sentence": English sentence with a WRONG verb tense (the error to find)
- "correct": The correct verb form that fixes the error
- "options": Array of exactly 4 strings: 1 correct fix + 3 wrong alternatives
- "explanation_ru": Short explanation in Russian: why the original is wrong, why the correct answer fits
"""

CHECK_JSON_INSTRUCTION = """
Respond with a JSON object with these fields:
- "is_correct": boolean, true if the sentence correctly uses the target tense
- "tense_used": string, the tense actually used in the student's sentence
- "corrected": string, corrected version of the sentence (or same if correct)
- "feedback_ru": string, feedback in Russian: praise if correct, gentle correction if wrong. 2-3 sentences max.
"""


def _parse_json(text: str) -> dict | None:
    """Парсит JSON из ответа."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse JSON: %s", text[:200])
        return None


def _generate(prompt: str, system: str = None, json_instruction: str = "") -> str | None:
    """Отправляет запрос через OpenRouter API."""
    now = time.time()

    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY не задан!")
        return None

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    # Формируем сообщения
    messages = []
    if system:
        messages.append({"role": "system", "content": system})

    user_content = prompt
    if json_instruction:
        user_content = f"{json_instruction}\n\n{prompt}"
    messages.append({"role": "user", "content": user_content})

    for model in MODELS:
        if model in _blocked_until and now < _blocked_until[model]:
            logger.debug("Модель %s: на кулдауне, пропускаю", model)
            continue

        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.9,
            "top_p": 0.9,
        }

        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(OPENROUTER_URL, headers=headers, json=payload)

            if response.status_code == 200:
                data = response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if content:
                    logger.info("OpenRouter OK: %s", model)
                    return content
                logger.warning("Модель %s: пустой ответ", model)
                continue

            elif response.status_code == 429:
                _blocked_until[model] = now + COOLDOWN_SEC
                logger.warning("Модель %s: лимит исчерпан (429), блокирую на %d мин", model, COOLDOWN_SEC // 60)
                continue

            elif response.status_code == 503:
                logger.warning("Модель %s: 503 перегружена, пробую следующую", model)
                continue

            else:
                err_body = response.text[:300]
                if "location" in err_body.lower() or "FAILED_PRECONDITION" in err_body:
                    logger.warning("Модель %s: геоблокировка, пробую следующую", model)
                    continue
                logger.warning("Модель %s: HTTP %d — %s, пробую следующую", model, response.status_code, err_body[:100])
                continue

        except httpx.TimeoutException:
            logger.warning("Модель %s: timeout, пробую следующую", model)
            continue
        except httpx.ConnectError:
            logger.warning("Модель %s: ошибка подключения, пробую следующую", model)
            continue
        except Exception as e:
            logger.error("Модель %s: непредвиденная ошибка: %s", model, e)
            continue

    logger.error("Все модели исчерпаны или на кулдауне")
    return None


def generate_question(tense_key: str, user_id: int = 0) -> dict | None:
    tense = TENSES[tense_key]
    used = get_recent_sentences(tense_key)
    prompt = get_quiz_prompt(tense["name"], tense["formula"], tense["markers"], used)

    for attempt in range(2):
        text = _generate(prompt, system=QUIZ_SYSTEM, json_instruction=QUIZ_JSON_INSTRUCTION)
        if text is None:
            logger.info("AI недоступен, ищу вопрос в кэше для %s (user %d)", tense_key, user_id)
            cached = get_cached_question(tense_key, user_id)
            if cached:
                logger.info("Вопрос взят из кэша")
                return cached
            return None
        data = _parse_json(text)
        if data and all(k in data for k in ("sentence", "correct", "options", "explanation_ru")):
            q_id = save_question_to_cache(tense_key, data)
            if q_id and user_id:
                mark_question_seen(user_id, q_id)
            return data
        logger.error("Invalid quiz response (attempt %d): %s", attempt + 1, data)
    return None


def generate_find_error(tense_key: str, user_id: int = 0) -> dict | None:
    tense = TENSES[tense_key]
    used = get_recent_sentences(tense_key)
    prompt = get_find_error_prompt(tense["name"], tense["formula"], tense["markers"], used)

    for attempt in range(2):
        text = _generate(prompt, system=QUIZ_SYSTEM, json_instruction=FIND_ERROR_JSON_INSTRUCTION)
        if text is None:
            logger.info("AI недоступен, ищу find_error в кэше для %s", tense_key)
            cached = get_cached_question(tense_key, user_id, qtype="find_error")
            if cached:
                logger.info("Find_error взят из кэша")
                return cached
            return None
        data = _parse_json(text)
        if data and all(k in data for k in ("sentence", "correct", "options", "explanation_ru")):
            q_id = save_question_to_cache(tense_key, data, qtype="find_error")
            if q_id and user_id:
                mark_question_seen(user_id, q_id)
            return data
        logger.error("Invalid find_error response (attempt %d): %s", attempt + 1, data)
    return None


def check_sentence(tense_key: str, user_sentence: str) -> dict | None:
    tense = TENSES[tense_key]
    prompt = get_check_sentence_prompt(tense["name"], user_sentence)

    for attempt in range(2):
        text = _generate(prompt, system=CHECK_SYSTEM, json_instruction=CHECK_JSON_INSTRUCTION)
        if text is None:
            return None
        data = _parse_json(text)
        if data and "is_correct" in data and "feedback_ru" in data:
            return data
        logger.error("Invalid check_sentence response (attempt %d): %s", attempt + 1, data)
    return None
