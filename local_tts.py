"""
local_tts.py — озвучка прямо на сервере бота: Piper (ONNX, без интернета и видеокарты).

Зачем: edge-tts (голоса Microsoft) с сервера иногда синтезирует короткий ответ 5–16 секунд или не отвечает вовсе
(«NoAudioReceived», живой войс 11.11). Piper на том же сервере делает короткую фразу за 0.3 с, 8 секунд речи — за
1.5 с (замер, одно ядро). Голоса у него проще, поэтому основным остаётся edge-tts, а Piper — подстраховка:
voice_ai.say запускает оба сразу и берёт edge-tts, если тот успел за TTS_EDGE_WAIT секунд, иначе — Piper.

TTS_ENGINE: auto (по умолчанию) — так; edge — только edge-tts, как раньше; piper — только Piper.
Голоса (~60 МБ каждый) скачиваются при первом !listen в piper-voices/ с HuggingFace (rhasspy/piper-voices)
и держатся в памяти бота.
"""
import asyncio
import os
import tempfile
import time
import urllib.request
import wave

ENGINE    = os.getenv("TTS_ENGINE", "auto").strip().lower()
EDGE_WAIT = float(os.getenv("TTS_EDGE_WAIT", "2.5"))
VOICE_DIR = os.path.abspath("piper-voices")
VOICE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
# язык → (женский, мужской) — как у edge-tts в voice_ai.TTS_VOICES; у украинского и словацкого голос один
VOICES = {
    "ru": ("ru_RU-irina-medium", "ru_RU-denis-medium"),
    "uk": ("uk_UA-ukrainian_tts-medium", "uk_UA-ukrainian_tts-medium"),
    "sk": ("sk_SK-lili-medium", "sk_SK-lili-medium"),
    "en": ("en_US-lessac-medium", "en_US-ryan-medium"),
}
# украинские голоса Piper не знают фонем заглавных букв («Missing phoneme from id map: С») — пропускают их
LOWERCASE = {"uk"}

_voices: dict = {}                 # имя голоса → PiperVoice
_failed: dict = {}                 # имя голоса → почему не загрузился (повторно не пробуем)


def available() -> bool:
    if ENGINE == "edge":
        return False
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def voice_name(lang: str, male: bool) -> str:
    return VOICES.get(lang, VOICES["ru"])[1 if male else 0]


def _download(name: str) -> str:
    """Голос с HuggingFace: «ru_RU-irina-medium» → ru/ru_RU/irina/medium/ru_RU-irina-medium.onnx (+ .json)."""
    path = os.path.join(VOICE_DIR, f"{name}.onnx")
    if os.path.exists(path) and os.path.exists(path + ".json"):
        return path
    os.makedirs(VOICE_DIR, exist_ok=True)
    region, speaker, quality = name.split("-")
    remote = f"{VOICE_URL}{region.split('_')[0]}/{region}/{speaker}/{quality}/{name}.onnx"
    for suffix in (".json", ""):                     # модель — последней: по ней судим, что голос скачан
        tmp = path + suffix + ".part"
        with urllib.request.urlopen(remote + suffix, timeout=60) as resp, open(tmp, "wb") as out:
            while chunk := resp.read(1 << 20):
                out.write(chunk)
        os.replace(tmp, path + suffix)
    return path


def _load(name: str):
    if name in _voices:
        return _voices[name]
    if name in _failed:
        raise RuntimeError(_failed[name])
    try:
        from piper import PiperVoice
        started = time.monotonic()
        voice = PiperVoice.load(_download(name))
    except Exception as e:
        _failed[name] = f"{type(e).__name__}: {e}"
        print(f"[tts] Голос Piper {name} не загрузился: {_failed[name]}")
        raise
    _voices[name] = voice
    print(f"[tts] Голос Piper {name} готов за {time.monotonic() - started:.1f} с")
    return voice


def _synth(text: str, lang: str, male: bool, path: str):
    voice = _load(voice_name(lang, male))
    with wave.open(path, "wb") as w:
        voice.synthesize_wav(text.lower() if lang in LOWERCASE else text, w)


async def synth(text: str, lang: str, male: bool) -> str:
    """WAV-файл с речью (путь; удаляет вызывающий). Ошибка — исключение."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = f.name
    try:
        await asyncio.to_thread(_synth, text, lang, male, path)
    except BaseException:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    return path


async def warm(langs):
    """Заранее скачать и загрузить голоса языков прослушки — чтобы первая подстраховка не ждала скачивания."""
    if not available():
        return
    for lang in dict.fromkeys(langs):
        for name in dict.fromkeys(VOICES.get(lang, ())):
            try:
                await asyncio.to_thread(_load, name)
            except Exception:
                pass
