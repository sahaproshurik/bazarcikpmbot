import asyncio
import os
import re
import tempfile
from collections import defaultdict, deque
import discord
from discord.ext import commands
import edge_tts
import ai
from config import AI_SYSTEM_PROMPT, TTS_SETTINGS
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


async def say(vc: discord.VoiceClient, text: str):
    """Озвучивает текст в уже подключённом войсе (edge-tts → FFmpeg); ждёт, пока доиграет прошлая фраза."""
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tts_path = f.name
    await edge_tts.Communicate(text[:1500], voice_for(text)).save(tts_path)
    while vc.is_playing():
        await asyncio.sleep(0.3)

    def after_play(_):
        try: os.unlink(tts_path)
        except OSError: pass
    vc.play(discord.FFmpegPCMAudio(tts_path), after=after_play)


class VoiceAICog(commands.Cog):
    def __init__(self, bot):
        self.bot              = bot
        self._shared_histories = defaultdict(lambda: deque(maxlen=HISTORY_MESSAGES))

    # ── AI Chat ───────────────────────────────────────────────
    @commands.command(
        name="ask", aliases=["a", "спроси"], brief="Спросить ИИ (бот помнит общий разговор)",
        help="`!ask вопрос` — ИИ отвечает в чате. Если ты в голосовом канале, бот ещё и озвучит ответ.\n"
             "ИИ помнит последние реплики всех участников сервера. Очистить память: `!aiclear`.")
    async def ask_ai(self, ctx, *, question: str):
        status_msg = await ctx.send(f"💬 **{ctx.author.display_name}**: {question}\n⏳ *Думаю…*")
        try:
            reply = await self.answer(ctx.guild.id if ctx.guild else ctx.author.id, ctx.author.display_name, question)
        except ai.AIError as e:
            await status_msg.edit(content=f"💬 **{ctx.author.display_name}**: {question}\n❌ {e}")
            return
        await status_msg.edit(content=None, embed=answer_embed(ctx.author, question, reply))

        if ctx.guild and ctx.author.voice:
            await self._speak(ctx, reply)

    async def answer(self, memory_key: int, name: str, question: str) -> str:
        """Ответ ИИ с общей памятью сервера — для !ask, голосовых сообщений и прослушивания войса."""
        history = self._shared_histories[memory_key]
        user_message = {"role": "user", "content": f"[{name}]: {question}"}
        reply = await ai.chat([{"role": "system", "content": AI_SYSTEM_PROMPT}, *history, user_message])
        history.extend([user_message, {"role": "assistant", "content": reply}])
        return reply

    async def _speak(self, ctx, text: str):
        """Озвучка ответа в войсе — бонус: если голос недоступен, ответ уже есть в чате."""
        vc = ctx.guild.voice_client
        try:
            if not vc or not vc.is_connected():
                vc = await asyncio.wait_for(ctx.author.voice.channel.connect(), timeout=15)
            await say(vc, text)
        except Exception as e:
            print(f"[voice_ai] Озвучка не удалась: {e!r}")
            await ctx.send("🔇 Не получилось озвучить ответ в войсе — он есть в чате.", delete_after=8)

    @commands.command(name="join", aliases=["j"], brief="Позвать бота в голосовой канал")
    async def voice_join(self, ctx):
        if not ctx.author.voice:
            await ctx.send("❌ Сначала зайди в голосовой канал!", delete_after=5); return
        if ctx.guild.voice_client:
            await ctx.send("⚠️ Я уже в канале. Пиши `!ask <вопрос>`.", delete_after=5); return
        try:
            await asyncio.wait_for(ctx.author.voice.channel.connect(), timeout=15)
        except Exception as e:
            await ctx.send(f"❌ Не удалось подключиться к войсу: {e}", delete_after=8); return
        await ctx.send("✅ Подключился! Пиши `!ask <вопрос>`, и я отвечу голосом.")

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


def setup(bot):
    bot.add_cog(VoiceAICog(bot))
