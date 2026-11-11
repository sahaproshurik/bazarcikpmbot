"""
wake_word.py — локальный детектор обращения «Базарчик» (Vosk), как у Siri и «Окей, Google».

Раньше бот отправлял в Whisper (Groq) каждую фразу из войса, только чтобы узнать, есть ли в ней
обращение: лимит распознаваний кончался за пару минут, а чужие разговоры уходили в облако.
Теперь начало каждой фразы (первые WINDOW_SEC секунд) слушает маленькая офлайн-модель прямо на сервере
бота. В Whisper уходят только фразы, где она услышала «Базарчик», остальные сразу забываются и никуда
не отправляются. Whisper по-прежнему проверяет обращение по тексту — ложное срабатывание стоит один запрос.

Модель vosk-model-small-ru-0.22 скачивается при первом !listen (проверяется SHA-256) и хранится
в облегчённом виде: без большого графа языка (Gr.fst) и со словарём из пары десятков слов — так она
занимает ~80 МиБ памяти вместо ~170. Точности это не стоит: детектор ищет слова по списку (грамматика),
а Gr.fst нужен только для свободной речи — замер полной модели дал те же результаты. Слова «базарчик»
в словаре нет, но модель надёжно слышит его как «базар» + «чик», одинаково на русском, украинском и
словацком. Чтобы похожие фразы («базилик», «базар чиста») не принимались за обращение, в списке есть
слова-соперники (WAKE_MODE=rivals, по умолчанию); WAKE_MODE=classic — прежний список из трёх слов.
В памяти модель держится, только пока бот слушает войс.

Фразы слушают отдельные процессы (WAKE_WORKERS, на 4 ядрах — 2) на ядрах WAKE_CORES (по умолчанию все,
кроме нулевого — оно остаётся боту): несколько человек проверяются одновременно, а бот не тормозит,
пока детектор считает. WAKE_WORKERS=0 — по-старому, в потоке бота.

Если vosk не установлен, модель не скачалась или детектор выключен (LOCAL_WAKE=0), бот работает
как раньше — каждую фразу распознаёт Whisper.
"""
import asyncio
import hashlib
import json
import os
import multiprocessing
import shutil
import struct
import time
import urllib.request
import zipfile
from array import array
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor, ThreadPoolExecutor
import diag

ENABLED      = os.getenv("LOCAL_WAKE", "1").strip().lower() not in ("0", "off", "false", "no")
MODEL_URL    = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
MODEL_SHA256 = "961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4"
MODEL_DIR    = os.path.abspath("vosk-wake-ru")
# Фраза начинается с 0.5 с предзаписи (voice_listen.PREROLL_SEC) — на них сдвинуты оба порога.
WINDOW_SEC   = 2.5           # слушаем только начало фразы: обращение стоит первым, «Слушай, Базарчик» влезает
WAKE_BY_SEC  = 1.7           # «базар» должен начаться не позже — дальше уже не обращение, а середина фразы
MAYBE_TAIL_SEC = 1.0         # одинокий «чик/чек» не позже — возможно, обрывок «Базарчик» (начало срезал микрофон)
# Слова-соперники: похожи на «базар» + «чик», но обращением не являются («базилик», «бабах, и чик»,
# «базар чиста», «базаре»). Когда в словаре только «базар», «чик» и [unk], модели не из чего выбрать, и такие
# фразы она слышит как обращение. С соперниками ложных срабатываний на замерах нет (37/37 против 33/37),
# памяти и CPU столько же. «Базарчику» (укр.) модель слышит как «базар чика» / «базар чику» — это обращение.
RIVALS       = ("чика", "чику", "базара", "базаре", "базары", "базарить", "базарный", "базарная", "чики", "чек",
                "чип", "чих", "чирик", "чиста", "чисто", "базилик", "бизнес", "бабах", "базу", "база", "вокзал")
