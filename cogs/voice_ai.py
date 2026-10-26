import asyncio
import os
import re
import tempfile
import time
from collections import defaultdict, deque
import discord
from discord.ext import commands
import edge_tts
import ai
import reply_modes
from config import AI_SYSTEM_PROMPT, TTS_SETTINGS
from views import OwnedView, GREEN, GREY
from data import AUTO_CHANNELS, YOUR_USER_ID

AUDIO_FILE = os.path.abspath("greeting.mp3")
_greeting_lock = asyncio.Lock()
HISTORY_MESSAGES = 12   # сколько последних реплик (вопросы + ответы) ИИ помнит на сервер


def generate_greeting():
    if not os.path.exists(AUDIO_FILE):
        try:
            from gtts import gTTS
            tts = gTTS("Привіт Юра Яковенко", lang="uk")
            tts.save(AUDIO_FILE)
            print(f"[AUDIO] Файл создан: {AUDIO_FILE}")
        except Exception as e:
            print(f"[AUDIO] Ошибка создания файла: {e}")


ROOM_SEPARATORS = {"🔊 Poslucháreň": "_ZP"}   # имя комнаты → что ставить перед номером (по умолчанию пробел)
ROOM_COOLDOWN   = 10                          # секунд между комнатами одного участника


def _room_pattern(entry_name: str) -> tuple:
    """Имя входа → (база, разделитель): «🔊Create Poslucháreň» → комнаты «🔊 Poslucháreň_ZP1»,
    «🎮Create Hračka» → «🎮 Hračka 1»."""
    base = " ".join(entry_name.replace("Create", "", 1).split())
    return base, ROOM_SEPARATORS.get(base, " ")


def _room_number(name: str, base: str, sep: str):
    """Номер комнаты, если имя — ровно «база + разделитель + число», иначе None."""
    m = re.fullmatch(re.escape(base + sep) + r"(\d+)", name)
    return int(m.group(1)) if m else None


def _room_kinds(guild):
    """(id категории, база, разделитель) для каждого входа: где живут его комнаты и как они называются."""
    for entry_id, cat_id in AUTO_CHANNELS.items():
        entry = guild.get_channel(entry_id)
        if entry is not None:
            yield (cat_id or entry.category_id, *_room_pattern(entry.name))


def _is_room(channel) -> bool:
    return any(channel.category_id == cat_id and _room_number(channel.name, base, sep) is not None
               for cat_id, base, sep in _room_kinds(channel.guild))


def _http_err(e) -> str:
    """Коротко об ошибке Discord для лога: статус и код, а вместо HTML-страницы Cloudflare — пометка о бане."""
    text = e.text if isinstance(e.text, str) else ""
    if text.lstrip().startswith("<"):
        return f"{e.status}, HTML-ответ Cloudflare — похоже на бан IP (1015)"
    return f"{e.status} (код {e.code}){': ' + text[:120] if text else ''}"


def answer_embed(user, question: str, reply: str) -> discord.Embed:
    embed = discord.Embed(description=reply[:4000], color=discord.Color.teal())
    embed.set_author(name=f"{user.display_name}: {question}"[:256], icon_url=user.display_avatar.url)
    embed.set_footer(text="🤖 ИИ • !aiclear — очистить память")
    return embed


UNTRANSLIT_PROMPT = (
    "Тебе дают текст из чата, написанный транслитом: русские или украинские слова латиницей («privet kak dela», "
    "«4to delaesh», «shcho robysh», «ya tebya ne slyshu»). Перепиши его обычными буквами — кириллицей, на том же "
    "языке (русский — по-русски, украинский — по-украински), с правильной орфографией. Сохрани слова, их порядок, "
    "пунктуацию, эмодзи, ссылки, @упоминания и ники. Слова, которые и так написаны правильно — английские, "
    "словацкие, кириллица, — не меняй. Не переводи на другой язык, не исправляй смысл, не добавляй пояснений. "
    "Ответь только переписанным текстом.")

