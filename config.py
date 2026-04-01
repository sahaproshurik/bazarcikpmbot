"""
config.py — API-клиенты и глобальные настройки.
"""
import os
from groq import Groq
import random

keys_string = os.getenv("GROQ_API_KEYS", "")

# 2. Разбиваем строку по запятой и чистим от случайных пробелов
# Получится список: ['gsk_ключ1', 'gsk_ключ2', 'gsk_ключ3']
API_KEYS = [key.strip() for key in keys_string.split(",") if key.strip()]


# 3. Функция, которая выдает клиента со случайным ключом
def get_groq_client():
    if not API_KEYS:
        raise ValueError("❌ Ключи Groq не найдены в .env файле!")

    selected_key = random.choice(API_KEYS)
    return Groq(api_key=selected_key)

AI_SYSTEM_PROMPT = os.getenv(
    "AI_SYSTEM_PROMPT",
    "Ты голосовой ИИ-ассистент в Discord. Отвечай кратко и по-дружески, "
    "как в живом разговоре. Без Markdown-форматирования. Отвечай на русском языке."
)

# Хранится в dict чтобы команда !aivoice могла менять значение без global
TTS_SETTINGS: dict = {"voice": os.getenv("TTS_VOICE", "ru-RU-SvetlanaNeural")}