# WAKE_MODE: rivals — с соперниками (по умолчанию); classic — прежний вариант: только «базар», «чик», [unk]
# Режим: (словарь Vosk, с чего начинается обращение, чем продолжается). Живой войс 19.10: у кого «Базарчик» с
# протяжным «á» или со словацким ударением, модель слышит «базар чек», «база чик», «базары чик», «база чирик» —
# и прежнее правило («базар» + «чик/чика/чику») их выбрасывало. Соперники по-прежнему в словаре: «базар чиста»,
# «база чиста», «базар вокзал», «чик-чирик», «бабах и чик» обращением не становятся.
# Живой войс 11.11 на сервере: «Базарчик» слышался и как «базар чип». Хвосты «чип», «чих», «чики» теперь тоже
# обращение: ложное срабатывание стоит одно локальное распознавание Parakeet (~0.5 с), а не запрос в Groq,
# и обращение по тексту всё равно проверяется.
# Второе обращение — «бот» («Бот, сколько денег», «Ботик, …», «Bot, …»). «Ботик» в словаре модели нет — она слышит
# его как «бот» + что-то. Соперники нужны, чтобы «вот, короче…» не становилось обращением.
# «Ботинок» и «ботаник» в начале фразы — так модель слышит «Ботик» (тест 11.11): тоже «бот», решит текст Parakeet.
BOT_WORDS    = ("бот", "ботинок", "ботаник")
BOT_RIVALS   = ("вот", "кот", "пот", "бок", "боты", "бота", "боту", "ботом", "робот", "работ")
MODES        = {"rivals": (("базар", "чик", "[unk]", *RIVALS, *BOT_WORDS, *BOT_RIVALS),
                           ("базар", "базары", "базара", "база"),
                           ("чик", "чика", "чику", "чек", "чирик", "чип", "чих", "чики")),
                "classic": (("базар", "чик", "[unk]"), ("базар",), ("чик",))}
# Обрывки: одно «база», «базу», «базарить» или одно «чик/чек» в начале фразы. Живой войс 11.11: так детектор слышал
# «Базарчик» со срезанным началом или смазанным концом. Это «возможно» — фразу распознаёт Parakeet на сервере,
# и обращение решает мягкая проверка текста (voice_listen.wake_score), без запроса в Groq.
MAYBE_HEADS  = ("базар", "базары", "базара", "база", "базу", "базарить")
WAKE_GAP_SEC = 1.0           # «чик» начинается не позже чем через секунду после «базар» — иначе это два слова
MODE         = os.getenv("WAKE_MODE", "rivals").strip().lower()
if MODE not in MODES:
    print(f"[wake] WAKE_MODE={MODE!r} не знаю — беру rivals (есть: {', '.join(MODES)})")
    MODE = "rivals"
# в словаре на диске — слова обоих режимов: переключение WAKE_MODE не требует новой модели
KEEP_WORDS   = ("<eps>", "!SIL", "[unk]", "#0", "<s>", "</s>", "базар", "чик", *RIVALS, *BOT_WORDS, *BOT_RIVALS)
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


def grammar(mode: str = None) -> str:
    return json.dumps(list(MODES[mode or MODE][0]), ensure_ascii=False)


def called(words, mode: str = None) -> bool:
    """Обращение — это «базар», сразу за ним «чик», в самом начале фразы. В режиме rivals — и как его слышат
    при другом произношении: «базары/базара/база» + «чика/чику/чек/чирик». «Был на базаре» не считается."""
    _, heads, tails = MODES[mode or MODE]
    return any(a[0] in heads and b[0] in tails and a[1] <= WAKE_BY_SEC and b[1] - a[1] <= WAKE_GAP_SEC
               for a, b in zip(words, words[1:]))


def wake_kind(words, mode: str = None) -> str:
    """Что услышал детектор: «bazarchik» — обращение, «bot» — «бот» в начале фразы, «maybe» — обрывок «Базарчик»
    («база» или «чик» в одиночку), "" — не к боту."""
    mode = mode or MODE
    if called(words, mode):
        return "bazarchik"
    if mode != "rivals":
        return ""
    if any(w in BOT_WORDS and s <= WAKE_BY_SEC for w, s in words):
        return "bot"
    tails = MODES[mode][2]
    if any((w in MAYBE_HEADS and s <= WAKE_BY_SEC) or (w in tails and s <= MAYBE_TAIL_SEC) for w, s in words):
        return "maybe"
    return ""


def _model_words(model_dir: str) -> set:
    try:
        with open(os.path.join(model_dir, "graph", "words.txt"), encoding="utf-8") as f:
            return {line.split(" ", 1)[0] for line in f if line.strip()}
    except OSError:
        return set()


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
    """Скачивает модель и раскладывает облегчённую версию в model_dir. Уже готовая — не трогается.
    Модель прошлой версии (словарь из 8 слов) пересобирается для соперников; не вышло скачать —
    работаем на ней в режиме classic, а не остаёмся без детектора."""
    global MODE
    model_dir, url, sha256 = model_dir or MODEL_DIR, url or MODEL_URL, sha256 or MODEL_SHA256
    if all(os.path.exists(os.path.join(model_dir, f)) for f in (*NEEDED, "graph/words.txt")):
        have = _model_words(model_dir)
        missing = set(MODES[MODE][0]) - have
        if not missing:
            return model_dir
        print(f"[wake] В словаре модели нет {len(missing)} слов режима {MODE} — скачиваю и пересобираю модель")
        try:
            return _build(model_dir, url, sha256)
        except Exception as e:
            if set(MODES["classic"][0]) <= have:
                print(f"[wake] Пересобрать модель не вышло ({type(e).__name__}: {e}) — работаю в режиме classic")
                MODE = "classic"
                return model_dir
            raise
    return _build(model_dir, url, sha256)


