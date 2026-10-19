"""
voice_listen.py — бот слушает войс и отвечает голосом, когда к нему обращаются «Базарчик, …».

!listen — зайти в твой войс и слушать, !stoplisten — перестать.
Каждый участник записывается отдельно. Когда человек замолчал, начало фразы слушает локальный детектор
«Базарчик» (wake_word.py, Vosk на сервере бота), и только фразы с обращением уходят в Whisper (Groq).
Если фраза начинается с «Базарчик» — ИИ отвечает голосом и дублирует ответ в чат.
Звук живёт только в памяти до распознавания и сразу удаляется; фразы без обращения никуда не пишутся.

Запасной путь — голосовое сообщение в чате, которое начинается с «Базарчик, …»: бот ответит так же.
Слушает бот один язык сервера (!язык: русский, украинский, словацкий или английский) — Whisper не угадывает язык.
Discord шифрует голос (DAVE), и py-cord пока помечает приём голоса как нестабильный,
а голосовые сообщения работают всегда.
"""
import asyncio
import io
import re
import threading
import time
import warnings
import wave
from array import array
from collections import defaultdict, deque
import discord
from discord.ext import commands
from discord.opus import Decoder as OpusDecoder
from discord.sinks import Sink
import ai
import diag
import wake_word
from cogs.voice_ai import say, answer_embed
from data import guild_config, save_guild_cfg
from names import all_aliases, norm_name

try:
    import davey
except ImportError:
    davey = None
try:
    from discord.voice.receive.reader import PacketDecryptor
    from discord.voice.packets.core import OPUS_SILENCE
except Exception:                 # нет голосовых зависимостей или другая версия py-cord
    PacketDecryptor, OPUS_SILENCE = None, b"\xf8\xff\xfe"

DAVE_MAGIC = b"\xfa\xfa"          # так заканчивается кадр, зашифрованный сквозным шифрованием DAVE


def _decrypt_rtp_fixed(self, packet):
    """Расшифровка входящего голоса: транспорт → срез расширения RTP по его настоящей длине → DAVE.
    В py-cord 2.8.1 расширение срезалось ровно на 8 байт, а после DAVE — второй раз, уже из звука,
    поэтому даже расшифрованные кадры превращались в мусор."""
    if self.mode != "aead_xchacha20_poly1305_rtpsize":
        return PacketDecryptor._bazarcik_original(self, packet)
    packet.adjust_rtpsize()
    result = self.box.decrypt(packet.decrypted_data or packet.data, bytes(packet.header),
                              packet.nonce + b"\x00" * 20)
    payload = result[packet.update_extended_header(result):] if packet.extended else result
    state = self.client._connection
    dave = state.dave_session
    if dave is not None and dave.ready and davey is not None:
        uid = state.ssrc_user_map.get(packet.ssrc) or self.client._ssrc_to_id.get(packet.ssrc)
        if uid:
            try:
                return dave.decrypt(uid, davey.MediaType.audio, payload)
            except Exception:
                pass
    return OPUS_SILENCE if payload[-2:] == DAVE_MAGIC else payload


if (PacketDecryptor is not None and discord.__version__.startswith("2.8")
        and not getattr(PacketDecryptor, "_bazarcik_original", None)):
    PacketDecryptor._bazarcik_original = PacketDecryptor.decrypt_rtp
    PacketDecryptor.decrypt_rtp = _decrypt_rtp_fixed

