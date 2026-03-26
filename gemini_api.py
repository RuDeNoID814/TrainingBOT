import json
import logging
import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()

from google import genai
from google.genai.types import HttpOptions

from config import GEMINI_API_KEY
from tenses import TENSES
from prompts import get_quiz_prompt

logger = logging.getLogger(__name__)

# Прокси для Gemini API (локально через Hiddify, на хостинге — без прокси)
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


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.error("Failed to parse Gemini JSON: %s", text[:200])
        return None


def generate_question(tense_key: str) -> dict | None:
    tense = TENSES[tense_key]
    prompt = get_quiz_prompt(tense["name"], tense["formula"], tense["markers"])

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            data = _parse_json(response.text)
            if data and all(k in data for k in ("sentence", "correct", "options", "explanation_ru")):
                return data
            logger.error("Invalid Gemini response structure (attempt %d): %s", attempt + 1, data)
        except Exception as e:
            logger.error("Gemini API error (attempt %d): %s", attempt + 1, e)
    return None