def _build(model_dir: str, url: str, sha256: str) -> str:
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


def _cores_setting():
    """Ядра для процессов детектора. WAKE_CORES=«1-3» или «2,3»; по умолчанию на 3+ ядрах — все, кроме нулевого:
    его оставляем боту (Discord, приём голоса, ffmpeg), чтобы распознавание не отнимало у него процессор."""
    raw, total = os.getenv("WAKE_CORES", "").strip(), os.cpu_count() or 1
    if raw.lower() in ("all", "0-"):
        return None
    if raw:
        cores = set()
        for part in raw.split(","):
            a, _, b = part.strip().partition("-")
            cores.update(range(int(a), int(b or a) + 1))
        return cores & set(range(total)) or None
    return set(range(1, total)) if total >= 3 else None


def _workers_setting(cores) -> int:
    """Сколько фраз детектор слушает одновременно. WAKE_WORKERS=0 — по-старому, в потоке бота, без процессов.
    По умолчанию — по процессу на два свободных ядра (на 4 ядрах — 2), на слабом хостинге — 1."""
    raw = os.getenv("WAKE_WORKERS", "").strip()
    if raw.isdigit():
        return int(raw)
    free = len(cores) if cores else (os.cpu_count() or 1)
    return max(1, min(2, free - 1)) if free >= 3 else 1


CORES   = _cores_setting()
WORKERS = _workers_setting(CORES)

# ── Рабочие процессы детектора ────────────────────────────────
# Модель Vosk грузится в каждый процесс один раз (~80 МиБ), фразы распознаются параллельно и не держат GIL бота:
# прежде все фразы шли по одной через замок, и в войсе на пятерых строка [wake] показывала до 1.1 с ожидания.
_worker: dict = {}


def _worker_init(path: str, cores):
    if cores and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, cores)        # Linux: процесс детектора не залезает на ядро бота
        except OSError:
            pass
    import vosk
    vosk.SetLogLevel(-1)
    started = time.monotonic()
    _worker["vosk"], _worker["model"] = vosk, vosk.Model(path)
    _worker["load"] = time.monotonic() - started


def _worker_ping(delay: float) -> tuple:
    """Прогрев: каждый процесс загрузил модель. (pid, за сколько загрузил, на каких ядрах)."""
    time.sleep(delay)
    cores = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None
    return os.getpid(), _worker.get("load", 0.0), cores


def _worker_spot(pcm: bytes, grammar_json: str) -> tuple:
    """(слова, когда начали — time.time(), сколько распознавали). Ресэмплинг — тоже здесь, не в процессе бота.
    Распознаватель создаётся заново: это ~1 мс против ~45 мс на саму фразу (замер), а чужие фразы его не «настраивают»."""
    began = time.time()
    rec = _worker["vosk"].KaldiRecognizer(_worker["model"], 16000, grammar_json)
    rec.SetWords(True)
    rec.AcceptWaveform(to_16k_mono(pcm))
    result = json.loads(rec.FinalResult())
    return [(w["word"], w["start"]) for w in result.get("result", [])], began, time.time() - began


