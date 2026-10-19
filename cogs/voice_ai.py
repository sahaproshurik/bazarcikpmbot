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


def hush(vc) -> bool:
    """«Базарчик, стоп»: обрывает фразу, которая звучит, и выбрасывает всё, что ждёт очереди.
    True — бот в этот момент говорил."""
    gid = getattr(getattr(vc, "guild", None), "id", None)
    _hushed[gid] = _hushed.get(gid, 0) + 1
    playing = vc.is_playing()
    if playing:
        vc.stop()
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
        print(f"[tts] {voice}: прозвучало за {time.monotonic() - playing:.1f} с"
              + (f", ошибка: {error!r}" if error else ""))
        try: os.unlink(tts_path)
        except OSError: pass
    vc.play(discord.FFmpegPCMAudio(tts_path), after=after_play)


class VoiceAICog(commands.Cog):
    def __init__(self, bot):
        self.bot              = bot
        self._shared_histories = defaultdict(lambda: deque(maxlen=HISTORY_MESSAGES))

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

    # ── Voice state ───────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):

        # === Создание авто-канала ===
        if after.channel and after.channel.id in AUTO_CHANNELS:
            guild    = member.guild
            category = guild.get_channel(AUTO_CHANNELS[after.channel.id])
            if category is None:
                print(f"[voice] Категория для авто-канала {after.channel.id} не найдена")
                return
            new_name = after.channel.name.replace("Create", "")
            prefix   = "_ZP" if new_name == "🔊 Poslucháreň" else " "

            existing = set()
            for ch in category.voice_channels:
                if ch.name.startswith(new_name + prefix):
                    try: existing.add(int(ch.name.replace(new_name + prefix, "").strip()))
                    except ValueError: pass

            num = 1
            while num in existing: num += 1
            new_ch = await guild.create_voice_channel(name=f"{new_name}{prefix}{num}", category=category)
            await new_ch.edit(sync_permissions=True)
            await member.move_to(new_ch)
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

        # === Удаление пустого канала ===
        if before.channel:
            if before.channel.id in AUTO_CHANNELS: return
            if before.channel.category_id not in AUTO_CHANNELS.values(): return
            if not re.search(r"\d+$", before.channel.name): return

            await asyncio.sleep(5)
            ch = member.guild.get_channel(before.channel.id)
            if ch and len(ch.members) == 0:
                try: await ch.delete()
                except Exception as e: print(f"[ERROR] delete channel: {e}")


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