SAMPLE_RATE     = 48000      # py-cord отдаёт PCM 48 кГц, 16 бит, стерео
BYTES_PER_SEC   = SAMPLE_RATE * 4
SILENCE_SEC     = 0.9        # пауза, после которой фраза считается законченной
MIN_SPEECH_SEC  = 0.6        # короче — покашливание или щелчок
MAX_SPEECH_SEC  = 20         # длиннее не копим: на любой вопрос хватает
VOICE_THRESHOLD = 450        # громкость (RMS), ниже которой кадр считается тишиной
FOLLOWUP_SEC    = 10         # после «Базарчик?» без вопроса ждём продолжение
ALONE_STOP_SEC  = 60         # в войсе никого — выключаемся
IDLE_STOP_SEC   = 30 * 60    # полчаса никто не обращался — выключаемся
STT_LIMIT       = (40, 300)  # не больше 40 распознаваний за 5 минут — бережём лимиты Groq
QUIET_HINT_SEC  = 45         # столько ждём хоть какого-то звука, прежде чем подсказать про DAVE
READY_QUICK_SEC = 3          # готов быстрее — одно сообщение «слушаю»; дольше — «захожу…», потом «готов»
READY_NOTE_SEC  = 20         # детектор всё ещё грузится — говорим «готов», а фразы пока распознаёт Whisper
READY_LATER     = "⏳ Напишу здесь, когда буду готов слушать."
WAKE_HINT       = "Базарчик, BazarčikPM"
HINT_CHARS      = 200        # подсказка Whisper — до 224 токенов, кириллица тратит их быстро: держим с запасом
# Язык, который бот слушает (!язык) — один на сервер. Whisper получает его сам, а не угадывает: на коротких
# фразах угадывание путало русский с английским, словацкий с чешским и стоило до трёх запросов на фразу.
LISTEN_LANGS    = {"ru": "🇷🇺 русский", "uk": "🇺🇦 украинский", "sk": "🇸🇰 словацкий", "en": "🇬🇧 английский"}
LANG_WORDS      = {
    "ru": {"ru", "rus", "russian", "рус", "русский", "русском", "русский язык", "російська", "ruština", "rusky"},
    "uk": {"uk", "ua", "ukr", "ukrainian", "укр", "украинский", "украинском", "українська", "українською",
           "украинская", "ukrajinčina", "ukrajinsky"},
    "sk": {"sk", "svk", "slovak", "словацкий", "словацком", "словацька", "словацькою", "slovenčina", "slovensky",
           "slovencina"},
    "en": {"en", "eng", "english", "англ", "английский", "английском", "англійська", "англійською", "angličtina",
           "anglicky"},
}
DEFAULT_LANG    = "ru"
WAKE_RE = re.compile(
    r"^\W*(?:(?:эй|ей|hey|слушай|ну|а)\W+)?(?:баз[аa]р\s?ч\w*|baz[aá]r\s?[cč]h?\w*)[\s,.!?:;…—-]*",
    re.IGNORECASE)


def split_wake(text: str):
    """Вопрос после обращения «Базарчик, …»; None — фраза не к боту, "" — позвали без вопроса."""
    m = WAKE_RE.match(text or "")
    return None if m is None else text[m.end():].strip()


def listen_lang(guild_id) -> str:
    """Язык, который бот слушает на сервере. Хранится в guild_config: {"guild_id": {"listen_lang": "sk"}}."""
    lang = guild_config.get(str(guild_id), {}).get("listen_lang", DEFAULT_LANG)
    return lang if lang in LISTEN_LANGS else DEFAULT_LANG


def set_listen_lang(guild_id, lang: str):
    guild_config.setdefault(str(guild_id), {})["listen_lang"] = lang
    save_guild_cfg()


def parse_lang(word: str):
    """«словацкий», «sk», «English» → код языка; не язык — None."""
    word = " ".join((word or "").lower().split()).strip(".,!?«»\"'")
    return next((lang for lang, words in LANG_WORDS.items() if word in words), None)


def whisper_hint(guild, members=()) -> str:
    """Подсказка Whisper: как пишутся обращение и имена — люди в войсе, потом прозвища сервера.
    Без неё Whisper записывает имя созвучным словом («Батки»), и Джарвис не находит, о ком речь."""
    hint, seen = WAKE_HINT, set()
    found = [m.display_name for m in members if not getattr(m, "bot", False)]
    for uid, aliases in all_aliases(getattr(guild, "id", None)).items():
        member = guild.get_member(uid) if hasattr(guild, "get_member") else None
        if member is not None:
            found += [member.display_name, *aliases]
    for name in found:
        name = re.sub(r"[^\w\s'’.-]", "", name).strip(" .-")       # без эмодзи и значков в нике
        key = norm_name(name)
        if not key or key in seen or len(hint) + len(name) + 2 > HINT_CHARS:
            continue
        seen.add(key)
        hint += (". " if hint == WAKE_HINT else ", ") + name
    return hint


async def recognize(audio: bytes, filename: str, lang: str = DEFAULT_LANG, waiting: bool = False, info: dict = None,
                    hint: str = WAKE_HINT):
    """Распознаёт фразу на языке сервера и достаёт вопрос к боту: None — фраза не к боту, "" — позвали без вопроса.
    waiting — человек только что сказал «Базарчик?», и следующая фраза — вопрос даже без обращения.
    info — сюда для логов кладутся язык, уверенность Whisper и число запросов (без текста фразы).
    hint — подсказка с именами (whisper_hint); если Groq её не примет, повторяем с одним «Базарчик»."""
    info = {} if info is None else info
    info["requests"] = 1
    try:
        heard = await ai.transcribe(audio, filename, hint=hint, language=lang, detailed=True)
    except ai.AIError as e:
        if hint == WAKE_HINT:
            raise
        print(f"[listen] Подсказка с именами не принята ({e}) — распознаю без неё")
        info["requests"] += 1
        heard = await ai.transcribe(audio, filename, hint=WAKE_HINT, language=lang, detailed=True)
    info.update(lang=lang, score=heard.score)
    question = split_wake(heard.text)
    if question is None and waiting and heard.text:
        question = heard.text
    return question


