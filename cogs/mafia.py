import asyncio
import os
import random
import tempfile
import discord
from discord.ext import commands
import edge_tts
from config import _groq_client, AI_SYSTEM_PROMPT, TTS_SETTINGS
from data import MAFIA_DATA


# ── AI narrator ───────────────────────────────────────────────
async def mafia_ai_narrator(prompt_type: str, context_data: str = "") -> str:
    prompts = {
        "morning": (
            f"Наступило утро в городе. Итоги ночи: {context_data}. "
            "Расскажи об этом очень кратко, смешно и в стиле Bazarcik PM. "
            "Если кто-то умер — придумай нелепую причину. "
            "Упомяни, что Юра Яковенко в безопасности."
        ),
        "win": (
            f"Игра окончена! Победили: {context_data}. "
            "Прокомментируй дерзко и ярко."
        ),
        "ai_defense": (
            f"Ты играешь в мафию. Твоя роль: {context_data}. "
            "Тебя подозревают. Оправдайся очень дерзко, "
            "наезжай на других и защищай Юру Яковенко. Без Markdown!"
        ),
        "night_start": (
            f"Ночь #{context_data} опустилась на город. "
            "Опиши атмосферу ночи очень кратко и зловеще, в стиле Bazarcik PM. "
            "Без Markdown, 1-2 предложения."
        ),
        "vote_result": (
            f"Город проголосовал и изгнал {context_data}. "
            "Прокомментируй это язвительно и смешно в стиле Bazarcik PM. "
            "Без Markdown, 1 предложение."
        ),
        "all_voted": (
            f"Все живые проголосовали в мафии. Текущие итоги: {context_data}. "
            "Напряги атмосферу — скоро приговор. Без Markdown, 1 предложение."
        ),
        "night_actions_done": (
            "Все ночные роли сделали свои ходы в мафии. "
            "Скажи кратко, что город замер в ожидании рассвета. Без Markdown, 1 предложение."
        ),
    }
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": AI_SYSTEM_PROMPT},
                    {"role": "user",   "content": prompts.get(prompt_type, context_data)},
                ],
                max_tokens=300,
            )
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return "Произошла техническая шоколадка, но город проснулся!"


# ── Join button ───────────────────────────────────────────────
class MafiaJoinView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎮 Вступить в игру", style=discord.ButtonStyle.green, custom_id="mafia_join_btn")
    async def join_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not MAFIA_DATA["is_running"] or MAFIA_DATA["phase"] != "waiting":
            return await interaction.response.send_message("❌ Набор закрыт!", ephemeral=True)

        uid = interaction.user.id
        if uid in MAFIA_DATA["players"]:
            return await interaction.response.send_message("⚠️ Ты уже в списке!", ephemeral=True)

        MAFIA_DATA["players"][uid] = {
            "role": None, "is_alive": True, "name": interaction.user.display_name
        }
        count = len(MAFIA_DATA["players"])
        names = ", ".join(d["name"] for d in MAFIA_DATA["players"].values())
        await interaction.response.send_message(f"✅ **{interaction.user.display_name}**, ты в игре!", ephemeral=True)
        try:
            await interaction.message.edit(
                content=(f"🕵️‍♂️ **МАФИЯ НА БАЗАРЧИКЕ!**\n"
                         f"Жмите кнопку, чтобы зайти. Нужно минимум 4 человека.\n"
                         f"👥 Игроков: **{count}** — {names}"),
                view=self,
            )
        except Exception:
            pass


