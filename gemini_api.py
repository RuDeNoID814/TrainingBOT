import json
import logging
import os
import re
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai import types
from google.genai.types import HttpOptions

from config import GEMINI_API_KEY
from tenses import TENSES
from prompts import get_quiz_prompt, get_check_sentence_prompt, get_find_error_prompt
from database import save_question_to_cache, get_cached_question, mark_question_seen, get_recent_sentences

logger = logging.getLogger(__name__)

# ── Клиент Gemini ────────────────────────────────────
_proxy_url = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
if _proxy_url:
    print(f"[Gemini] Прокси: {_proxy_url}")
    _http_client = httpx.Client(proxy=_proxy_url)
    client = genai.Client(
        api_key=GEMINI_API_KEY,
        http_options=HttpOptions(httpxClient=_http_client),
    )
else:
    print("[Gemini] Прямое подключение (без прокси)")
    client = genai.Client(api_key=GEMINI_API_KEY)

# ── Модели (fallback по убыванию лимитов) ────────────
MODELS = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
]

COOLDOWN_SEC = 60 * 60  # 1 час блокировки после 429
_blocked_until: dict[str, float] = {}

# ── System instructions ──────────────────────────────
QUIZ_SYSTEM = (
    "You are an expert English grammar teacher creating quiz questions for Russian-speaking students. "
    "You always respond with valid JSON only. "
    "You create diverse, creative questions using varied vocabulary, subjects, and real-life contexts. "
    "Each question tests a specific English tense with one correct answer and three plausible distractors from other tenses. "
    "Explanations are always in Russian, short and clear."
)

CHECK_SYSTEM = (
    "You are a friendly English grammar teacher checking sentences written by Russian-speaking students. "
    "You always respond with valid JSON only. "
    "You give encouraging feedback in Russian. "
    "You check both grammatical correctness and whether the correct tense was used."
)

# ── JSON-схемы для structured output ─────────────────
QUIZ_SCHEMA = types.Schema(
    type="OBJECT",
    properties={
        "sentence": types.Schema(
            type="STRING",
            description="English sentence with ___ blank and base verb in parentheses",
        ),
        "correct": types.Schema(
            type="STRING",
            description="The correct verb form for the blank",
        ),
        "options": types.Schema(
            type="ARRAY",
            items=types.Schema(type="STRING"),
            description="Exactly 4 options: 1 correct + 3 plausible distractors from other tenses",
        ),
        "explanation_ru": types.Schema(
            type="STRING",
            description="Short explanation in Russian why this answer is correct, mentioning the tense name and time marker",
        ),
    },
    required=["sentence", "correct", "options", "explanation_ru"],
)

FIND_ERROR_SCHEMA = types.Schema(
    type="OBJECT",
    properties={
        "sentence": types.Schema(
            type="STRING",
            description="English sentence with a WRONG verb tense (the error)",
        ),
        "correct": types.Schema(
            type="STRING",
            description="The correct verb form that fixes the error",
        ),
        "options": types.Schema(
            type="ARRAY",
            items=types.Schema(type="STRING"),
            description="Exactly 4 options: 1 correct fix + 3 wrong alternatives",
        ),
        "explanation_ru": types.Schema(
            type="STRING",
            description="Short explanation in Russian: why the original is wrong, why the correct answer fits",
        ),
    },
    required=["sentence", "correct", "options", "explanation_ru"],
)

CHECK_SCHEMA = types.Schema(
    type="OBJECT",
    properties={
        "is_correct": types.Schema(
            type="BOOLEAN",
            description="true if the sentence correctly uses the target tense",
        ),
        "tense_used": types.Schema(
            type="STRING",
            description="The tense actually used in the student's sentence",
        ),
        "corrected": types.Schema(
            type="STRING",
            description="Corrected version of the sentence (or same if correct)",
        ),
        "feedback_ru": types.Schema(
            type="STRING",
            description="Feedback in Russian: praise if correct, gentle correction if wrong. 2-3 sentences max.",
        ),
    },
    required=["is_correct", "tense_used", "corrected", "feedback_ru"],
)