def whisper_note(info: dict, seconds: float) -> str:
    """«Whisper uk (-0.33), 2 запроса, 0.9 с» — для логов."""
    score = info.get("score")
    lang = f"{info.get('lang')} ({score:.2f})" if score is not None else str(info.get("lang"))
    return f"Whisper {lang}, запросов {info.get('requests', 0)}, {seconds:.1f} с"


def frame_loud(pcm: bytes) -> bool:
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    probe = samples[::8]
    return bool(probe) and (sum(s * s for s in probe) / len(probe)) ** 0.5 >= VOICE_THRESHOLD


def to_wav(pcm: bytes) -> bytes:
    """Стерео 48 кГц → моно WAV в памяти: вдвое меньше трафика на распознавание, без файлов на диске."""
    samples = array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 4])
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(samples[0::2].tobytes())
    return buf.getvalue()


class UtteranceSink(Sink):
    """Копит речь каждого участника в памяти; готовые фразы забирает цикл сессии после паузы."""
    __sink_listeners__ = []   # роутер py-cord 2.8 ждёт этот атрибут, а в базовом Sink его нет

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self.buffers: dict = {}
        self.last_voice: dict = {}
        self.users: dict = {}
        self.decoders: dict = {}          # uid → свой Opus-декодер на каждого говорящего
        self.frames = 0                   # кадров со звуком — если 0, приём голоса не работает
        self.stats = {"packets": 0, "empty": 0, "bad": 0}
        self.last_error = None

    def walk_children(self, with_self: bool = False):
        return iter([self] if with_self else [])

    def is_opus(self) -> bool:
        return True       # берём у py-cord сырой Opus и декодируем сами: битый пакет не уронит весь приём

    def write(self, data, user):          # вызывается из потока py-cord, не из event loop
        try:
            self._write(data, user)
        except Exception as e:            # исключение здесь остановило бы приём целиком
            self.stats["bad"] += 1
            self.last_error = repr(e)

    def _resolve(self, user):
        if user is None or hasattr(user, "display_name"):
            return user
        guild = getattr(self.vc, "guild", None)   # py-cord иногда отдаёт голый Object(id)
        return guild.get_member(user.id) if guild is not None else None

    def _decode(self, uid: int, opus) -> bytes:
        if not opus or opus == OPUS_SILENCE:
            return b""
        decoder = self.decoders.get(uid)
        if decoder is None:
            decoder = self.decoders[uid] = OpusDecoder()
        return decoder.decode(opus, fec=False)

    def _write(self, data, user):
        self.stats["packets"] += 1
        user = self._resolve(user)
        if user is None or getattr(user, "bot", False):
            return
        pcm = getattr(data, "pcm", b"") or self._decode(user.id, getattr(data, "opus", None))
        if not pcm:
            self.stats["empty"] += 1
            return
        self.frames += 1
        loud = frame_loud(pcm)
        with self._lock:
            if user.id not in self.buffers and not loud:
                return                    # тишина до начала речи
            buf = self.buffers.setdefault(user.id, bytearray())
            if len(buf) < MAX_SPEECH_SEC * BYTES_PER_SEC:
                buf.extend(pcm)
            if loud:
                self.last_voice[user.id] = time.monotonic()
            self.users[user.id] = user

    def pop_finished(self) -> list:
        """Фразы тех, кто замолчал дольше SILENCE_SEC. Буферы сразу удаляются из памяти синка."""
        now, done = time.monotonic(), []
        with self._lock:
            for uid, last in list(self.last_voice.items()):
                if now - last >= SILENCE_SEC:
                    pcm = bytes(self.buffers.pop(uid, b""))
                    del self.last_voice[uid]
                    user = self.users.pop(uid)
                    if len(pcm) >= MIN_SPEECH_SEC * BYTES_PER_SEC:
                        done.append((user, pcm))
        return done

    def cleanup(self):
        self.finished = True
        with self._lock:
            self.buffers.clear()
            self.last_voice.clear()
            self.users.clear()
        self.decoders.clear()

    def report(self) -> str:
        s = self.stats
        text = f"пакетов {s['packets']}, со звуком {self.frames}, пустых {s['empty']}, ошибок {s['bad']}"
        return text + (f" (последняя: {self.last_error})" if self.last_error else "")