# Голоса озвучки по языку ответа: (женский, мужской)
TTS_VOICES = {
    "ru": ("ru-RU-SvetlanaNeural", "ru-RU-DmitryNeural"),
    "uk": ("uk-UA-PolinaNeural",   "uk-UA-OstapNeural"),
    "sk": ("sk-SK-ViktoriaNeural", "sk-SK-LukasNeural"),
    "en": ("en-US-JennyNeural",    "en-US-GuyNeural"),
}
MALE_VOICES = {male for _, male in TTS_VOICES.values()}
ALL_VOICES  = {v for pair in TTS_VOICES.values() for v in pair}
UK_LETTERS  = set("іїєґ")
RU_LETTERS  = set("ыэёъ")
SK_LETTERS  = set("áäčďéíĺľňóôŕšťúýž")


def detect_lang(text: str) -> str:
    """Язык ответа по буквам: кириллица — русский или украинский, латиница — словацкий или английский."""
    letters = [c for c in text.lower() if c.isalpha()]
    if not letters:
        return "ru"
    cyrillic = sum("а" <= c <= "я" or c in "ёіїєґ" for c in letters)
    if cyrillic * 2 >= len(letters):
        uk = sum(c in UK_LETTERS for c in letters)
        return "uk" if uk > sum(c in RU_LETTERS for c in letters) else "ru"
    return "sk" if any(c in SK_LETTERS for c in letters) else "en"


def voice_for(text: str) -> str:
    """Голос под язык ответа; пол — как у голоса, выбранного через !aivoice."""
    chosen, lang = TTS_SETTINGS["voice"], detect_lang(text)
    if chosen in ALL_VOICES and chosen.startswith(TTS_VOICES[lang][0][:3]):
        return chosen                      # выбранный голос уже нужного языка
    female, male = TTS_VOICES[lang]
    return male if chosen in MALE_VOICES else female


_hushed: dict = {}          # guild_id → сколько раз озвучку обрывали «Базарчик, стоп»


def stop_playback(vc):
    """Обрывает только звук бота. VoiceClient.stop() в py-cord 2.8 останавливает ещё и приём голоса
    (_reader.stop()) — после «Базарчик, стоп» бот глох до переподключения (живой войс 19.10)."""
    if not hasattr(vc, "_player"):
        return vc.stop()                    # другая версия py-cord — как умеет
    if vc._player is not None:
        vc._player.stop()
    future = getattr(vc, "_player_future", None)
    if future:
        vc.loop.call_soon_threadsafe(vc._set_future_result_if_pending, future, None)
    vc._player, vc._player_future = None, None


def hush(vc) -> bool:
    """«Базарчик, стоп»: обрывает фразу, которая звучит, и выбрасывает всё, что ждёт очереди.
    True — бот в этот момент говорил."""
    gid = getattr(getattr(vc, "guild", None), "id", None)
    _hushed[gid] = _hushed.get(gid, 0) + 1
    playing = vc.is_playing()
    if playing:
        stop_playback(vc)
    return playing


async def say(vc: discord.VoiceClient, text: str):
    """Озвучивает текст в уже подключённом войсе (edge-tts → FFmpeg); ждёт, пока доиграет прошлая фраза.
    В логах — голос, длина, время синтеза, ожидание очереди и сколько фраза звучала.
    Фраза, поставленная в очередь до «Базарчик, стоп» (hush), не звучит."""
    gid = getattr(getattr(vc, "guild", None), "id", None)
    epoch = _hushed.get(gid, 0)
    voice = voice_for(text)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tts_path = f.name
    started = time.monotonic()
    try:
        await edge_tts.Communicate(text[:1500], voice).save(tts_path)
    except Exception as e:
        print(f"[tts] {voice}: синтез не удался за {time.monotonic() - started:.1f} с: {e!r}")
        try: os.unlink(tts_path)
        except OSError: pass
        raise
    synth = time.monotonic() - started
    while vc.is_playing() and _hushed.get(gid, 0) == epoch:
        await asyncio.sleep(0.3)
    if _hushed.get(gid, 0) != epoch:
        print(f"[tts] {voice}: {len(text)} символов — не озвучено, остановили «стоп»")
        try: os.unlink(tts_path)
        except OSError: pass
        return
    queued = time.monotonic() - started - synth
    print(f"[tts] {voice}: {len(text)} символов, синтез {synth:.1f} с"
          + (f", ждал очередь {queued:.1f} с" if queued >= 0.3 else ""))
    playing = time.monotonic()

    def after_play(error):
        took = time.monotonic() - playing
        slow = took > 3 * (len(text) / 10 + 2)        # обычно ~10 символов в секунду
        print(f"[tts] {voice}: прозвучало за {took:.1f} с"
              + (f", ошибка: {error!r}" if error else "")
              + (" — подозрительно долго для такой фразы: плеер подвисал" if slow else ""))
        try: os.unlink(tts_path)
        except OSError: pass
    vc.play(discord.FFmpegPCMAudio(tts_path), after=after_play)