def _parse_json(text: str) -> dict | None:
    """Парсит JSON из ответа (fallback если structured output не сработал)."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse Gemini JSON: %s", text[:200])
        return None


def _generate(prompt: str, system: str = None, schema: types.Schema = None) -> str | None:
    """Отправляет запрос в Gemini с system instruction и structured output."""
    now = time.time()

    config = types.GenerateContentConfig(
        temperature=0.9,
        top_p=0.9,
    )
    if system:
        config.system_instruction = system
    if schema:
        config.response_mime_type = "application/json"
        config.response_schema = schema

    for model in MODELS:
        if model in _blocked_until and now < _blocked_until[model]:
            logger.debug("Модель %s: на кулдауне, пропускаю", model)
            continue

        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
            logger.info("Gemini OK: %s", model)
            return response.text
        except httpx.TimeoutException:
            logger.warning("Модель %s: timeout, пробую следующую", model)
            continue
        except httpx.ConnectError:
            logger.warning("Модель %s: ошибка подключения (прокси?), пробую следующую", model)
            continue
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                _blocked_until[model] = now + COOLDOWN_SEC
                logger.warning("Модель %s: лимит исчерпан, блокирую на %d мин", model, COOLDOWN_SEC // 60)
                continue
            if "503" in err_str or "UNAVAILABLE" in err_str:
                logger.warning("Модель %s: 503 перегружена, пробую следующую", model)
                continue
            # Некоторые модели могут не поддерживать response_schema — пробуем без
            if schema and ("schema" in err_str.lower() or "mime" in err_str.lower()):
                logger.warning("Модель %s: не поддерживает schema, пробую без", model)
                try:
                    fallback_config = types.GenerateContentConfig(
                        temperature=0.9,
                        top_p=0.9,
                    )
                    if system:
                        fallback_config.system_instruction = system
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=fallback_config,
                    )
                    logger.info("Gemini OK (без schema): %s", model)
                    return response.text
                except Exception as e2:
                    err2 = str(e2)
                    if "429" in err2 or "RESOURCE_EXHAUSTED" in err2:
                        _blocked_until[model] = now + COOLDOWN_SEC
                        logger.warning("Модель %s: лимит исчерпан", model)
                        continue
                    if "503" in err2 or "UNAVAILABLE" in err2:
                        logger.warning("Модель %s: 503 перегружена", model)
                        continue
                    logger.error("Gemini API error (%s): %s", model, e2)
                    return None
            logger.error("Gemini API error (%s): %s", model, e)
            return None

    logger.error("Все модели исчерпаны или на кулдауне")
    return None


def generate_question(tense_key: str, user_id: int = 0) -> dict | None:
    tense = TENSES[tense_key]
    used = get_recent_sentences(tense_key)
    prompt = get_quiz_prompt(tense["name"], tense["formula"], tense["markers"], used)

    for attempt in range(2):
        text = _generate(prompt, system=QUIZ_SYSTEM, schema=QUIZ_SCHEMA)
        if text is None:
            logger.info("Gemini недоступен, ищу вопрос в кэше для %s (user %d)", tense_key, user_id)
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
        text = _generate(prompt, system=QUIZ_SYSTEM, schema=FIND_ERROR_SCHEMA)
        if text is None:
            logger.info("Gemini недоступен, ищу find_error в кэше для %s", tense_key)
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
        text = _generate(prompt, system=CHECK_SYSTEM, schema=CHECK_SCHEMA)
        if text is None:
            return None
        data = _parse_json(text)
        if data and "is_correct" in data and "feedback_ru" in data:
            return data
        logger.error("Invalid check_sentence response (attempt %d): %s", attempt + 1, data)
    return None
