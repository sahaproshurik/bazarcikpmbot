"""
wake_word.py — локальный детектор обращения «Базарчик» (Vosk), как у Siri и «Окей, Google».

Раньше бот отправлял в Whisper (Groq) каждую фразу из войса, только чтобы узнать, есть ли в ней
обращение: лимит распознаваний кончался за пару минут, а чужие разговоры уходили в облако.
Теперь начало каждой фразы (первые WINDOW_SEC секунд) слушает маленькая офлайн-модель прямо на сервере
бота. В Whisper уходят только фразы, где она услышала «Базарчик», остальные сразу забываются и никуда
не отправляются. Whisper по-прежнему проверяет обращение по тексту — ложное срабатывание стоит один запрос.

Модель vosk-model-small-ru-0.22 скачивается при первом !listen (проверяется SHA-256) и хранится
в облегчённом виде: без большого графа языка (Gr.fst) и со словарём из нескольких слов — так она
занимает ~80 МиБ памяти вместо ~170. Слова «базарчик» в её словаре нет, но она надёжно слышит его
как «базар» + «чик», одинаково на русском, украинском и словацком. В памяти модель держится,
только пока бот слушает войс.

Если vosk не установлен, модель не скачалась или детектор выключен (LOCAL_WAKE=0), бот работает
как раньше — каждую фразу распознаёт Whisper.
"""
import asyncio
import hashlib
import json
import os
import shutil
import struct
import threading
import time
import urllib.request
import zipfile
from array import array
import diag

ENABLED      = os.getenv("LOCAL_WAKE", "1").strip().lower() not in ("0", "off", "false", "no")
MODEL_URL    = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
MODEL_SHA256 = "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4"
MODEL_DIR    = os.path.abspath("vosk-wake-ru")
WINDOW_SEC   = 2.0           # слушаем только начало фразы: обращение стоит первым, «Слушай, Базарчик» влезает
WAKE_BY_SEC  = 1.2           # «базар» должен начаться не позже — дальше уже не обращение, а середина фразы
GRAMMAR      = json.dumps(["базар", "чик", "[unk]"], ensure_ascii=False)
KEEP_WORDS   = ("<eps>", "!SIL", "[unk]", "#0", "<s>", "</s>", "базар", "чик")
# файлы модели, которые нужны для поиска по словарю (Gr.fst — граф свободной речи — не нужен)
NEEDED = ("am/final.mdl", "conf/model.conf", "conf/mfcc.conf", "graph/HCLr.fst", "graph/disambig_tid.int",
          "graph/phones/word_boundary.int", "ivector/final.dubm", "ivector/final.ie", "ivector/final.mat",
          "ivector/global_cmvn.stats", "ivector/online_cmvn.conf", "ivector/splice.conf")