class VoiceAICog(commands.Cog):
    def __init__(self, bot):
        self.bot              = bot
        self._shared_histories = defaultdict(lambda: deque(maxlen=HISTORY_MESSAGES))
        self._room_locks       = defaultdict(asyncio.Lock)   # категория → номер выбирают по очереди
        self._room_made_at     = {}                          # участник → когда ему последний раз создали комнату
        self._room_no_perms    = set()                       # категории, про нехватку прав в которых уже писали

    # ── AI Chat ───────────────────────────────────────────────
    # К ИИ в чате обращаются упоминанием: «@BazarčikPM вопрос или просьба» (cogs/jarvis.py, on_message).
    async def answer(self, memory_key: int, name: str, question: str, user_id: int = None) -> str:
        """Ответ ИИ с общей памятью сервера — для обращений в чате, голосовых сообщений и войса.
        Манера — по режиму автора (!режим): стандартный, язык админов (транслит) или режим Юрчика.
        Возвращает reply_modes.Answer: текст для чата, .speech — для голоса."""
        history = self._shared_histories[memory_key]
        mode = reply_modes.mode_of(memory_key, user_id) if user_id is not None else reply_modes.DEFAULT
        user_message = {"role": "user", "content": f"[{name}]: {question}"}
        system = reply_modes.system_prompt(AI_SYSTEM_PROMPT, mode)
        reply = await ai.chat([{"role": "system", "content": system}, *history, user_message])
        self.remember(memory_key, name, question, reply)
        if mode != reply_modes.DEFAULT:
            print(f"[ai] {name}: ответ в режиме {mode}")
        return reply_modes.present(mode, reply)

    def remember(self, memory_key: int, name: str, question: str, reply: str):
        """Добавляет реплику в общую память — так ИИ помнит и то, что бот сделал по голосовой команде."""
        self._shared_histories[memory_key].extend([{"role": "user", "content": f"[{name}]: {question}"},
                                                   {"role": "assistant", "content": reply}])

    def recent(self, memory_key: int, count: int) -> list:
        return list(self._shared_histories[memory_key])[-count:]

    @commands.command(name="join", aliases=["j"], brief="Позвать бота в голосовой канал")
    async def voice_join(self, ctx):
        if not ctx.author.voice:
            await ctx.send("❌ Сначала зайди в голосовой канал!", delete_after=5); return
        if ctx.guild.voice_client:
            await ctx.send(f"⚠️ Я уже в канале. Пиши {self.bot.user.mention} и вопрос.", delete_after=5); return
        try:
            await asyncio.wait_for(ctx.author.voice.channel.connect(), timeout=15)
        except Exception as e:
            await ctx.send(f"❌ Не удалось подключиться к войсу: {e}", delete_after=8); return
        await ctx.send(f"✅ Подключился! Пиши {self.bot.user.mention} и вопрос — отвечу ещё и голосом. "
                       "А чтобы я слушал войс — `!listen`.")

    @commands.command(name="leave", aliases=["l", "выйти"], brief="Выгнать бота из войса")
    async def voice_leave(self, ctx):
        if ctx.guild.voice_client:
            await ctx.guild.voice_client.disconnect()
            await ctx.send("👋 Вышел из голосового канала.")
        else:
            await ctx.send("❌ Я не в канале.", delete_after=5)

    @commands.command(name="aiclear", brief="Очистить общую память чата")
    async def voice_clear(self, ctx):
        self._shared_histories[ctx.guild.id].clear()
        await ctx.send("🗑️ Общая память чата очищена. Бот всех забыл!")

    @commands.command(name="aivoice", brief="Сменить голос AI",
                      help="`!aivoice` — список голосов, `!aivoice имя` — выбрать. Язык озвучки бот подбирает "
                           "сам по ответу (русский, украинский, словацкий, английский), а выбранный голос задаёт пол.")
    async def voice_change(self, ctx, *, voice_name: str = None):
        if not voice_name:
            await ctx.send(
                "🗣️ **Голоса озвучки** (язык подбирается сам по ответу, выбор задаёт пол):\n"
                "• 🇷🇺 `ru-RU-SvetlanaNeural` (ж) • `ru-RU-DmitryNeural` (м)\n"
                "• 🇺🇦 `uk-UA-PolinaNeural` (ж) • `uk-UA-OstapNeural` (м)\n"
                "• 🇸🇰 `sk-SK-ViktoriaNeural` (ж) • `sk-SK-LukasNeural` (м)\n"
                "• 🇺🇸 `en-US-JennyNeural` (ж) • `en-US-GuyNeural` (м)\n\n"
                f"Сейчас: `{TTS_SETTINGS['voice']}`. Пример: `!aivoice ru-RU-DmitryNeural`"
            )
            return
        match = next((v for v in ALL_VOICES if v.lower() == voice_name.strip().lower()), None)
        if match is None:
            await ctx.send("❌ Нет такого голоса. Список: `!aivoice`", delete_after=10)
            return
        TTS_SETTINGS["voice"] = match
        await ctx.send(f"✅ Голос изменён на `{match}` — "
                       f"{'мужской' if match in MALE_VOICES else 'женский'} во всех языках озвучки.")

    # ── Транслит → обычные буквы ──────────────────────────────
    @commands.command(name="translit", aliases=["транслит", "детранслит", "untranslit"],
                      brief="Переписать транслит обычными буквами",
                      help="`!транслит privet kak dela` → «привет как дела»: русские и украинские слова латиницей — "
                           "кириллицей, на том же языке. Ответь командой `!транслит` на чужое сообщение — бот "
                           "перепишет его. Английские и словацкие слова, ники и ссылки не трогает.\n"
                           "Словами: «@BazarčikPM переведи с транслита: privet kak dela».")
    async def translit(self, ctx, *, text: str = None):
        source = ctx.author
        if not (text or "").strip():                  # ответ на сообщение — переписываем его
            ref = getattr(ctx.message, "reference", None)
            msg = getattr(ref, "resolved", None) if ref is not None else None
            if msg is None and ref is not None and ref.message_id:
                try:
                    msg = await ctx.channel.fetch_message(ref.message_id)
                except discord.HTTPException:
                    msg = None
            text = getattr(msg, "content", "") if isinstance(msg, discord.Message) else ""
            source = getattr(msg, "author", source)
        if not text.strip():
            return await ctx.send("❌ Напиши текст: `!транслит privet kak dela` — или ответь командой `!транслит` "
                                  "на сообщение.", delete_after=10)
        try:
            result = (await ai.ask(UNTRANSLIT_PROMPT, text[:1500], max_tokens=800, temperature=0)).strip()
        except ai.AIError as e:
            return await ctx.send(f"❌ {e}", delete_after=15)
        print(f"[translit] {ctx.author.display_name}: {len(text)} симв. → {len(result)} симв.")
        e = discord.Embed(description=result[:4000] or "—", color=discord.Color.teal())
        e.set_author(name=f"🔤 Из транслита: {source.display_name}"[:256], icon_url=source.display_avatar.url)
        await ctx.send(embed=e)

    # ── Режим ответа ──────────────────────────────────────────
    @commands.command(name="mode", aliases=["режим"], brief="Режим ответа ИИ: стандартный, язык админов, Юрчик",
                      help="`!режим` — твой режим и кнопки, чтобы сменить. `!режим юрчик` / `!режим админ` / "
                           "`!режим стандарт` — сменить свой.\n"
                           "Администраторам: `!режим @user` — режим участника, `!режим @user юрчик` — сменить ему, "
                           "`!режим list` — у кого какой.\n"
                           "Режимы: 🗣️ стандартный (на языке собеседника), 🔤 язык админов (транслит латиницей), "
                           "🤪 режим Юрчика (в его манере).\n"
                           "Словами: «@BazarčikPM отвечай мне как юрчик», «включи Пете язык админов».")
    @commands.guild_only()
    async def reply_mode(self, ctx, *, args: str = ""):
        from cogs.aliases import is_admin
        from names import find_member
        if args.strip().lower() in ("list", "все", "всё", "all", "список"):
            if not is_admin(ctx.author, ctx.channel):
                return await ctx.send("❌ Список режимов смотрят только администраторы. Свой — `!режим`.",
                                      delete_after=10)
            rows = []
            for uid, mode in sorted(reply_modes.modes_on(ctx.guild.id).items()):
                member = ctx.guild.get_member(uid)
                rows.append(f"{reply_modes.label(mode)} — {member.mention if member else f'участник {uid}'}")
            e = discord.Embed(title="🎭 Режимы ответа", color=discord.Color.teal(),
                              description="\n".join(rows) or "У всех стандартный.")
            return await ctx.send(embed=e)
        mode, who = reply_modes.parse_mode(args)
        target = ctx.author
        if who:
            m = re.fullmatch(r"<@!?(\d+)>", who.strip())
            if m:
                target = ctx.guild.get_member(int(m.group(1)))
            else:
                try:
                    target = find_member(ctx.guild, who, ctx.author)
                except LookupError:
                    return await ctx.send(f"❌ Не нашёл участника «{who}».", delete_after=10)
                except ValueError as e:
                    return await ctx.send(f"❌ Не понял, кого именно: {e}?", delete_after=10)
            if target is None:
                return await ctx.send("❌ Не нашёл такого участника.", delete_after=10)
        if target.id != ctx.author.id and not is_admin(ctx.author, ctx.channel):
            return await ctx.send("❌ Чужой режим смотрят и меняют только администраторы. Свой — `!режим`.",
                                  delete_after=10)
        if mode is not None:
            reply_modes.set_mode(ctx.guild.id, target.id, mode)
            print(f"[ai] {ctx.author.display_name}: режим {target.display_name} → {mode}")
        await ctx.send(embed=mode_embed(ctx.guild.id, target, changed=mode is not None),
                       view=ModeView(ctx.author, target))

    # ── Авто-комнаты ──────────────────────────────────────────
    async def _open_room(self, member, entry):
        """Зашёл во вход «Create…» — создать ему комнату с первым свободным номером и перекинуть туда."""
        guild    = member.guild
        who      = f"{member.display_name} ({member.id})"
        print(f"[voice] {who} зашёл во вход «{entry.name}»")
        cat_id   = AUTO_CHANNELS[entry.id] or entry.category_id
        category = guild.get_channel(cat_id) if cat_id else None
        if category is None:
            print(f"[voice] Категория {cat_id} для входа «{entry.name}» ({entry.id}) не найдена — комнату не создаю")
            return
        perms = category.permissions_for(guild.me)
        if not (perms.manage_channels and perms.move_members):
            if category.id not in self._room_no_perms:   # заведомо получим 403 — не дёргаем API зря
                self._room_no_perms.add(category.id)
                missing = [p for p, ok in (("Manage Channels", perms.manage_channels),
                                           ("Move Members", perms.move_members)) if not ok]
                print(f"[voice] Нет прав {', '.join(missing)} в категории «{category.name}» — "
                      f"авто-комнаты там не создаю (сообщаю один раз до перезапуска)")
            return
        now = time.monotonic()
        since = now - self._room_made_at.get(member.id, 0)
        if since < ROOM_COOLDOWN:
            print(f"[voice] {who}: прошлая комната {since:.1f} с назад, лимит {ROOM_COOLDOWN} с — "
                  f"новую не создаю, остаётся во входе")
            return                                # прыгает во вход и обратно — не плодим каналы
        self._room_made_at[member.id] = now

        base, sep = _room_pattern(entry.name)
        # Под замком до самого перекида: следующий вошедший увидит уже созданную комнату и возьмёт другой номер
        async with self._room_locks[category.id]:
            waited = time.monotonic() - now
            if waited > 0.5:
                print(f"[voice] {who} ждал очереди на комнату {waited:.1f} с")
            if member.voice is None or member.voice.channel != entry:
                print(f"[voice] {who} ушёл из входа, пока ждал очереди — комнату не создаю")
                return
            taken = {_room_number(ch.name, base, sep) for ch in category.voice_channels} - {None}
            num = 1
            while num in taken: num += 1
            name = f"{base}{sep}{num}"
            started = time.monotonic()
            try:
                # права сразу как у категории — без отдельного запроса на синхронизацию
                room = await guild.create_voice_channel(name, category=category, overwrites=category.overwrites)
            except discord.HTTPException as e:
                print(f"[voice] Не создал комнату «{name}» для {who}: {_http_err(e)}")
                return
            created = time.monotonic()
            try:
                await member.move_to(room)
            except discord.HTTPException as e:
                print(f"[voice] Не перекинул {who} в «{name}»: {_http_err(e)} — удаляю комнату")
                try: await room.delete()          # иначе пустая комната так и останется висеть
                except discord.HTTPException as e2: print(f"[voice] Не удалил брошенную «{name}»: {_http_err(e2)}")
                return
            print(f"[voice] {who} → «{name}» ({room.id}) в «{category.name}»: создание "
                  f"{(created - started) * 1000:.0f} мс, перекид {(time.monotonic() - created) * 1000:.0f} мс; "
                  f"заняты номера {sorted(taken) or 'нет'}")

    async def _close_room_if_empty(self, channel, member):
        await asyncio.sleep(5)
        ch = channel.guild.get_channel(channel.id)
        if ch is None:
            return                                # уже удалили (другой уход или руками)
        if ch.members:
            return
        try:
            await ch.delete()
            print(f"[voice] Удалил опустевшую «{ch.name}» ({ch.id}), последним вышел {member.display_name}")
        except discord.NotFound: pass
        except discord.HTTPException as e: print(f"[voice] Не удалил «{ch.name}»: {_http_err(e)}")

    @commands.Cog.listener()
    async def on_ready(self):
        """Пустые комнаты, оставшиеся с прошлого запуска, — удалить: уходов из них уже не будет."""
        for guild in self.bot.guilds:
            empty = [ch for ch in guild.voice_channels if not ch.members and _is_room(ch)]
            deleted = 0
            for ch in empty:
                try:
                    await ch.delete()
                    deleted += 1
                except discord.HTTPException as e:
                    print(f"[voice] Уборка: не удалил «{ch.name}»: {_http_err(e)}")
            if empty:
                print(f"[voice] Уборка на «{guild.name}»: удалил {deleted} из {len(empty)} пустых авто-комнат "
                      f"({', '.join(ch.name for ch in empty)})")

    # ── Voice state ───────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        moved = (before.channel.id if before.channel else None) != (after.channel.id if after.channel else None)

        # === Создание авто-канала === (только при входе: mute/камера внутри входа — не повод)
        if moved and after.channel and after.channel.id in AUTO_CHANNELS:
            await self._open_room(member, after.channel)
            return

        # === Приветствие Юры ===
        if (member.id == YOUR_USER_ID
                and after.channel is not None
                and (before.channel is None or before.channel.id != after.channel.id)):

            if _greeting_lock.locked():
                return
            listen = self.bot.get_cog("VoiceListenCog")
            if listen is not None and listen.is_listening(member.guild.id):
                return                         # бот сейчас слушает войс — не переподключаемся ради приветствия

            async with _greeting_lock:
                await asyncio.sleep(1)
                channel = member.voice.channel if member.voice else None
                if channel is None: return

                for vc_old in list(self.bot.voice_clients):
                    try: await vc_old.disconnect(force=False)
                    except Exception: pass
                await asyncio.sleep(2)

                vc = None
                greeted = False
                try:
                    vc = await asyncio.wait_for(channel.connect(reconnect=False), timeout=15.0)
                    await asyncio.sleep(1)

                    if not os.path.exists(AUDIO_FILE):
                        await asyncio.to_thread(generate_greeting)   # gTTS ходит в сеть синхронно

                    finished = asyncio.Event()
                    loop = asyncio.get_running_loop()
                    def after_play(error):
                        if error: print(f"[AUDIO] Ошибка: {error}")
                        loop.call_soon_threadsafe(finished.set)

                    source = discord.FFmpegPCMAudio(AUDIO_FILE, executable="ffmpeg", options="-loglevel panic")
                    vc.play(source, after=after_play)

                    try:
                        await asyncio.wait_for(finished.wait(), timeout=15.0)
                        greeted = True
                    except asyncio.TimeoutError:
                        print("[AUDIO] Таймаут воспроизведения")

                except asyncio.TimeoutError:
                    print("[AUDIO] Таймаут подключения!")
                except Exception as e:
                    import traceback; print(f"[AUDIO] Ошибка: {e}"); traceback.print_exc()
                finally:
                    if vc and vc.is_connected():
                        await vc.disconnect(force=True)

                if not greeted:
                    ch = member.guild.get_channel(channel.id)
                    if ch:
                        for m in list(ch.members):
                            if m.id != YOUR_USER_ID:
                                try: await m.move_to(None)
                                except Exception: pass

        # === Удаление пустой авто-комнаты ===
        if moved and before.channel and _is_room(before.channel):
            await self._close_room_if_empty(before.channel, member)


