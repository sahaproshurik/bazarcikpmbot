"""
config.py — глобальные настройки из окружения (.env / настройки хостинга).
Клиент ИИ и ключи Groq живут в ai.py.
"""
import os

AI_SYSTEM_PROMPT = os.getenv(
    "AI_SYSTEM_PROMPT",
    "Ты ИИ-ассистент Discord-сервера BAZARCIK_PM. Отвечай кратко и по-дружески, "
    "как в живом разговоре. Без Markdown-форматирования. Отвечай на русском языке."
)

# Хранится в dict чтобы команда !aivoice могла менять значение без global
TTS_SETTINGS: dict = {"voice": os.getenv("TTS_VOICE", "ru-RU-SvetlanaNeural")}
