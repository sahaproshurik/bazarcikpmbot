import asyncio
import os
import re
import tempfile
from collections import defaultdict
import discord
from discord.ext import commands
import edge_tts
from config import get_groq_client, AI_SYSTEM_PROMPT, TTS_SETTINGS
from data import AUTO_CHANNELS, YOUR_USER_ID

AUDIO_FILE = os.path.abspath("greeting.mp3")
_greeting_lock = asyncio.Lock()


def generate_greeting():
    if not os.path.exists(AUDIO_FILE):
        try:
            from gtts import gTTS
            tts = gTTS("Привіт Юра Яковенко", lang="uk")
            tts.save(AUDIO_FILE)
            print(f"[AUDIO] Файл создан: {AUDIO_FILE}")
        except Exception as e:
            print(f"[AUDIO] Ошибка создания файла: {e}")


class VoiceAICog(commands.Cog):
    def __init__(self, bot):
        self.bot              = bot
        self._shared_histories = defaultdict(list)

    # ── AI Chat ───────────────────────────────────────────────
    @commands.command(name="ask", aliases=["a", "спроси"], brief="Общий чат с AI (бот помнит всех)")
    async def ask_ai(self, ctx, *, question: str):
        await ctx.message.delete()

        if not ctx.author.voice:
            await ctx.send("❌ Зайди в войс, чтобы я мог ответить голосом!", delete_after=5)
            return

        vc = ctx.guild.voice_client
        if not vc or not vc.is_connected():
            try:
                vc = await ctx.author.voice.channel.connect()
            except Exception as e:
                await ctx.send(f"❌ Ошибка подключения: {e}", delete_after=5)
                return

        status_msg = await ctx.send(f"💬 **{ctx.author.display_name}**: {question}\n⏳ *Пишет ответ...*")
        history    = self._shared_histories[ctx.guild.id]
        user_message = f"[{ctx.author.display_name}]: {question}"
        history.append({"role": "user", "content": user_message})
        if len(history) > 6:
            history.pop(0)

        try:
            messages_for_api = [{"role": "system", "content": AI_SYSTEM_PROMPT}] + history
            reply_obj = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: get_groq_client().chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    max_tokens=400,
                    messages=messages_for_api,
                )
            )
            reply = reply_obj.choices[0].message.content.strip()
            history.append({"role": "assistant", "content": reply})
            await status_msg.edit(content=f"💬 **{ctx.author.display_name}**: {question}\n🤖 **AI**: {reply}")

            tts_path  = tempfile.mktemp(suffix=".mp3")
            communicate = edge_tts.Communicate(reply, TTS_SETTINGS["voice"])
            await communicate.save(tts_path)

            while vc.is_playing():
                await asyncio.sleep(0.5)

            if vc.is_connected():
                def after_play(e):
                    try: os.unlink(tts_path)
                    except Exception: pass
                vc.play(discord.FFmpegPCMAudio(tts_path), after=after_play)

        except Exception as e:
            await status_msg.edit(content=f"❌ Ошибка ИИ: `{e}`")

    @commands.command(name="join", aliases=["j"], brief="Позвать бота в голосовой канал")
    async def voice_join(self, ctx):
        await ctx.message.delete()
        if not ctx.author.voice:
            await ctx.send("❌ Сначала зайди в голосовой канал!", delete_after=5); return
        if ctx.guild.voice_client:
            await ctx.send("⚠️ Я уже в канале. Пиши `!ask <вопрос>`.", delete_after=5); return
        await ctx.author.voice.channel.connect()
        await ctx.send("✅ Подключился! Пиши `!ask <вопрос>`, и я отвечу голосом.")

    @commands.command(name="leave", aliases=["l", "выйти"], brief="Выгнать бота из войса")
    async def voice_leave(self, ctx):
        await ctx.message.delete()
        if ctx.guild.voice_client:
            await ctx.guild.voice_client.disconnect()
            await ctx.send("👋 Вышел из голосового канала.")
        else:
            await ctx.send("❌ Я не в канале.", delete_after=5)

    @commands.command(name="aiclear", brief="Очистить общую память чата")
    async def voice_clear(self, ctx):
        await ctx.message.delete()
        self._shared_histories[ctx.guild.id].clear()
        await ctx.send("🗑️ Общая память чата очищена. Бот всех забыл!")

    @commands.command(name="aivoice", brief="Сменить голос AI")
    async def voice_change(self, ctx, *, voice_name: str = None):
        await ctx.message.delete()
        if not voice_name:
            await ctx.send(
                "🗣️ **Доступные голоса:**\n"
                "• `ru-RU-SvetlanaNeural` (женский)\n"
                "• `ru-RU-DmitryNeural` (мужской)\n"
                "• `ru-RU-DariyaNeural` (женский)\n\n"
                "Пример: `!aivoice ru-RU-DmitryNeural`"
            )
            return
        TTS_SETTINGS["voice"] = voice_name
        await ctx.send(f"✅ Голос изменён на `{voice_name}`")

    # ── Voice state ───────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):

        # === Создание авто-канала ===
        if after.channel and after.channel.id in AUTO_CHANNELS:
            guild    = member.guild
            cat_id   = AUTO_CHANNELS[after.channel.id]
            category = guild.get_channel(cat_id)
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
                        generate_greeting()

                    finished = asyncio.Event()
                    def after_play(error):
                        if error: print(f"[AUDIO] Ошибка: {error}")
                        self.bot.loop.call_soon_threadsafe(finished.set)

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