# ── Cog ───────────────────────────────────────────────────────
class MafiaCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Internal helpers ──────────────────────────────────────
    def _alive_players(self, include_bot=False):
        return [
            (uid, d) for uid, d in MAFIA_DATA["players"].items()
            if d["is_alive"] and (include_bot or uid != self.bot.user.id)
        ]

    def _numbered_list(self, include_bot=False):
        alive = self._alive_players(include_bot)
        text  = "\n".join(f"{i+1}. {d['name']}" for i, (_, d) in enumerate(alive))
        return alive, text

    def _pending_actions(self):
        pending = []
        for uid, data in MAFIA_DATA["players"].items():
            if not data["is_alive"]: continue
            role = data["role"]
            if role == "Мафия"    and MAFIA_DATA["actions"]["kill"]  is None: pending.append("Мафия")
            elif role == "Доктор"  and MAFIA_DATA["actions"]["heal"]  is None: pending.append("Доктор")
            elif role == "Комиссар" and MAFIA_DATA["actions"]["check"] is None: pending.append("Комиссар")
        return pending

    async def _mafia_say(self, channel, text: str):
        await channel.send(f"🎙️ **Ведущий:** {text}")
        vc = channel.guild.voice_client
        if vc and vc.is_connected():
            try:
                tts_path = tempfile.mktemp(suffix=".mp3")
                await edge_tts.Communicate(text, TTS_SETTINGS["voice"]).save(tts_path)
                while vc.is_playing():
                    await asyncio.sleep(0.5)
                vc.play(
                    discord.FFmpegPCMAudio(tts_path),
                    after=lambda e: os.unlink(tts_path) if os.path.exists(tts_path) else None,
                )
            except Exception as e:
                print(f"[MAFIA TTS] {e}")

    async def _check_winner(self, channel) -> bool:
        alive_mafia = [d for d in MAFIA_DATA["players"].values() if d["role"] == "Мафия" and d["is_alive"]]
        alive_civil = [d for d in MAFIA_DATA["players"].values() if d["role"] != "Мафия" and d["is_alive"]]

        if not alive_mafia:
            msg = await mafia_ai_narrator("win", "Мирные жители и Юра!")
            await self._mafia_say(channel, msg)
            await channel.send("🏆 **МИРНЫЕ ПОБЕДИЛИ!** Мафия уничтожена.")
            MAFIA_DATA["is_running"] = False
            return True

        if len(alive_mafia) >= len(alive_civil):
            msg = await mafia_ai_narrator("win", "МАФИЯ!")
            await self._mafia_say(channel, msg)
            await channel.send("🔴 **МАФИЯ ПОБЕДИЛА!** Мирных слишком мало.")
            MAFIA_DATA["is_running"] = False
            return True

        return False

    async def _send_night_dm(self):
        alive, player_list = self._numbered_list()
        for uid, data in list(MAFIA_DATA["players"].items()):
            if not data["is_alive"] or uid == self.bot.user.id: continue
            user = self.bot.get_user(uid)
            if not user: continue
            role = data["role"]
            try:
                if role == "Мафия":
                    await user.send(
                        f"🌑 **НОЧЬ #{MAFIA_DATA['night_count']}** — ты **Мафия!**\n"
                        f"Живые игроки:\n{player_list}\n\n`!kill <номер>` — выбрать жертву.")
                elif role == "Доктор":
                    await user.send(
                        f"🌑 **НОЧЬ #{MAFIA_DATA['night_count']}** — ты **Доктор!**\n"
                        f"Живые игроки:\n{player_list}\n\n`!heal <номер>` — кого лечишь.")
                elif role == "Комиссар":
                    await user.send(
                        f"🌑 **НОЧЬ #{MAFIA_DATA['night_count']}** — ты **Комиссар!**\n"
                        f"Живые игроки:\n{player_list}\n\n`!check <номер>` — проверить.")
                elif role == "Мирный":
                    await user.send(
                        f"🌑 **НОЧЬ #{MAFIA_DATA['night_count']}** — ты **Мирный житель.**\n"
                        f"Дожидайся утра (переход автоматический).")
            except discord.Forbidden:
                pass

        # Бот авто-действует
        bot_data = MAFIA_DATA["players"].get(self.bot.user.id)
        if bot_data and bot_data["is_alive"]:
            bot_role = bot_data["role"]
            non_bot  = [(uid, d) for uid, d in alive if uid != self.bot.user.id]
            if bot_role == "Мафия" and non_bot and MAFIA_DATA["actions"]["kill"] is None:
                MAFIA_DATA["actions"]["kill"] = random.choice(non_bot)[0]
            elif bot_role == "Доктор" and alive and MAFIA_DATA["actions"]["heal"] is None:
                MAFIA_DATA["actions"]["heal"] = random.choice(alive)[0]
            elif bot_role == "Комиссар" and non_bot and MAFIA_DATA["actions"]["check"] is None:
                MAFIA_DATA["actions"]["check"] = random.choice(non_bot)[0]

    async def _process_morning(self, channel):
        kill_id = MAFIA_DATA["actions"]["kill"]
        heal_id = MAFIA_DATA["actions"]["heal"]

        result_text = "Этой ночью никто не погиб."
        if kill_id is not None:
            victim = MAFIA_DATA["players"].get(kill_id)
            if victim:
                if kill_id == heal_id:
                    result_text = f"Мафия атаковала **{victim['name']}**, но Доктор успел его спасти!"
                elif victim["is_alive"]:
                    victim["is_alive"] = False
                    result_text = f"Был зверски ликвидирован **{victim['name']}** (роль: {victim['role']})."

        MAFIA_DATA["actions"] = {"kill": None, "heal": None, "check": None}
        MAFIA_DATA["phase"]   = "day"

        story = await mafia_ai_narrator("morning", result_text)
        await self._mafia_say(channel, story)

        bot_data = MAFIA_DATA["players"].get(self.bot.user.id)
        if bot_data and bot_data["is_alive"]:
            ai_opinion = await mafia_ai_narrator("ai_defense", bot_data["role"])
            await channel.send(f"🤖 **{self.bot.user.display_name} говорит:** {ai_opinion}")

        if await self._check_winner(channel):
            return

        alive, player_list = self._numbered_list(include_bot=True)
        await channel.send(
            f"☀️ **ДЕНЬ #{MAFIA_DATA['night_count']}**\n"
            f"Живые игроки:\n{player_list}\n\n"
            f"🗳️ Голосуйте за изгнание: `!mafia_vote <номер>`\n"
            f"⚖️ Завершить голосование: `!mafia_end_day`"
        )

    async def _try_advance_night(self, channel):
        if MAFIA_DATA["phase"] != "night": return
        pending = self._pending_actions()
        if pending: return
        bridge_text = await mafia_ai_narrator("night_actions_done")
        await self._mafia_say(channel, bridge_text)
        await asyncio.sleep(2)
        await self._process_morning(channel)

    # ── Commands ──────────────────────────────────────────────
    @commands.command(name="mafia_start")
    async def mafia_start(self, ctx):
        await ctx.message.delete()
        if MAFIA_DATA["is_running"]:
            return await ctx.send("❌ Игра уже идёт! Останови её командой `!mafia_stop`.", delete_after=5)

        MAFIA_DATA.update({
            "is_running": True, "phase": "waiting", "players": {},
            "actions": {"kill": None, "heal": None, "check": None},
            "votes": {}, "night_count": 0,
            "channel_id": ctx.channel.id, "guild_id": ctx.guild.id,
        })
        MAFIA_DATA["players"][self.bot.user.id] = {
            "role": None, "is_alive": True, "name": self.bot.user.display_name
        }
        view = MafiaJoinView()
        await ctx.send(
            f"🕵️‍♂️ **МАФИЯ НА БАЗАРЧИКЕ!**\n"
            f"Жмите кнопку, чтобы зайти. Нужно минимум 4 человека.\n"
            f"👥 Игроков: **1** — {self.bot.user.display_name}",
            view=view,
        )

    @commands.command(name="mafia_go")
    async def mafia_go(self, ctx):
        await ctx.message.delete()
        if not MAFIA_DATA["is_running"] or MAFIA_DATA["phase"] != "waiting":
            return await ctx.send("❌ Нет активного набора! Сначала `!mafia_start`.", delete_after=5)

        total = len(MAFIA_DATA["players"])
        if total < 4:
            return await ctx.send(f"❌ Нужно минимум 4 игрока! Сейчас: **{total}**", delete_after=5)

        uids = [uid for uid in MAFIA_DATA["players"] if uid != self.bot.user.id]
        random.shuffle(uids)

        n_players = len(uids)
        n_mafia   = max(1, n_players // 4)
        n_civil   = max(0, n_players - n_mafia - 2)

        roles_pool = ["Мафия"] * n_mafia + ["Доктор"] + ["Комиссар"] + ["Мирный"] * n_civil
        random.shuffle(roles_pool)

        for i, uid in enumerate(uids):
            role = roles_pool[i] if i < len(roles_pool) else "Мирный"
            MAFIA_DATA["players"][uid]["role"] = role
            user = self.bot.get_user(uid)
            if user:
                try:
                    await user.send(
                        f"🎭 **Твоя роль в Мафии: {role}**\n\n"
                        f"{'🔴 Убивай мирных ночью командой `!kill <номер>`' if role == 'Мафия' else ''}"
                        f"{'💊 Лечи кого-то ночью командой `!heal <номер>`' if role == 'Доктор' else ''}"
                        f"{'🔍 Проверяй игроков ночью командой `!check <номер>`' if role == 'Комиссар' else ''}"
                        f"{'🏠 Дожидайся утра, голосуй днём командой `!mafia_vote <номер>`' if role == 'Мирный' else ''}"
                        f"\nУдачи!"
                    )
                except discord.Forbidden:
                    pass

        MAFIA_DATA["players"][self.bot.user.id]["role"] = random.choice(["Мафия", "Мирный"])
        MAFIA_DATA["phase"]       = "night"
        MAFIA_DATA["night_count"] = 1
        MAFIA_DATA["actions"]     = {"kill": None, "heal": None, "check": None}

        roles_count = f"Мафии: **{n_mafia}** | Доктор: **1** | Комиссар: **1** | Мирных: **{n_civil + 1}** (включая бота)"

        night_msg = await mafia_ai_narrator("night_start", "1")
        await self._mafia_say(ctx, night_msg)

        await ctx.send(
            f"🌑 **НОЧЬ #1 НАСТУПИЛА!**\n"
            f"Всего игроков: **{total}** | {roles_count}\n\n"
            f"Роли розданы в ЛС. Переход к утру — автоматически когда все сделают ход.\n"
            f"Посмотреть статус: `!mafia_status`"
        )
        await self._send_night_dm()

    # ── Night actions (DM only) ───────────────────────────────
    @commands.command(name="kill")
    async def mafia_kill(self, ctx, number: int):
        if ctx.guild: return
        uid = ctx.author.id
        if not MAFIA_DATA["is_running"]: return await ctx.send("❌ Игра не идёт.")
        if MAFIA_DATA["phase"] != "night": return await ctx.send("❌ Сейчас не ночь.")
        player = MAFIA_DATA["players"].get(uid)
        if not player: return await ctx.send("❌ Ты не участник.")
        if not player["is_alive"]: return await ctx.send("❌ Ты мёртв.")
        if player["role"] != "Мафия": return await ctx.send("❌ Ты не Мафия.")

        alive, player_list = self._numbered_list()
        if number < 1 or number > len(alive):
            return await ctx.send(f"❌ Выбери от 1 до {len(alive)}:\n{player_list}")
        target_id, target_data = alive[number - 1]
        if target_id == uid: return await ctx.send("❌ Нельзя убить себя!")

        MAFIA_DATA["actions"]["kill"] = target_id
        await ctx.send(f"🔪 Цель выбрана: **{target_data['name']}**. Ждём остальных ролей.")

        channel = self.bot.get_channel(MAFIA_DATA["channel_id"])
        if channel:
            pending = self._pending_actions()
            if pending:
                await channel.send(f"🌑 Ночные действия в процессе... (ждём: {', '.join(pending)})")
            await self._try_advance_night(channel)

    @commands.command(name="heal")
    async def mafia_heal(self, ctx, number: int):
        if ctx.guild: return
        uid = ctx.author.id
        if not MAFIA_DATA["is_running"]: return await ctx.send("❌ Игра не идёт.")
        if MAFIA_DATA["phase"] != "night": return await ctx.send("❌ Сейчас не ночь.")
        player = MAFIA_DATA["players"].get(uid)
        if not player: return await ctx.send("❌ Ты не участник.")
        if not player["is_alive"]: return await ctx.send("❌ Ты мёртв.")
        if player["role"] != "Доктор": return await ctx.send("❌ Ты не Доктор.")

        alive, player_list = self._numbered_list()
        if number < 1 or number > len(alive):
            return await ctx.send(f"❌ Выбери от 1 до {len(alive)}:\n{player_list}")
        target_id, target_data = alive[number - 1]

        MAFIA_DATA["actions"]["heal"] = target_id
        await ctx.send(f"💊 Ты спасёшь: **{target_data['name']}**. Ждём остальных ролей.")

        channel = self.bot.get_channel(MAFIA_DATA["channel_id"])
        if channel:
            pending = self._pending_actions()
            if pending:
                await channel.send(f"🌑 Ночные действия в процессе... (ждём: {', '.join(pending)})")
            await self._try_advance_night(channel)

    @commands.command(name="check")
    async def mafia_check(self, ctx, number: int):
        if ctx.guild: return
        uid = ctx.author.id
        if not MAFIA_DATA["is_running"]: return await ctx.send("❌ Игра не идёт.")
        if MAFIA_DATA["phase"] != "night": return await ctx.send("❌ Сейчас не ночь.")
        player = MAFIA_DATA["players"].get(uid)
        if not player: return await ctx.send("❌ Ты не участник.")
        if not player["is_alive"]: return await ctx.send("❌ Ты мёртв.")
        if player["role"] != "Комиссар": return await ctx.send("❌ Ты не Комиссар.")

        alive, player_list = self._numbered_list()
        if number < 1 or number > len(alive):
            return await ctx.send(f"❌ Выбери от 1 до {len(alive)}:\n{player_list}")
        target_id, target_data = alive[number - 1]
        is_mafia = target_data["role"] == "Мафия"
        MAFIA_DATA["actions"]["check"] = target_id

        await ctx.send(
            f"🔍 **{target_data['name']}** — "
            f"{'🔴 **МАФИЯ!** Это враг!' if is_mafia else '⚪ Мирный (или особая роль).'}"
        )

        channel = self.bot.get_channel(MAFIA_DATA["channel_id"])
        if channel:
            pending = self._pending_actions()
            if pending:
                await channel.send(f"🌑 Ночные действия в процессе... (ждём: {', '.join(pending)})")
            await self._try_advance_night(channel)

    @commands.command(name="morning")
    async def mafia_morning(self, ctx):
        """[Резерв] Ведущий вручную завершает ночь."""
        await ctx.message.delete()
        if not MAFIA_DATA["is_running"] or MAFIA_DATA["phase"] != "night":
            return await ctx.send("❌ Сейчас не ночная фаза!", delete_after=5)

        pending = self._pending_actions()
        if pending:
            await ctx.send(
                f"⚠️ Ещё не все сделали ход: **{', '.join(pending)}**\nПринудительный переход...",
                delete_after=8,
            )
        await self._process_morning(ctx.channel)

    # ── Voting ────────────────────────────────────────────────
    @commands.command(name="mafia_vote")
    async def mafia_vote(self, ctx, number: int):
        await ctx.message.delete()
        if not MAFIA_DATA["is_running"] or MAFIA_DATA["phase"] != "day":
            return await ctx.send("❌ Голосование доступно только днём!", delete_after=5)

        voter = MAFIA_DATA["players"].get(ctx.author.id)
        if not voter: return await ctx.send("❌ Ты не участник!", delete_after=5)
        if not voter["is_alive"]: return await ctx.send("❌ Мёртвые не голосуют!", delete_after=5)

        alive, player_list = self._numbered_list(include_bot=True)
        if number < 1 or number > len(alive):
            return await ctx.send(f"❌ Выбери число от 1 до {len(alive)}:\n{player_list}", delete_after=10)

        target_id, target_data = alive[number - 1]
        if target_id == ctx.author.id:
            return await ctx.send("❌ Нельзя голосовать за себя!", delete_after=5)

        MAFIA_DATA["votes"][ctx.author.id] = target_id
        await ctx.send(f"🗳️ **{ctx.author.display_name}** голосует против **{target_data['name']}**")

        # Бот авто-голосует
        bot_data = MAFIA_DATA["players"].get(self.bot.user.id)
        if bot_data and bot_data["is_alive"] and self.bot.user.id not in MAFIA_DATA["votes"]:
            non_bot = [(uid, d) for uid, d in alive if uid != self.bot.user.id]
            if non_bot:
                bot_target_id   = random.choice(non_bot)[0]
                bot_target_name = MAFIA_DATA["players"][bot_target_id]["name"]
                MAFIA_DATA["votes"][self.bot.user.id] = bot_target_id
                await ctx.send(f"🤖 **{self.bot.user.display_name}** подозрительно косится на **{bot_target_name}**...")

        # Проверяем — все ли проголосовали
        alive_now, _ = self._numbered_list(include_bot=True)
        alive_ids   = {uid for uid, _ in alive_now}
        voted_ids   = set(MAFIA_DATA["votes"].keys()) & alive_ids

        if len(voted_ids) >= len(alive_ids):
            from collections import Counter
            counts    = Counter(MAFIA_DATA["votes"].values())
            leader_id = counts.most_common(1)[0][0]
            leader    = MAFIA_DATA["players"][leader_id]
            summary   = ", ".join(
                f"{MAFIA_DATA['players'][tid]['name']} — {cnt} голос(а)"
                for tid, cnt in counts.most_common(3) if tid in MAFIA_DATA["players"]
            )
            all_voted_text = await mafia_ai_narrator("all_voted", summary)
            await self._mafia_say(ctx.channel, all_voted_text)
            await asyncio.sleep(2)

            leader["is_alive"] = False
            MAFIA_DATA["votes"] = {}

            vote_comment = await mafia_ai_narrator("vote_result", leader["name"])
            await ctx.send(
                f"⚖️ {vote_comment}\n"
                f"Город изгнал **{leader['name']}** — его роль: **{leader['role']}**"
            )
            exiled_user = self.bot.get_user(leader_id)
            if exiled_user:
                try:
                    await exiled_user.send(f"💀 Ты изгнан. Твоя роль: **{leader['role']}**.\nМожешь наблюдать.")
                except discord.Forbidden: pass

            if await self._check_winner(ctx.channel): return

            MAFIA_DATA["phase"]        = "night"
            MAFIA_DATA["night_count"] += 1
            MAFIA_DATA["actions"]      = {"kill": None, "heal": None, "check": None}

            night_msg = await mafia_ai_narrator("night_start", str(MAFIA_DATA["night_count"]))
            await self._mafia_say(ctx.channel, night_msg)

            alive_next, _ = self._numbered_list(include_bot=True)
            await ctx.send(
                f"🌑 **НОЧЬ #{MAFIA_DATA['night_count']} НАСТУПИЛА!**\n"
                f"Живых осталось: **{len(alive_next)}**\n"
                f"Мафия, Доктор, Комиссар — действуйте!\n"
                f"Переход к утру — автоматически когда все сделают ход."
            )
            await self._send_night_dm()
        else:
            await ctx.send(f"📊 Проголосовало: **{len(voted_ids)}/{len(alive_ids)}**. Ждём остальных...")

    @commands.command(name="mafia_end_day")
    async def mafia_end_day(self, ctx):
        """[Резерв] Принудительно завершить голосование."""
        await ctx.message.delete()
        if not MAFIA_DATA["is_running"] or MAFIA_DATA["phase"] != "day":
            return await ctx.send("❌ Сейчас не дневная фаза!", delete_after=5)
        if not MAFIA_DATA["votes"]:
            return await ctx.send("❌ Никто не проголосовал!", delete_after=5)

        from collections import Counter
        counts    = Counter(MAFIA_DATA["votes"].values())
        killed_id = counts.most_common(1)[0][0]
        victim    = MAFIA_DATA["players"][killed_id]
        victim["is_alive"] = False
        MAFIA_DATA["votes"] = {}

        vote_comment = await mafia_ai_narrator("vote_result", victim["name"])
        await ctx.send(f"⚖️ {vote_comment}\nГород изгнал **{victim['name']}** — его роль: **{victim['role']}**")

        exiled_user = self.bot.get_user(killed_id)
        if exiled_user:
            try:
                await exiled_user.send(f"💀 Ты изгнан. Твоя роль: **{victim['role']}**.\nМожешь наблюдать.")
            except discord.Forbidden: pass

        if await self._check_winner(ctx.channel): return

        MAFIA_DATA["phase"]        = "night"
        MAFIA_DATA["night_count"] += 1
        MAFIA_DATA["actions"]      = {"kill": None, "heal": None, "check": None}

        night_msg = await mafia_ai_narrator("night_start", str(MAFIA_DATA["night_count"]))
        await self._mafia_say(ctx.channel, night_msg)

        alive, _ = self._numbered_list(include_bot=True)
        await ctx.send(
            f"🌑 **НОЧЬ #{MAFIA_DATA['night_count']} НАСТУПИЛА!**\n"
            f"Живых осталось: **{len(alive)}**\n"
            f"Мафия, Доктор, Комиссар — действуйте!\n"
            f"Переход к утру — автоматически когда все сделают ход."
        )
        await self._send_night_dm()

    # ── Status / Stop ─────────────────────────────────────────
    @commands.command(name="mafia_status")
    async def mafia_status(self, ctx):
        await ctx.message.delete()
        if not MAFIA_DATA["is_running"]:
            return await ctx.send("❌ Игра не запущена.", delete_after=5)

        phase_names = {
            "waiting": "⏳ Набор игроков",
            "night":   f"🌑 Ночь #{MAFIA_DATA['night_count']}",
            "day":     f"☀️ День #{MAFIA_DATA['night_count']}",
        }
        embed = discord.Embed(
            title=f"🕵️ Мафия — {phase_names.get(MAFIA_DATA['phase'], MAFIA_DATA['phase'])}",
            color=discord.Color.dark_red(),
        )
        alive_lines, dead_lines = [], []
        for uid, d in MAFIA_DATA["players"].items():
            icon = "🤖" if uid == self.bot.user.id else "👤"
            line = f"{icon} {d['name']}"
            if d["is_alive"]:
                alive_lines.append(line)
            else:
                dead_lines.append(f"~~{line}~~ ({d['role']})")

        if alive_lines:
            embed.add_field(name=f"✅ Живые ({len(alive_lines)})", value="\n".join(alive_lines), inline=False)
        if dead_lines:
            embed.add_field(name=f"💀 Мёртвые ({len(dead_lines)})", value="\n".join(dead_lines), inline=False)

        if MAFIA_DATA["phase"] == "waiting":
            embed.set_footer(text="Для старта вызови !mafia_go (нужно 4+ игрока)")
        elif MAFIA_DATA["phase"] == "night":
            pending = self._pending_actions()
            footer = f"Ожидаем: {', '.join(pending)}" if pending else "Все сделали ход, переход скоро..."
            embed.set_footer(text=footer)
        elif MAFIA_DATA["phase"] == "day":
            alive_now, _ = self._numbered_list(include_bot=True)
            alive_ids = {uid for uid, _ in alive_now}
            voted = len(set(MAFIA_DATA["votes"].keys()) & alive_ids)
            embed.set_footer(text=f"Голосуй !mafia_vote <номер> | Проголосовало: {voted}/{len(alive_ids)}")

        await ctx.send(embed=embed)

    @commands.command(name="mafia_stop")
    async def mafia_stop(self, ctx):
        await ctx.message.delete()
        MAFIA_DATA.update({
            "is_running": False, "phase": "waiting", "players": {},
            "actions": {"kill": None, "heal": None, "check": None},
            "votes": {}, "night_count": 0,
        })
        await ctx.send("🛑 Игра в Мафию принудительно остановлена.")


async def setup(bot):
    await bot.add_cog(MafiaCog(bot))
