"""
voice_listen.py — бот слушает войс и отвечает голосом, когда к нему обращаются «Базарчик, …».

!listen — зайти в твой войс и слушать, !stoplisten — перестать.
Каждый участник записывается отдельно; когда человек замолчал, фраза уходит в Whisper (Groq).
Если фраза начинается с «Базарчик» — ИИ отвечает голосом и дублирует ответ в чат.
Звук живёт только в памяти до распознавания и сразу удаляется; фразы без обращения никуда не пишутся.

Запасной путь — голосовое сообщение в чате, которое начинается с «Базарчик, …»: бот ответит так же.
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
from discord.sinks import Sink
import ai
from cogs.voice_ai import say, answer_embed

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
WAKE_HINT       = "Базарчик, BazarčikPM"
WAKE_RE = re.compile(
    r"^\W*(?:(?:эй|ей|hey|слушай|ну|а)\W+)?(?:баз[аa]р\s?ч\w*|baz[aá]r\s?[cč]h?\w*)[\s,.!?:;…—-]*",
    re.IGNORECASE)


def split_wake(text: str):
    """Вопрос после обращения «Базарчик, …»; None — фраза не к боту, "" — позвали без вопроса."""
    m = WAKE_RE.match(text or "")
    return None if m is None else text[m.end():].strip()


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
        self.frames = 0       # сколько кадров вообще пришло — если 0, приём голоса не работает

    def walk_children(self, with_self: bool = False):
        return iter([self] if with_self else [])

    def write(self, data, user):          # вызывается из потока py-cord, не из event loop
        pcm = getattr(data, "pcm", data)
        if user is None or getattr(user, "bot", False) or not pcm:
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


class ListenSession:
    def __init__(self, cog, vc: discord.VoiceClient, channel):
        self.cog, self.vc, self.channel = cog, vc, channel
        self.guild = vc.guild
        self.loop = asyncio.get_running_loop()
        self.sink = UtteranceSink()
        self.started = self.last_wake = time.monotonic()
        self.alone_since = None
        self.followup: dict = {}          # uid → до какого момента ждём вопрос после «Базарчик?»
        self.stt_times: deque = deque()
        self.tasks: set = set()
        self.warned_quiet = self.warned_limit = self.stopping = False
        self.loop_task = None

    def start(self):
        self.sink.init(self.vc)
        with warnings.catch_warnings():   # py-cord предупреждает о DAVE при каждом старте — сообщаем сами
            warnings.simplefilter("ignore", RuntimeWarning)
            self.vc.start_recording(self.sink, self._on_reader_stop)
        self.loop_task = asyncio.create_task(self._watch())

    def _on_reader_stop(self, error):     # колбэк py-cord из его потока
        if error is not None and not self.stopping:
            print(f"[listen] Приём голоса остановился с ошибкой: {error!r}")
            self.loop.call_soon_threadsafe(self._spawn, self.stop("приём голоса прервался"))

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
                humans = [m for m in self.vc.channel.members if not m.bot]
                self.alone_since = None if humans else (self.alone_since or now)
                if self.alone_since and now - self.alone_since > ALONE_STOP_SEC:
                    return await self.stop("в войсе никого не осталось")
                if now - self.last_wake > IDLE_STOP_SEC:
                    return await self.stop("полчаса никто не обращался")
                if not self.warned_quiet and humans and self.sink.frames == 0 and now - self.started > QUIET_HINT_SEC:
                    self.warned_quiet = True
                    await self.channel.send(
                        "🤔 Пока не слышу ни звука. Если вы говорите, а я молчу — Discord-шифрование голоса (DAVE) "
                        "мешает приёму. Тогда отправьте **голосовое сообщение** «Базарчик, …» в чат — это работает всегда.")
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
        if not self._stt_allowed():
            if not self.warned_limit:
                self.warned_limit = True
                await self.channel.send("⏳ Слишком много разговоров — часть фраз пропускаю, чтобы не упереться "
                                        "в лимиты распознавания.", delete_after=30)
            return
        try:
            text = await ai.transcribe(to_wav(pcm), "speech.wav", hint=WAKE_HINT)
        except ai.AIError as e:
            print(f"[listen] Распознавание не удалось: {e}")
            return
        finally:
            del pcm                       # звук больше нигде не хранится
        question = split_wake(text)
        if question is None:
            if not text or time.monotonic() > self.followup.pop(user.id, 0):
                return                    # обычный разговор — не к боту, расшифровку выбрасываем
            question = text
        elif not question:
            self.followup[user.id] = time.monotonic() + FOLLOWUP_SEC
            try:
                await say(self.vc, "Да? Слушаю.")
            except Exception as e:
                print(f"[listen] Не удалось ответить голосом: {e!r}")
            return
        self.last_wake = time.monotonic()
        await self.cog.reply(self.channel, user, question, self.vc, "🎙️ из войса")

    async def stop(self, reason: str = None, disconnect: bool = True):
        if self.stopping:
            return
        self.stopping = True
        self.cog.sessions.pop(self.guild.id, None)
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

    async def reply(self, channel, user, question: str, vc=None, source: str = ""):
        """Ответ ИИ в чат и, если бот в войсе с автором, голосом."""
        voice_cog = self.bot.get_cog("VoiceAICog")
        if voice_cog is None:
            return
        async with self.locks[channel.guild.id]:
            try:
                reply = await voice_cog.answer(channel.guild.id, user.display_name, question)
            except ai.AIError as e:
                await channel.send(f"❌ {e}", delete_after=15)
                return
            embed = answer_embed(user, question, reply)
            embed.set_footer(text=f"{source} • «Базарчик, …» — чтобы спросить")
            await channel.send(embed=embed)
            if vc is not None and vc.is_connected():
                try:
                    await say(vc, reply)
                except Exception as e:
                    print(f"[listen] Озвучка не удалась: {e!r}")

    @commands.command(
        name="listen", aliases=["слушай"], brief="Бот слушает войс и отвечает на «Базарчик, …»",
        help="`!listen` — бот заходит в твой войс и слушает. Начни фразу с «Базарчик» — он ответит голосом "
             "и продублирует ответ в чат. Можно сказать просто «Базарчик?» и задать вопрос следом.\n"
             "Звук хранится только в памяти до распознавания, фразы без обращения не сохраняются.\n"
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
        e = discord.Embed(title="🎙️ Слушаю войс", color=discord.Color.teal(), description=(
            f"Канал: {voice.channel.mention}\n"
            "Обращайся: **«Базарчик, …»** — отвечу голосом и продублирую в чат.\n\n"
            "🔒 Звук хранится только в памяти до распознавания (Groq Whisper) и сразу удаляется, "
            "фразы без обращения никуда не записываются.\n"
            "Выключить: `!stoplisten`. Сам выключусь, если все уйдут или полчаса никто не обратится."))
        await ctx.send(embed=e)

    @commands.command(name="stoplisten", aliases=["unlisten", "хватит"], brief="Перестать слушать войс")
    @commands.guild_only()
    async def stoplisten(self, ctx):
        session = self.sessions.get(ctx.guild.id)
        if session is None:
            return await ctx.send("❌ Я сейчас не слушаю войс.", delete_after=8)
        await session.stop(f"выключил {ctx.author.display_name}")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Запасной путь: голосовое сообщение «Базарчик, …» в чате — работает и без приёма голоса в войсе."""
        if (message.author.bot or message.guild is None or not message.flags.is_voice_message
                or not message.attachments or not ai.API_KEYS):
            return
        attachment = message.attachments[0]
        if attachment.size > 20 * 1024 * 1024:
            return
        try:
            audio = await attachment.read()
            text = await ai.transcribe(audio, attachment.filename or "voice.ogg", hint=WAKE_HINT)
        except (discord.HTTPException, ai.AIError) as e:
            print(f"[listen] Голосовое сообщение не распознано: {e}")
            return
        question = split_wake(text)
        if not question:
            return                        # голосовое не боту — расшифровку не храним
        vc = message.guild.voice_client
        author_voice = getattr(message.author, "voice", None)
        same_channel = (vc is not None and vc.is_connected() and author_voice is not None
                        and author_voice.channel == vc.channel)
        await self.reply(message.channel, message.author, question, vc if same_channel else None, "🎤 голосовое")


def setup(bot):
    bot.add_cog(VoiceListenCog(bot))
