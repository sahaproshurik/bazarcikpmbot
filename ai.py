"""
ai.py — единая точка работы с ИИ (Groq) для всех cogs: чат и распознавание речи.

• Ключи: GROQ_API_KEYS (через запятую) или старый GROQ_API_KEY.
• Модель: GROQ_MODEL, а если её сняли с поддержки — автоматически пробуем следующую из списка.
  (llama-3.3-70b-versatile, на которой работал бот, Groq отключил 16.08.2026.)
• Лимит или неверный ключ — переключаемся на другой ключ.
"""
import os
import random
from groq import (AsyncGroq, APIConnectionError, APIStatusError, AuthenticationError,
                  BadRequestError, NotFoundError, PermissionDeniedError, RateLimitError)

DEFAULT_MODELS = ["openai/gpt-oss-120b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b"]
STT_MODELS     = ["whisper-large-v3-turbo", "whisper-large-v3"]


class AIError(Exception):
    """Ошибка, текст которой можно показать пользователю."""


def _load_keys() -> list:
    raw = os.getenv("GROQ_API_KEYS") or os.getenv("GROQ_API_KEY") or ""
    return [k.strip() for k in raw.split(",") if k.strip()]


def _load_models() -> list:
    custom = [m.strip() for m in os.getenv("GROQ_MODEL", "").split(",") if m.strip()]
    return list(dict.fromkeys(custom + DEFAULT_MODELS))


API_KEYS = _load_keys()
MODELS   = _load_models()
STATE    = {"model": MODELS[0], "dead_models": set(), "last_error": None, "ok": 0, "failed": 0}
_dead_stt: set = set()
_clients: dict = {}


def _client(key: str) -> AsyncGroq:
    if key not in _clients:
        _clients[key] = AsyncGroq(api_key=key, max_retries=0, timeout=40)
    return _clients[key]


def _model_params(model: str) -> dict:
    # reasoning-модели тратят токены на «размышления» — просим думать коротко и не возвращать их
    if model.startswith("openai/gpt-oss"):
        return {"reasoning_effort": "low", "include_reasoning": False}
    if model.startswith("qwen/qwen3"):
        return {"reasoning_effort": "none"}
    return {}


def _is_model_gone(e: Exception) -> bool:
    text = str(e).lower()
    return isinstance(e, (NotFoundError, BadRequestError)) and "model" in text and any(
        w in text for w in ("decommission", "not found", "does not exist", "deprecated"))


def _friendly(e) -> str:
    if e is None:
        return "ИИ сейчас недоступен."
    if isinstance(e, RateLimitError):
        return "Лимит запросов к ИИ исчерпан, попробуй через минуту."
    if isinstance(e, (AuthenticationError, PermissionDeniedError)):
        return "Ключ Groq недействителен — администратору нужно обновить GROQ_API_KEYS."
    if isinstance(e, APIConnectionError):
        return "Нет связи с сервером ИИ, попробуй позже."
    if isinstance(e, AIError):
        return str(e)
    return f"Ошибка ИИ: {str(e)[:200]}"


async def _run(models: list, call, dead: set):
    """Перебирает модели и ключи: лимит/плохой ключ — следующий ключ, снятая модель — следующая модель.
    call(client, model) возвращает результат; None означает «пустой ответ, попробуй другой ключ»."""
    if not API_KEYS:
        raise AIError("Не задан ключ Groq: добавь GROQ_API_KEYS (или GROQ_API_KEY) в .env / настройки хостинга.")
    last = None
    for model in models:
        for key in random.sample(API_KEYS, len(API_KEYS)):
            try:
                result = await call(_client(key), model)
                if result is not None:
                    return model, result
                last = AIError("ИИ вернул пустой ответ.")
            except (RateLimitError, AuthenticationError, PermissionDeniedError, APIConnectionError) as e:
                last = e                       # этот ключ не сработал — пробуем следующий
            except (NotFoundError, BadRequestError) as e:
                last = e
                if _is_model_gone(e):
                    dead.add(model)
                    print(f"[ai] Модель {model} недоступна, переключаюсь: {e}")
                    break                      # модель снята — следующая модель
                raise AIError(_friendly(e)) from e
            except APIStatusError as e:
                last = e
    print(f"[ai] Запрос не удался: {last!r}")
    raise AIError(_friendly(last))


async def chat(messages: list, max_tokens: int = 700, temperature: float = 0.8) -> str:
    """Отправляет диалог в Groq и возвращает текст ответа. Бросает AIError с понятным текстом."""
    async def call(client, model):
        resp = await client.chat.completions.create(
            model=model, messages=messages, temperature=temperature,
            max_completion_tokens=max_tokens, **_model_params(model))
        return (resp.choices[0].message.content or "").strip() or None

    # последняя рабочая модель первой, снятые с поддержки пропускаем (если снято всё — пробуем все заново)
    models = [m for m in dict.fromkeys([STATE["model"], *MODELS]) if m not in STATE["dead_models"]] or MODELS
    try:
        model, text = await _run(models, call, STATE["dead_models"])
    except AIError as e:
        STATE["failed"] += 1
        STATE["last_error"] = str(e)
        raise
    STATE.update(model=model, last_error=None)
    STATE["ok"] += 1
    return text


async def ask(system: str, prompt: str, **kw) -> str:
    return await chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}], **kw)


async def transcribe(audio: bytes, filename: str = "speech.wav", hint: str = "") -> str:
    """Распознаёт речь через Whisper на Groq. Аудио нигде не сохраняется — только уходит на распознавание.
    hint — подсказка Whisper'у, как пишутся имена (например, «Базарчик»). Тишина → пустая строка."""
    async def call(client, model):
        resp = await client.audio.transcriptions.create(
            file=(filename, audio), model=model, prompt=hint or None,
            temperature=0, response_format="json")
        return (getattr(resp, "text", "") or "").strip()

    models = [m for m in STT_MODELS if m not in _dead_stt] or STT_MODELS
    _, text = await _run(models, call, _dead_stt)
    return text


def status() -> str:
    if not API_KEYS:
        return "🔴 нет ключа GROQ_API_KEYS"
    state = "🟢" if STATE["last_error"] is None else "🟠"
    text = f"{state} {STATE['model']} • ключей: {len(API_KEYS)} • ответов: {STATE['ok']}"
    if STATE["last_error"]:
        text += f"\nПоследняя ошибка: {STATE['last_error']}"
    return text