def mode_embed(guild_id, target, changed: bool = False) -> discord.Embed:
    mode = reply_modes.mode_of(guild_id, target.id)
    emoji, name, about = reply_modes.MODES[mode]
    others = "\n".join(f"{reply_modes.label(k)} — {v[2]}" for k, v in reply_modes.MODES.items())
    e = discord.Embed(title=f"{'✅ ' if changed else ''}{emoji} {name}", color=discord.Color.teal(),
                      description=f"Так бот отвечает **{target.display_name}**: {about}.\n\n{others}")
    e.set_footer(text="Сменить — кнопкой ниже, «!режим юрчик» или словами: «@BazarčikPM отвечай мне как юрчик»")
    return e


class ModeView(OwnedView):
    """Кнопки режимов: нажимает тот, кто открыл; меняет режим тому, чей он смотрит."""
    deny_text = "Это не твоё меню — открой своё: `!режим`"

    def __init__(self, user, target):
        super().__init__(user, timeout=120)
        self.target = target
        current = reply_modes.mode_of(target.guild.id, target.id)
        for key, (emoji, name, _) in reply_modes.MODES.items():
            self.btn(name, self._pick(key), GREEN if key == current else GREY, emoji=emoji, disabled=key == current)

    def _pick(self, mode: str):
        async def cb(interaction: discord.Interaction):
            reply_modes.set_mode(self.target.guild.id, self.target.id, mode)
            print(f"[ai] {interaction.user.display_name}: режим {self.target.display_name} → {mode} (кнопка)")
            await interaction.response.edit_message(embed=mode_embed(self.target.guild.id, self.target, True),
                                                    view=ModeView(self.user, self.target))
        return cb


def setup(bot):
    bot.add_cog(VoiceAICog(bot))
