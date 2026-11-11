"""
local_stt.py — распознавание речи прямо на сервере бота: NVIDIA Parakeet TDT 0.6B v3 (ONNX, без видеокарты).

Зачем: Whisper в Groq — облако с лимитами, и звук уходит туда. Parakeet понимает 25 европейских языков, среди них
русский, украинский и словацкий, и, в отличие от Whisper, не дополняет фразу до 30 секунд звука — поэтому на
процессоре быстрый. Замер на сервере (4 ядра Ampere, 3 потока): фраза 3 с — 0.65 с, фраза 6 с — 1.2 с, все тестовые
фразы на трёх языках без ошибок. Квантованная int8-версия втрое быстрее, но портит словацкий — берём полную (fp32).

Чего Parakeet не умеет: подсказки с именами (как prompt у Whisper) и выбора языка. Имена правит names.fix_names —
по прозвищам и никам сервера; язык он определяет сам.

STT_ENGINE: local (по умолчанию на 3+ ядрах) — Parakeet, а Groq Whisper — запасной, если модель не готова или упала;
groq — как раньше. Модель (~2.5 ГБ на диске, ~2.5 ГБ памяти) скачивается при первом !listen в parakeet-v3/
и держится в памяти, пока бот слушает войс. Работает в отдельном процессе на ядрах детектора (WAKE_CORES),
ядро 0 остаётся боту.
"""
import asyncio
import io
import multiprocessing
import os
import time
import wave
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor
import diag
import wake_word

MODEL_NAME = "nemo-parakeet-tdt-0.6b-v3"
MODEL_REPO = "istupakov/parakeet-tdt-0.6b-v3-onnx"
MODEL_DIR  = os.path.abspath("parakeet-v3")
# полная (fp32) модель; int8-файлы не качаем — на словацком они теряют даже «Bazarčik»
MODEL_FILES = ("config.json", "vocab.txt", "nemo128.onnx", "decoder_joint-model.onnx", "encoder-model.onnx",
               "encoder-model.onnx.data")
ENGINE  = os.getenv("STT_ENGINE", "local" if (os.cpu_count() or 1) >= 3 else "groq").strip().lower()
THREADS = int(os.getenv("LOCAL_STT_THREADS", "0") or 0) or max(1, len(wake_word.CORES or ()) or 1)


class LocalSTTError(Exception):
    """Локальное распознавание не сработало — фразу распознаёт Groq."""


def prepare_model(model_dir: str = None) -> str:
    """Скачивает модель с HuggingFace в обычную папку (не в кеш HF: из кеша onnxruntime отказывается читать
    веса энкодера — «External data path escapes model directory»). Уже скачанная — не трогается."""
    model_dir = model_dir or MODEL_DIR
    if all(os.path.exists(os.path.join(model_dir, f)) for f in MODEL_FILES):
        return model_dir
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL_REPO, local_dir=model_dir, allow_patterns=list(MODEL_FILES))
    return model_dir


# ── Рабочий процесс ───────────────────────────────────────────
_worker: dict = {}


def _worker_init(path: str, cores, threads: int):
    if cores and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, cores)
        except OSError:
            pass
    import onnx_asr
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = threads, 1
    started = time.monotonic()
    _worker["model"] = onnx_asr.load_model(MODEL_NAME, path, sess_options=options)
    _worker["load"] = time.monotonic() - started


def _worker_ping() -> float:
    return _worker.get("load", 0.0)


def _worker_recognize(wav_bytes: bytes) -> tuple:
    """WAV 16 кГц моно (voice_listen.to_wav) → (текст, сколько распознавали)."""
    import numpy as np
    with wave.open(io.BytesIO(wav_bytes)) as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1:
            raise ValueError(f"нужен WAV 16 кГц моно, а пришёл {w.getframerate()} Гц, каналов {w.getnchannels()}")
        audio = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    began = time.monotonic()
    text = _worker["model"].recognize(audio)
    return (text or "").strip(), time.monotonic() - began


class LocalSTT:
    """Parakeet на все сессии прослушивания: процесс с моделью запускается с первой сессией и гасится с последней."""

    def __init__(self):
        self.pool = None
        self.users = 0
        self.state = "выключен (STT_ENGINE=groq)" if ENGINE != "local" else "не загружен"
        self.stats = {"done": 0, "work": 0.0, "failed": 0}
        self._task = None

    @property
    def ready(self) -> bool:
        return self.pool is not None

    def acquire(self):
        self.users += 1
        if ENGINE == "local" and self.pool is None and (self._task is None or self._task.done()):
            self._task = asyncio.get_running_loop().create_task(self._load())

    def release(self):
        self.users = max(0, self.users - 1)
        if not self.users and self.pool is not None:
            self._drop()
            print("[stt] Parakeet выгружен из памяти")

    def _drop(self, why: str = None):
        pool, self.pool = self.pool, None
        self.state = f"не работает ({why})" if why else "не загружен"
        if why:
            print(f"[stt] Parakeet отключён, фразы распознаёт Groq Whisper: {why}")
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    async def _load(self):
        self.state = "загружается"
        started = time.monotonic()
        try:
            fresh = not os.path.exists(os.path.join(MODEL_DIR, "encoder-model.onnx.data"))
            if fresh:
                print("[stt] Скачиваю Parakeet v3 (~2.5 ГБ) — пока он не готов, фразы распознаёт Groq Whisper")
            path = await asyncio.to_thread(prepare_model)
            if fresh:
                print(f"[stt] Parakeet скачан за {time.monotonic() - started:.0f} с → {path}")
            pool = ProcessPoolExecutor(1, mp_context=multiprocessing.get_context("spawn"),
                                       initializer=_worker_init, initargs=(path, wake_word.CORES, THREADS))
            load = await asyncio.get_running_loop().run_in_executor(pool, _worker_ping)
        except Exception as e:
            self.state = f"не работает ({type(e).__name__}: {e})"
            print(f"[stt] Parakeet не запустился, фразы распознаёт Groq Whisper: {self.state}")
            return
        if not self.users:
            pool.shutdown(wait=False, cancel_futures=True)
            self.state = "не загружен"
            return
        self.pool, self.state = pool, "работает"
        cores = wake_word.CORES
        print(f"[stt] Parakeet готов за {time.monotonic() - started:.1f} с (модель — {load:.1f} с), потоков {THREADS}"
              + (f", ядра {min(cores)}–{max(cores)}" if cores else "") + f"; {diag.report()}")

    async def transcribe(self, wav_bytes: bytes) -> tuple:
        """(текст, сколько распознавали). LocalSTTError — не готов или ошибка: тогда фразу распознаёт Groq."""
        pool = self.pool
        if pool is None:
            raise LocalSTTError(f"Parakeet {self.state}")
        try:
            text, worked = await asyncio.get_running_loop().run_in_executor(pool, _worker_recognize, wav_bytes)
        except BrokenExecutor as e:
            self.stats["failed"] += 1
            self._drop(f"процесс упал ({type(e).__name__})")
            raise LocalSTTError("процесс Parakeet упал") from e
        except Exception as e:
            self.stats["failed"] += 1
            raise LocalSTTError(f"{type(e).__name__}: {e}") from e
        self.stats["done"] += 1
        self.stats["work"] += worked
        return text, worked

    def report(self) -> str:
        s = self.stats
        avg = f", в среднем {s['work'] / s['done']:.2f} с" if s["done"] else ""
        return f"; Parakeet {self.state}: распознано {s['done']}{avg}, ошибок {s['failed']}"


engine = LocalSTT()