def to_16k_mono(pcm: bytes) -> bytes:
    """PCM из войса (48 кГц, стерео, 16 бит) → 16 кГц моно для Vosk: левый канал, среднее по 3 отсчёта."""
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 4])
    left = samples[0::2]
    n = len(left) - len(left) % 3
    return array("h", ((a + b + c) // 3 for a, b, c in zip(left[0:n:3], left[1:n:3], left[2:n:3]))).tobytes()


def called(words) -> bool:
    """Обращение — это «базар», сразу за ним «чик», в самом начале фразы. «Был на базаре» не считается."""
    return any(a[0] == "базар" and b[0] == "чик" and a[1] <= WAKE_BY_SEC for a, b in zip(words, words[1:]))


def _read_words(stream) -> dict:
    """Нужные слова и их номера из таблицы символов в начале бинарного OpenFst-файла Gr.fst."""
    def i32():
        return struct.unpack("<i", stream.read(4))[0]

    def i64():
        return struct.unpack("<q", stream.read(8))[0]

    def text():
        return stream.read(i32()).decode("utf-8")

    if i32() != 2125659606:
        raise ValueError("Gr.fst — не файл OpenFst")
    text(), text()                                   # тип графа и тип дуг
    i32()                                            # версия
    flags = i32()
    stream.read(32)                                  # свойства, старт, число состояний и дуг
    found = {}
    for has in (flags & 1, flags & 2):               # таблица входных, затем выходных символов
        if not has:
            continue
        if i32() != 2125658996:
            raise ValueError("в Gr.fst нет таблицы слов")
        text(), i64()
        for _ in range(i64()):
            word, key = text(), i64()
            if has == 2 and word in KEEP_WORDS:
                found[word] = key
    missing = set(KEEP_WORDS) - set(found)
    if missing:
        raise ValueError(f"в словаре модели нет: {', '.join(sorted(missing))}")
    return found


def prepare_model(model_dir: str = None, url: str = None, sha256: str = None) -> str:
    """Скачивает модель и раскладывает облегчённую версию в model_dir. Уже готовая — не трогается."""
    model_dir, url, sha256 = model_dir or MODEL_DIR, url or MODEL_URL, sha256 or MODEL_SHA256
    if all(os.path.exists(os.path.join(model_dir, f)) for f in (*NEEDED, "graph/words.txt")):
        return model_dir
    part, tmp = model_dir + ".zip.part", model_dir + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        digest = hashlib.sha256()
        with urllib.request.urlopen(url, timeout=60) as resp, open(part, "wb") as out:
            while chunk := resp.read(1 << 20):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != sha256:
            raise ValueError("контрольная сумма модели не совпала — файл повреждён или подменён")
        with zipfile.ZipFile(part) as z:
            root = z.namelist()[0].split("/")[0]
            for name in NEEDED:                      # только известные файлы — никаких путей из архива
                target = os.path.join(tmp, *name.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(f"{root}/{name}") as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
            with z.open(f"{root}/graph/Gr.fst") as src:
                words = _read_words(src)
        with open(os.path.join(tmp, "graph", "words.txt"), "w", encoding="utf-8") as f:
            f.writelines(f"{w} {k}\n" for w, k in words.items())
        shutil.rmtree(model_dir, ignore_errors=True)
        os.replace(tmp, model_dir)
        return model_dir
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if os.path.exists(part):
            os.remove(part)


class WakeWord:
    """Детектор на все сессии прослушивания: модель грузится с первой сессией и выгружается с последней."""

    def __init__(self):
        self.model = None
        self.vosk = None
        self.users = 0
        self.state = "выключен" if not ENABLED else "не загружен"
        self.stats = {"checked": 0, "heard": 0}
        self._task = None
        self._lock = threading.Lock()            # распознаём по одной фразе — CPU на хостинге мало

    def acquire(self):
        """Началась сессия прослушивания: загружаем модель в фоне (в первый раз — со скачиванием)."""
        self.users += 1
        if ENABLED and self.model is None and (self._task is None or self._task.done()):
            self._task = asyncio.get_running_loop().create_task(self._load())

    def release(self):
        """Сессия закончилась: без слушающих сессий модель не держим в памяти."""
        self.users = max(0, self.users - 1)
        if not self.users and self.model is not None:
            self.model = None
            self.state = "не загружен"
            print("[wake] Модель выгружена из памяти")

    async def _load(self):
        self.state = "загружается"
        try:
            vosk, model = await asyncio.to_thread(self._open)
        except Exception as e:
            self.state = f"не работает ({type(e).__name__}: {e})"
            print(f"[wake] Детектор «Базарчик» не запустился, все фразы распознаёт Whisper: {self.state}")
            return
        if not self.users:                       # пока грузилась, все сессии закончились
            self.state = "не загружен"
            return
        self.vosk, self.model, self.state = vosk, model, "работает"
        print("[wake] Детектор «Базарчик» готов: в Whisper уходят только фразы с обращением")

    @staticmethod
    def _open():
        import vosk
        vosk.SetLogLevel(-1)
        started = time.monotonic()
        fresh = not os.path.exists(os.path.join(MODEL_DIR, "graph", "words.txt"))
        path = prepare_model()
        if fresh:
            print(f"[wake] Модель скачана и подготовлена за {time.monotonic() - started:.1f} с → {path}")
        print("[wake] Загружаю модель. Строка Vosk «Fst::Read: Can't open file …/Gr.fst» — норма: "
              "этот файл удалён специально, чтобы модель занимала меньше памяти")
        started = time.monotonic()
        model = vosk.Model(path)
        print(f"[wake] Модель загружена за {time.monotonic() - started:.1f} с; {diag.report()}")
        return vosk, model

    def _spot(self, model, audio: bytes) -> list:
        with self._lock:
            rec = self.vosk.KaldiRecognizer(model, 16000, GRAMMAR)
            rec.SetWords(True)
            rec.AcceptWaveform(audio)
            result = json.loads(rec.FinalResult())
        return [(w["word"], w["start"]) for w in result.get("result", [])]

    async def heard(self, pcm: bytes, label: str = "") -> bool:
        """Есть ли в начале фразы «Базарчик». Детектор не готов — True: пусть решает Whisper, как раньше.
        label («#12 Nikita (2.4 с)») — для строки в логе. В лог попадает только то, что услышал детектор:
        его словарь — «базар», «чик» и [unk] (всё остальное), так что содержание фразы туда не утекает."""
        model = self.model
        if model is None:
            if label:
                print(f"[wake] {label}: детектор {self.state} → фраза идёт в Whisper")
            return True
        audio = to_16k_mono(pcm[: int(WINDOW_SEC * 48000) * 4])
        started = time.monotonic()
        try:
            words = await asyncio.to_thread(self._spot, model, audio)
        except Exception as e:
            print(f"[wake] {label}: ошибка детектора, фраза уходит в Whisper: {e!r}")
            return True
        hit = called(words)
        self.stats["checked"] += 1
        self.stats["heard"] += hit
        if label:
            got = ", ".join(f"{w} {s:.1f}с" for w, s in words) or "тишина"
            print(f"[wake] {label}: {got} → {'к боту' if hit else 'не к боту'} "
                  f"({(time.monotonic() - started) * 1000:.0f} мс)")
        return hit

    def report(self) -> str:
        s = self.stats
        return f"; детектор {self.state}: проверено {s['checked']}, с обращением {s['heard']}"


detector = WakeWord()