class WakeWord:
    """Детектор на все сессии прослушивания: процессы с моделью запускаются с первой сессией и гасятся с последней."""

    def __init__(self):
        self.pool = None                         # ProcessPoolExecutor (или поток при WAKE_WORKERS=0)
        self.users = 0
        self.state = "выключен" if not ENABLED else "не загружен"
        self.stats = {"checked": 0, "heard": 0, "work": 0.0}
        self._task = None

    @property
    def ready(self) -> bool:
        return self.pool is not None

    def acquire(self):
        """Началась сессия прослушивания: запускаем детектор в фоне (в первый раз — со скачиванием модели)."""
        self.users += 1
        if ENABLED and self.pool is None and (self._task is None or self._task.done()):
            self._task = asyncio.get_running_loop().create_task(self._load())

    def loading(self) -> bool:
        """Модель ещё грузится (или скачивается). Не грузится и не готова — значит, выключена или сломалась."""
        return self._task is not None and not self._task.done()

    def release(self):
        """Сессия закончилась: без слушающих сессий процессы с моделью не держим."""
        self.users = max(0, self.users - 1)
        if not self.users and self.pool is not None:
            self._drop()
            print("[wake] Детектор выгружен из памяти")

    def _drop(self, why: str = None):
        pool, self.pool = self.pool, None
        self.state = f"не работает ({why})" if why else "не загружен"
        if why:
            print(f"[wake] Детектор «Базарчик» отключён, все фразы распознаёт Whisper: {why}")
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    async def _load(self):
        self.state = "загружается"
        started = time.monotonic()
        try:
            fresh = not os.path.exists(os.path.join(MODEL_DIR, "graph", "words.txt"))
            path = await asyncio.to_thread(prepare_model)
            if fresh:
                print(f"[wake] Модель скачана и подготовлена за {time.monotonic() - started:.1f} с → {path}")
            print("[wake] Загружаю модель. Строка Vosk «Fst::Read: Can't open file …/Gr.fst» — норма: "
                  "этот файл удалён специально, чтобы модель занимала меньше памяти")
            pool, how = self._start(path)
            loop = asyncio.get_running_loop()
            # по заданию на каждый процесс сразу: все загрузят модель до первой фразы, а не на ней
            pings = await asyncio.gather(*(loop.run_in_executor(pool, _worker_ping, 0.3)
                                           for _ in range(max(1, WORKERS))))
        except Exception as e:
            self.state = f"не работает ({type(e).__name__}: {e})"
            print(f"[wake] Детектор «Базарчик» не запустился, все фразы распознаёт Whisper: {self.state}")
            return
        if not self.users:                       # пока грузился, все сессии закончились
            pool.shutdown(wait=False, cancel_futures=True)
            self.state = "не загружен"
            return
        self.pool, self.state = pool, "работает"
        loads = ", ".join(f"{t:.1f} с" for _, t, _ in pings)
        cores = pings[0][2]
        print(f"[wake] Детектор «Базарчик» готов за {time.monotonic() - started:.1f} с: {how}, модель загружена за "
              f"{loads}" + (f", ядра {cores[0]}–{cores[-1]}" if cores else "")
              + f", режим {MODE}; {diag.report()}")

    @staticmethod
    def _start(path: str):
        """Процессы детектора (spawn: без копии памяти и потоков бота) или, при WAKE_WORKERS=0, поток бота."""
        if WORKERS <= 0:
            pool = ThreadPoolExecutor(1, thread_name_prefix="wake", initializer=_worker_init, initargs=(path, None))
            return pool, "в потоке бота (WAKE_WORKERS=0)"
        pool = ProcessPoolExecutor(WORKERS, mp_context=multiprocessing.get_context("spawn"),
                                   initializer=_worker_init, initargs=(path, CORES))
        return pool, f"процессов {WORKERS}"

    async def heard(self, pcm: bytes, label: str = "") -> str:
        """Что в начале фразы (wake_kind): «bazarchik», «bot», «maybe» или "" — не к боту. Детектор не готов —
        «unknown»: пусть решает распознавание текста, как раньше. Пустая строка — ложь, остальное — истина.
        label («#12 Nikita (2.4 с)») — для строки в логе. В лог попадает только то, что услышал детектор:
        его словарь — «базар», «чик», «бот», соперники и [unk] (всё остальное), так что содержание фразы не утекает."""
        pool = self.pool
        if pool is None:
            if label:
                print(f"[wake] {label}: детектор {self.state} → фразу проверит распознавание")
            return "unknown"
        started, sent = time.monotonic(), time.time()
        try:
            words, began, worked = await asyncio.get_running_loop().run_in_executor(
                pool, _worker_spot, pcm[: int(WINDOW_SEC * 48000) * 4], grammar())
        except BrokenExecutor as e:
            self._drop(f"процесс детектора упал ({type(e).__name__})")
            return "unknown"
        except Exception as e:
            print(f"[wake] {label}: ошибка детектора, фразу проверит распознавание: {e!r}")
            return "unknown"
        waited = max(0.0, began - sent)
        kind = wake_kind(words)
        self.stats["checked"] += 1
        self.stats["heard"] += kind in ("bazarchik", "bot")
        self.stats["maybe"] = self.stats.get("maybe", 0) + (kind == "maybe")
        self.stats["work"] += worked
        if label:
            got = ", ".join(f"{w} {s:.1f}с" for w, s in words) or "тишина"
            verdict = {"bazarchik": "к боту", "bot": "«бот» → к боту", "maybe": "возможно, проверит Parakeet",
                       "": "не к боту"}[kind]
            # всего = очередь к свободному процессу детектора + распознавание + пересылка звука между процессами
            print(f"[wake] {label}: {got} → {verdict} "
                  f"({(time.monotonic() - started) * 1000:.0f} мс: очередь {waited * 1000:.0f}, "
                  f"распознавание {worked * 1000:.0f})")
        return kind

    def report(self) -> str:
        s = self.stats
        avg = f", в среднем {s['work'] / s['checked'] * 1000:.0f} мс на фразу" if s["checked"] else ""
        return (f"; детектор {self.state}: проверено {s['checked']}, с обращением {s['heard']}, "
                f"возможно {s.get('maybe', 0)}{avg}")


detector = WakeWord()
