"""
config.py — API-клиенты и глобальные настройки.
"""
import os
from groq import Groq as GroqClient

_groq_client = GroqClient(api_key=os.getenv("GROQ_API_KEY", ""))

AI_SYSTEM_PROMPT = os.getenv(
    "AI_SYSTEM_PROMPT",
    "Ты голосовой ИИ-ассистент в Discord. Отвечай кратко и по-дружески, "
    "как в живом разговоре. Без Markdown-форматирования. Отвечай на русском языке."
)

# Хранится в dict чтобы команда !aivoice могла менять значение без global
TTS_SETTINGS: dict = {"voice": os.getenv("TTS_VOICE", "ru-RU-SvetlanaNeural")}