class ListenSession:
    def __init__(self, cog, vc: discord.VoiceClient, channel):
        self.cog, self.vc, self.channel = cog, vc, channel
        self.guild = vc.guild
        self.loop = asyncio.get_running_loop()
        self.sink = UtteranceSink()
        self.started = self.last_wake = time.monotonic()
        self.alone_since = None
        self.followup: dict = {}          # uid → до какого момента ждём вопрос после «Базарчик?»
        self.min_phrase: dict = {}        # uid → в окне строгого подтверждения фразы короче не распознаём
        self.stt_times: deque = deque()
        self.tasks: set = set()
        self.warned_quiet = self.warned_limit = self.stopping = False
        self.announced = False            # написали ли в чат «готов слушать»
        self.intro = None                 # первое сообщение сессии — его заголовок правим, когда готовы
        self.intro_sent = False           # «готов» пишем только после первого сообщения, не раньше
        self.loop_task = None
        self.restarts = 0
        self.reported_at = self.started
        self.phrase_no = 0                # номер фразы в логах: по нему видно всю её дорогу
        self.minute, self.total = {}, {}  # счётчики для логов: за последнюю минуту и за всю сессию
        self.cpu = diag.CpuMeter()

    def count(self, key: str, n: int = 1):
        for counter in (self.minute, self.total):
            counter[key] = counter.get(key, 0) + n

    @staticmethod
    def counts_note(c: dict) -> str:
        return (f"фраз {c.get('phrases', 0)}, детектор пропустил {c.get('to_bot', 0)}, "
                f"без «Базарчик» (ждали ответ) {c.get('bypass', 0)}, запросов в Whisper {c.get('whisper', 0)}, "
                f"вопросов боту {c.get('questions', 0)}, отсеял Whisper {c.get('dropped', 0)}, "
                f"мимо лимита {c.get('limit', 0)}, коротких в окне подтверждения {c.get('short', 0)}")

    def start(self):
        self.sink.init(self.vc)
        with warnings.catch_warnings():   # py-cord предупреждает о DAVE при каждом старте — сообщаем сами
            warnings.simplefilter("ignore", RuntimeWarning)
            self.vc.start_recording(self.sink, self._on_reader_stop)
        self.loop_task = asyncio.create_task(self._watch())
        wake_word.detector.acquire()      # модель «Базарчик» грузится в фоне, пока она не готова — всё решает Whisper
        humans = sum(not m.bot for m in getattr(self.vc.channel, "members", []))
        print(f"[listen] Старт: {getattr(self.guild, 'name', self.guild.id)} / "
              f"{getattr(self.vc.channel, 'name', self.vc.channel)}, людей {humans}; "
              f"детектор {wake_word.detector.state}; {diag.report()}")

    def dave_ready(self) -> bool:
        """Сквозное шифрование голоса (DAVE): пока обмен ключами не закончен, вместо звука приходит тишина."""
        state = getattr(self.vc, "_connection", None)
        if not getattr(state, "dave_protocol_version", 0):
            return True                    # канал без DAVE — звук расшифровывается сразу
        dave = getattr(state, "dave_session", None)
        return bool(dave is not None and dave.ready)

    def readiness(self) -> tuple:
        """(готов ли слушать, что мешает): «шифрование» или «детектор»."""
        if not self.dave_ready():
            return False, "шифрование"
        if wake_word.detector.loading():
            return False, "детектор"
        return True, ""

    async def announce(self, note: str = ""):
        """«Готов слушать» — отдельным сообщением (правка заголовка не уведомляет), заголовок первого — тоже."""
        self.announced = True
        print(f"[listen] Готов слушать через {time.monotonic() - self.started:.1f} с; детектор "
              f"{wake_word.detector.state}" + (f" ({note})" if note else ""))
        text = f"✅ Готов слушать {self.vc.channel.mention}! Говорите: **«Базарчик, …»**"
        if note:
            text += f"\n{note}"
        try:
            await self.channel.send(text)
        except discord.HTTPException as e:
            print(f"[listen] Не удалось написать «готов слушать»: {e!r}")
        try:                               # заголовок — мелочь: его ошибка не должна ронять прослушивание
            if self.intro is not None and self.intro.embeds:
                embed = self.intro.embeds[0]
                embed.title = "🎙️ Слушаю войс"
                embed.description = (embed.description or "").replace("\n\n" + READY_LATER, "")
                await self.intro.edit(embed=embed)
        except Exception as e:
            print(f"[listen] Не удалось поправить заголовок: {e!r}")

    async def check_ready(self, now: float):
        if self.announced or not self.intro_sent:
            return
        ready, why = self.readiness()
        if ready:
            await self.announce()
        elif why == "детектор" and now - self.started > READY_NOTE_SEC:
            await self.announce("Детектор «Базарчик» ещё загружается — пока распознаю каждую фразу через Whisper, "
                                "отвечать буду чуть медленнее.")

    def _on_reader_stop(self, error):     # колбэк py-cord из его потока
        if error is not None and not self.stopping:
            print(f"[listen] Приём голоса остановился с ошибкой: {error!r} | {self.sink.report()}")
            self.loop.call_soon_threadsafe(self._spawn, self._recover(error))

    async def _recover(self, error):
        """py-cord может уронить приём на одном пакете — перезапускаем запись, но не бесконечно."""
        self.restarts += 1
        if self.restarts > 3 or not self.vc.is_connected():
            return await self.stop(f"приём голоса прервался ({type(error).__name__}: {error})")
        await asyncio.sleep(1)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                self.vc.start_recording(self.sink, self._on_reader_stop)
            print(f"[listen] Приём голоса перезапущен ({self.restarts}/3)")
        except Exception as e:
            await self.stop(f"приём голоса не перезапустился ({e})")

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _watch(self):
        try:
            while not self.stopping:
                await asyncio.sleep(0.25)
                if not self.vc.is_connected():
                    return await self.stop("бот отключился от войса")
                now = time.monotonic()
                await self.check_ready(now)
                humans = [m for m in self.vc.channel.members if not m.bot]
                self.alone_since = None if humans else (self.alone_since or now)
                if self.alone_since and now - self.alone_since > ALONE_STOP_SEC:
                    return await self.stop("в войсе никого не осталось")
                if now - self.last_wake > IDLE_STOP_SEC:
                    return await self.stop("полчаса никто не обращался")
                if now - self.reported_at >= 60:      # статистика приёма в логи — для диагностики
                    self.reported_at = now
                    print(f"[listen] {self.vc.channel}: {self.sink.report()}{wake_word.detector.report()}")
                    print(f"[listen] За минуту: {self.counts_note(self.minute)}; {diag.report(self.cpu)}")
                    self.minute = {}
                if not self.warned_quiet and humans and self.sink.frames == 0 and now - self.started > QUIET_HINT_SEC:
                    self.warned_quiet = True
                    packets = self.sink.stats["packets"]
                    detail = (f"Пакеты от Discord приходят ({packets}), но звук из них не расшифровывается"
                              if packets else "От Discord не пришло ни одного звукового пакета")
                    print(f"[listen] Тишина: {self.sink.report()}")
                    await self.channel.send(
                        f"🤔 Пока не слышу ни звука. {detail} — скорее всего, мешает шифрование голоса Discord (DAVE).\n"
                        "Отправьте **голосовое сообщение** «Базарчик, …» в чат — это работает всегда.")
                for user, pcm in self.sink.pop_finished():
                    self._spawn(self.handle(user, pcm))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[listen] Ошибка цикла прослушивания: {e!r}")
            await self.stop("внутренняя ошибка")

    def _stt_allowed(self) -> bool:
        limit, window = STT_LIMIT
        now = time.monotonic()
        while self.stt_times and now - self.stt_times[0] > window:
            self.stt_times.popleft()
        if len(self.stt_times) >= limit:
            return False
        self.stt_times.append(now)
        return True

    async def handle(self, user, pcm: bytes):
        """Одна фраза: детектор → лимит → Whisper → ответ. В логах — путь фразы под номером, без её текста."""
        self.phrase_no += 1
        tag = f"#{self.phrase_no} {user.display_name}"
        started = time.monotonic()
        self.count("phrases")
        waiting = started <= self.followup.get(user.id, 0)
        if waiting:
            seconds, need = len(pcm) / BYTES_PER_SEC, self.min_phrase.get(user.id, 0)
            if seconds < need:
                self.count("short")
                print(f"[listen] {tag}: фраза {seconds:.1f} с короче {need} с — в окне полного подтверждения "
                      "короткое не распознаю")
                return
            self.count("bypass")
            print(f"[listen] {tag}: фраза {seconds:.1f} с — бот ждёт ответ, идёт без детектора "
                  f"(окно ещё {self.followup[user.id] - started:.0f} с)")
        elif not await wake_word.detector.heard(pcm, f"{tag} ({len(pcm) / BYTES_PER_SEC:.1f} с)"):
            return                        # «Базарчик» не прозвучал — фраза не уходит даже в Whisper
        else:
            self.count("to_bot")
        if not self._stt_allowed():
            self.count("limit")
            print(f"[listen] {tag}: пропущена — лимит {STT_LIMIT[0]} распознаваний за {STT_LIMIT[1] // 60} мин")
            if not self.warned_limit:
                self.warned_limit = True
                await self.channel.send("⏳ Слишком много разговоров — часть фраз пропускаю, чтобы не упереться "
                                        "в лимиты распознавания.", delete_after=30)
            return
        audio = to_wav(pcm)
        del pcm
        info, lang = {}, listen_lang(self.guild.id)
        try:
            question = await recognize(audio, "speech.wav", lang, waiting, info,
                                       whisper_hint(self.guild, getattr(self.vc.channel, "members", [])))
        except ai.AIError as e:
            print(f"[listen] {tag}: распознавание не удалось: {e}")
            return
        finally:
            del audio                     # звук больше нигде не хранится
            self.count("whisper", info.get("requests", 0))
        note = whisper_note(info, time.monotonic() - started)
        if question is None:
            self.count("dropped")
            print(f"[listen] {tag}: {note} — обращения нет, фраза выброшена")
            return                        # обычный разговор — не к боту, расшифровку выбрасываем
        if not question:
            print(f"[listen] {tag}: {note} — позвали без вопроса, жду вопрос {FOLLOWUP_SEC} с")
            self.followup[user.id] = time.monotonic() + FOLLOWUP_SEC
            try:
                await say(self.vc, "Да? Слушаю.")
            except Exception as e:
                print(f"[listen] Не удалось ответить голосом: {e!r}")
            return
        self.count("questions")
        print(f"[listen] {tag}: {note} — вопрос боту (слов: {len(question.split())})")
        self.followup.pop(user.id, None)
        self.last_wake = time.monotonic()
        await self.cog.reply(self.channel, user, question, self.vc, "🎙️ из войса", lang=lang)
        print(f"[listen] {tag}: обработана за {time.monotonic() - started + SILENCE_SEC:.1f} с от конца фразы")

    async def stop(self, reason: str = None, disconnect: bool = True):
        if self.stopping:
            return
        self.stopping = True
        self.cog.sessions.pop(self.guild.id, None)
        print(f"[listen] Стоп ({reason or 'без причины'}): {(time.monotonic() - self.started) / 60:.1f} мин, "
              f"{self.counts_note(self.total)}; {self.sink.report()}")
        wake_word.detector.release()
        try:
            if self.vc.is_recording():
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    self.vc.stop_recording()
        except Exception as e:
            print(f"[listen] stop_recording: {e!r}")
        self.sink.cleanup()
        current = asyncio.current_task()
        for task in list(self.tasks):
            if task is not current:
                task.cancel()
        if self.loop_task is not None and self.loop_task is not current:
            self.loop_task.cancel()
        if disconnect and self.vc.is_connected():
            try:
                await self.vc.disconnect()
            except Exception:
                pass
        if reason:
            try:
                await self.channel.send(f"🔇 Прослушивание выключено: {reason}.")
            except discord.HTTPException:
                pass


class VoiceListenCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sessions: dict = {}                       # guild_id → ListenSession
        self.locks = defaultdict(asyncio.Lock)         # отвечаем по очереди, не перебивая сами себя

    def is_listening(self, guild_id: int) -> bool:
        return guild_id in self.sessions

    def cog_unload(self):
        for session in list(self.sessions.values()):
            asyncio.create_task(session.stop("модуль перезагружен"))

    async def reply(self, channel, user, question: str, vc=None, source: str = "",
                    hint: str = "«Базарчик, …» — чтобы спросить", message=None, lang: str = None):
        """Ответ ИИ в чат и, если бот в войсе с автором, голосом. Сюда приходят и войс, и голосовые,
        и обращения в чате (@бот …) — сначала фразу смотрит Джарвис. lang — язык прослушки для фраз голосом."""
        voice_cog = self.bot.get_cog("VoiceAICog")
        if voice_cog is None:
            return
        async with self.locks[channel.guild.id]:
            jarvis = self.bot.get_cog("JarvisCog")     # просьба что-то сделать — выполняет Джарвис (cogs/jarvis.py)
            if jarvis is not None and await jarvis.handle(channel, user, question, vc, source, message=message, lang=lang):
                return
            started = time.monotonic()
            try:
                reply = await voice_cog.answer(channel.guild.id, user.display_name, question, user_id=user.id)
            except ai.AIError as e:
                print(f"[listen] {user.display_name}: ответ ИИ не получен: {e}")
                await channel.send(f"❌ {e}", delete_after=15)
                return
            print(f"[listen] {user.display_name}: ответ ИИ за {time.monotonic() - started:.1f} с, {len(reply)} символов")
            embed = answer_embed(user, question, reply)
            embed.set_footer(text=f"{source} • {hint}")
            await channel.send(embed=embed)
            if vc is not None and vc.is_connected():
                try:
                    await say(vc, getattr(reply, "speech", reply))   # «язык админов»: голосом — кириллица
                except Exception as e:
                    print(f"[listen] Озвучка не удалась: {e!r}")

    @commands.command(
        name="listen", aliases=["слушай"], brief="Бот слушает войс и отвечает на «Базарчик, …»",
        help="`!listen` — бот заходит в твой войс и слушает. Начни фразу с «Базарчик» — он ответит голосом "
             "и продублирует ответ в чат. Можно сказать просто «Базарчик?» и задать вопрос следом.\n"
             "Звук хранится только в памяти до распознавания, фразы без обращения не сохраняются. "
             "Обращение сначала слышит детектор прямо на сервере бота — в Groq уходят только фразы с «Базарчик».\n"
             "Выключается командой `!stoplisten`, а сам — когда все ушли или полчаса никто не обращался.\n"
             "Если войс не слышно — отправь в чат голосовое сообщение «Базарчик, …».")
    @commands.guild_only()
    async def listen(self, ctx):
        voice = ctx.author.voice
        if voice is None or voice.channel is None:
            return await ctx.send("❌ Сначала зайди в голосовой канал.", delete_after=8)
        if ctx.guild.id in self.sessions:
            channel = self.sessions[ctx.guild.id].vc.channel
            return await ctx.send(f"🎙️ Я уже слушаю {channel.mention}. Выключить: `!stoplisten`", delete_after=10)
        if not ai.API_KEYS:
            return await ctx.send("❌ Не задан ключ Groq (GROQ_API_KEYS) — распознавать речь нечем.", delete_after=10)
        vc = ctx.guild.voice_client
        try:
            if vc is not None and vc.is_connected():
                if vc.channel != voice.channel:
                    await vc.move_to(voice.channel)
            else:
                vc = await asyncio.wait_for(voice.channel.connect(), timeout=15)
        except Exception as e:
            return await ctx.send(f"❌ Не удалось подключиться к войсу: {e}", delete_after=10)
        session = ListenSession(self, vc, ctx.channel)
        try:
            session.start()
        except Exception as e:
            print(f"[listen] Не удалось запустить приём голоса: {e!r}")
            return await ctx.send(
                f"❌ Приём голоса не запустился: `{e}`.\nСкорее всего, мешает шифрование голоса Discord (DAVE). "
                "Отправь **голосовое сообщение** «Базарчик, …» в чат — на него я отвечу.")
        self.sessions[ctx.guild.id] = session
        waited = time.monotonic()
        while not session.readiness()[0] and time.monotonic() - waited < READY_QUICK_SEC and not session.stopping:
            await asyncio.sleep(0.2)
        ready = session.readiness()[0]
        title = "🎙️ Слушаю войс — можно говорить" if ready else "🎙️ Захожу в войс — секунду…"
        e = discord.Embed(title=title, color=discord.Color.teal(), description=(
            f"Канал: {voice.channel.mention}\n"
            "Обращайся: **«Базарчик, …»** — отвечу голосом и продублирую в чат.\n\n"
            "🔒 Звук хранится только в памяти до распознавания (Groq Whisper) и сразу удаляется, "
            "фразы без обращения никуда не записываются."
            + (" «Базарчик» сначала слышит детектор прямо на сервере бота — в Groq уходят только фразы "
               "с обращением.\n" if wake_word.ENABLED else "\n") +
            f"Слушаю на языке: **{LISTEN_LANGS[listen_lang(ctx.guild.id)]}** — сменить: `!язык`.\n"
            "Выключить: `!stoplisten`. Сам выключусь, если все уйдут или полчаса никто не обратится."
            + ("" if ready else "\n\n" + READY_LATER)))
        session.announced = ready
        session.intro = await ctx.send(embed=e)
        session.intro_sent = True
        if ready:
            print(f"[listen] Готов слушать через {time.monotonic() - session.started:.1f} с; "
                  f"детектор {wake_word.detector.state}")

    @commands.command(name="stoplisten", aliases=["unlisten", "хватит"], brief="Перестать слушать войс")
    @commands.guild_only()
    async def stoplisten(self, ctx):
        session = self.sessions.get(ctx.guild.id)
        if session is None:
            return await ctx.send("❌ Я сейчас не слушаю войс.", delete_after=8)
        await session.stop(f"выключил {ctx.author.display_name}")

    @commands.command(
        name="listenlang", aliases=["язык", "lang"], brief="На каком языке бот слушает войс и голосовые",
        help="Бот слушает один язык: русский, украинский, словацкий или английский — так Whisper не путает языки "
             "и распознаёт фразу с первого раза.\n"
             "`!язык` — какой сейчас; `!язык sk` / `!язык словацкий` — сменить (ru, uk, sk, en). "
             "Менять — администраторам. Голосом: «Базарчик, слушай нас на словацком».")
    @commands.guild_only()
    async def listenlang(self, ctx, *, language: str = None):
        from cogs.aliases import is_admin
        current = listen_lang(ctx.guild.id)
        if language is not None:
            lang = parse_lang(language)
            if lang is None:
                return await ctx.send("❌ Такого языка нет. Варианты: `!язык ru`, `!язык uk`, `!язык sk`, `!язык en`.",
                                      delete_after=10)
            if not is_admin(ctx.author, ctx.channel):
                return await ctx.send("❌ Язык прослушки меняют только администраторы.", delete_after=10)
            if lang == current:
                return await ctx.send(f"🎙️ Я и так слушаю на языке: **{LISTEN_LANGS[lang]}**.")
            set_listen_lang(ctx.guild.id, lang)
            print(f"[listen] {ctx.author.display_name}: язык прослушки {current} → {lang}")
            return await ctx.send(f"🎙️ Теперь слушаю на языке: **{LISTEN_LANGS[lang]}**. "
                                  "Фразы на других языках буду понимать плохо.")
        options = "\n".join(f"`!язык {code}` — {name}" for code, name in LISTEN_LANGS.items())
        e = discord.Embed(title=f"🎙️ Слушаю на языке: {LISTEN_LANGS[current]}", color=discord.Color.teal(),
                          description="Войс (`!listen`) и голосовые сообщения распознаю только на этом языке — "
                                      "фразы на других понимаю плохо.\n\n" + options +
                                      "\n\nМенять — администраторам.")
        await ctx.send(embed=e)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Запасной путь: голосовое сообщение «Базарчик, …» в чате — работает и без приёма голоса в войсе."""
        if (message.author.bot or message.guild is None or not message.flags.is_voice_message
                or not message.attachments or not ai.API_KEYS):
            return
        attachment = message.attachments[0]
        if attachment.size > 20 * 1024 * 1024:
            return
        started, info, lang = time.monotonic(), {}, listen_lang(message.guild.id)
        try:
            audio = await attachment.read()
            voice = getattr(message.author, "voice", None)
            people = getattr(getattr(voice, "channel", None), "members", None) or [message.author]
            question = await recognize(audio, attachment.filename or "voice.ogg", lang, info=info,
                                       hint=whisper_hint(message.guild, people))
        except (discord.HTTPException, ai.AIError) as e:
            print(f"[listen] Голосовое сообщение от {message.author.display_name} не распознано: {e}")
            return
        del audio
        result = ("обращения нет, выброшено" if question is None else "только «Базарчик», без вопроса"
                  if not question else f"вопрос боту (слов: {len(question.split())})")
        print(f"[listen] Голосовое от {message.author.display_name} ({attachment.size / 1024:.0f} КБ): "
              f"{whisper_note(info, time.monotonic() - started)} — {result}")
        if not question:
            return                        # голосовое не боту — расшифровку не храним
        vc = message.guild.voice_client
        author_voice = getattr(message.author, "voice", None)
        same_channel = (vc is not None and vc.is_connected() and author_voice is not None
                        and author_voice.channel == vc.channel)
        await self.reply(message.channel, message.author, question, vc if same_channel else None, "🎤 голосовое",
                         lang=lang)


def setup(bot):
    bot.add_cog(VoiceListenCog(bot))
