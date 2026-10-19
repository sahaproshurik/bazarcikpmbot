"""
admin.py — инструменты администрации:
  • лог-канал: удалённые/изменённые сообщения, входы/выходы (с проверкой «свежих» аккаунтов), смены ников и ролей;
  • автомодерация: флуд, чужие инвайты, капс, масс-упоминания, запрещённые слова;
  • автороль и приветствие новичков, меню ролей на кнопках;
  • !snipe, статус бота, горячая перезагрузка cogs, бэкап всех данных в ЛС.
"""
import glob
import io
import platform
import re
import time
import zipfile
from collections import defaultdict, deque
from datetime import timedelta
import discord
from discord.ext import commands
import ai
from data import mod_data, save_guild_cfg
from utils import guild_cfg, send_log, log_action, safe_delete, utcnow, fmt_duration

INVITE_RE = re.compile(r"(discord\.gg|discord(?:app)?\.com/invite)/\S+", re.I)
AUTOMOD_RULES = {
    "spam":     ("Флуд",              "5+ сообщений за 7 секунд → удаление и тайм-аут 5 минут"),
    "invites":  ("Инвайты",           "чужие приглашения discord.gg → удаление"),
    "caps":     ("Капс",              "70%+ заглавных в сообщении от 12 букв → удаление"),
    "mentions": ("Масс-упоминания",   "5+ упоминаний в сообщении → удаление и тайм-аут 10 минут"),
    "words":    ("Запрещённые слова", "слова из !badword → удаление"),
}
AUTOMOD_DEFAULTS = {"spam": True, "invites": True, "caps": False, "mentions": True, "words": True}
NEW_ACCOUNT_DAYS = 7
ON  = ("on", "вкл", "да", "1", "true")
OFF = ("off", "выкл", "нет", "0", "false")


def automod_cfg(guild_id) -> dict:
    am = guild_cfg(guild_id).setdefault("automod", {})
    am.setdefault("enabled", False)
    am.setdefault("words", [])
    for rule, default in AUTOMOD_DEFAULTS.items():
        am.setdefault(rule, default)
    return am


def fill_placeholders(text: str, member: discord.Member) -> str:
    return (text.replace("{user}", member.mention).replace("{name}", member.display_name)
                .replace("{server}", member.guild.name).replace("{count}", str(member.guild.member_count)))


class AdminCog(commands.Cog):
    def __init__(self, bot):
        self.bot     = bot
        self.started = time.time()
        self.snipes: dict = {}                                  # channel_id → (author, content, when, files)
        self.recent  = defaultdict(lambda: deque(maxlen=10))    # (guild, user) → времена сообщений
        self.automod_deleted: set = set()                       # id сообщений, удалённых автомодом

    def is_command(self, message: discord.Message) -> bool:
        prefix = self.bot.command_prefix
        return isinstance(prefix, str) and message.content.startswith(prefix)

    # ══ Лог-канал ═════════════════════════════════════════════
    @commands.command(name="setlog", brief="[Админ] Канал для логов модерации и событий",
                      help="`!setlog #канал` — включить логи, `!setlog off` — выключить.")
    @commands.has_permissions(administrator=True)
    async def setlog(self, ctx, channel: str = None):
        cfg = guild_cfg(ctx.guild.id)
        if channel and channel.lower() in OFF:
            cfg.pop("log_channel", None)
            save_guild_cfg()
            return await ctx.send("📕 Логи выключены.", delete_after=10)
        target = ctx.message.channel_mentions[0] if ctx.message.channel_mentions else ctx.channel
        cfg["log_channel"] = target.id
        save_guild_cfg()
        await ctx.send(f"📗 Логи теперь пишутся в {target.mention}.", delete_after=10)
        await send_log(ctx.guild, discord.Embed(title="📗 Лог-канал подключён", color=discord.Color.green(),
                                                description=f"Настроил: {ctx.author.mention}"))

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild or self.is_command(message):
            return                                   # команды бот удаляет сам — это не «удалённые сообщения»
        self.snipes[message.channel.id] = (message.author, message.content, utcnow(),
                                           [a.filename for a in message.attachments])
        if message.id in self.automod_deleted:
            self.automod_deleted.discard(message.id)
            return
        e = discord.Embed(title="🗑 Сообщение удалено", color=discord.Color.red(), timestamp=utcnow(),
                          description=(message.content or "_(без текста)_")[:4000])
        e.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        e.add_field(name="Канал", value=message.channel.mention)
        if message.attachments:
            e.add_field(name="Файлы", value=", ".join(a.filename for a in message.attachments)[:1000])
        await send_log(message.guild, e)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if messages and messages[0].guild:
            e = discord.Embed(title="🧹 Массовое удаление", color=discord.Color.red(), timestamp=utcnow(),
                              description=f"Удалено **{len(messages)}** сообщений в {messages[0].channel.mention}")
            await send_log(messages[0].guild, e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        e = discord.Embed(title="✏️ Сообщение изменено", color=discord.Color.gold(), timestamp=utcnow(),
                          description=f"[Перейти к сообщению]({after.jump_url}) в {after.channel.mention}")
        e.set_author(name=str(before.author), icon_url=before.author.display_avatar.url)
        e.add_field(name="Было", value=(before.content or "—")[:1000], inline=False)
        e.add_field(name="Стало", value=(after.content or "—")[:1000], inline=False)
        await send_log(before.guild, e)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = guild_cfg(member.guild.id)
        age = utcnow() - member.created_at
        e = discord.Embed(title="📥 Участник зашёл", color=discord.Color.green(), timestamp=utcnow(),
                          description=f"{member.mention} • аккаунт создан <t:{int(member.created_at.timestamp())}:R>")
        e.set_thumbnail(url=member.display_avatar.url)
        if age < timedelta(days=NEW_ACCOUNT_DAYS):
            e.color = discord.Color.orange()
            e.add_field(name="⚠️ Новый аккаунт", value=f"Моложе {NEW_ACCOUNT_DAYS} дней — возможен твинк/рейд")
        e.set_footer(text=f"Участников: {member.guild.member_count}")
        await send_log(member.guild, e)

        role = member.guild.get_role(cfg.get("autorole") or 0)
        if role is not None:
            try:
                await member.add_roles(role, reason="Автороль")
            except discord.HTTPException as err:
                print(f"[admin] Не удалось выдать автороль: {err}")
        welcome = cfg.get("welcome")
        if welcome:
            ch = member.guild.get_channel(welcome["channel"])
            if ch is not None:
                try:
                    await ch.send(fill_placeholders(welcome["text"], member))
                except discord.HTTPException:
                    pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        roles = ", ".join(r.mention for r in member.roles[1:]) or "—"
        e = discord.Embed(title="📤 Участник вышел", color=discord.Color.dark_grey(), timestamp=utcnow(),
                          description=f"{member.mention} ({member})")
        e.add_field(name="Роли", value=roles[:1000])
        if member.joined_at:
            e.add_field(name="Был на сервере", value=fmt_duration(utcnow() - member.joined_at))
        await send_log(member.guild, e)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        changes = []
        if before.nick != after.nick:
            changes.append(f"Ник: **{before.nick or before.name}** → **{after.nick or after.name}**")
        added   = [r.mention for r in after.roles if r not in before.roles]
        removed = [r.mention for r in before.roles if r not in after.roles]
        if added:
            changes.append("➕ Роли: " + ", ".join(added))
        if removed:
            changes.append("➖ Роли: " + ", ".join(removed))
        if changes:
            e = discord.Embed(title="👤 Участник изменён", color=discord.Color.blurple(), timestamp=utcnow(),
                              description=f"{after.mention}\n" + "\n".join(changes))
            await send_log(after.guild, e)

    # ══ Автомодерация ═════════════════════════════════════════
    @commands.command(
        name="automod", brief="[Админ] Настройка автомодерации",
        help="`!automod` — статус, `!automod on|off` — включить/выключить,\n"
             "`!automod spam|invites|caps|mentions|words on|off` — отдельные правила.\n"
             "Модераторов (право «Управлять сообщениями») автомод не трогает.")
    @commands.has_permissions(administrator=True)
    async def automod(self, ctx, rule: str = None, state: str = None):
        am = automod_cfg(ctx.guild.id)
        if rule and rule.lower() in ON + OFF and state is None:
            am["enabled"] = rule.lower() in ON
            save_guild_cfg()
        elif rule:
            rule = rule.lower()
            if rule not in AUTOMOD_RULES or state is None or state.lower() not in ON + OFF:
                return await ctx.send(f"❌ Формат: `!automod <{'|'.join(AUTOMOD_RULES)}> on|off`", delete_after=10)
            am[rule] = state.lower() in ON
            save_guild_cfg()
        e = discord.Embed(title=f"🤖 Автомодерация: {'🟢 включена' if am['enabled'] else '🔴 выключена'}",
                          color=discord.Color.purple())
        for key, (name, desc) in AUTOMOD_RULES.items():
            e.add_field(name=f"{'✅' if am[key] else '⬜'} {name} (`{key}`)", value=desc, inline=False)
        e.set_footer(text=f"Запрещённых слов: {len(am['words'])} • !badword add/remove/list")
        await ctx.send(embed=e)

    @commands.command(name="badword", brief="[Админ] Запрещённые слова для автомода",
                      help="`!badword add слово`, `!badword remove слово`, `!badword list`")
    @commands.has_permissions(administrator=True)
    async def badword(self, ctx, action: str = "list", *, word: str = ""):
        am, word, action = automod_cfg(ctx.guild.id), word.lower().strip(), action.lower()
        if action == "add" and word:
            if word not in am["words"]:
                am["words"].append(word)
            save_guild_cfg()
            await ctx.send(f"🚫 Слово добавлено. Всего: {len(am['words'])}", delete_after=8)
        elif action in ("remove", "del") and word:
            if word in am["words"]:
                am["words"].remove(word)
            save_guild_cfg()
            await ctx.send(f"✅ Слово убрано. Всего: {len(am['words'])}", delete_after=8)
        else:
            words = ", ".join(f"||{w}||" for w in am["words"]) or "список пуст"
            await ctx.send(f"🚫 Запрещённые слова: {words}"[:1990], delete_after=30)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
            return
        am = guild_cfg(message.guild.id).get("automod")
        if not am or not am.get("enabled") or message.author.guild_permissions.manage_messages:
            return
        violation, timeout = self._check_automod(message, automod_cfg(message.guild.id))
        if not violation:
            return
        self.automod_deleted.add(message.id)
        await safe_delete(message)
        note = f"🤖 {message.author.mention}, сообщение удалено: **{violation}**."
        if timeout:
            try:
                await message.author.timeout_for(timeout, reason=f"Автомод: {violation}")
                note += f" Тайм-аут на {fmt_duration(timeout)}."
            except discord.HTTPException:
                pass
        await message.channel.send(note, delete_after=8)
        await log_action(message.guild, "automod", message.author, self.bot.user,
                         f"{violation}: {message.content[:300]}", timeout)

    def _check_automod(self, message: discord.Message, am: dict):
        content = message.content
        low = content.lower()
        if am["words"] and any(w in low for w in am["words"]):
            return "запрещённое слово", None
        if am["invites"] and INVITE_RE.search(content):
            return "чужое приглашение", None
        if am["mentions"] and len(message.mentions) + len(message.role_mentions) >= 5:
            return "масс-упоминание", timedelta(minutes=10)
        if am["caps"]:
            letters = [c for c in content if c.isalpha()]
            if len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) >= 0.7:
                return "капс", None
        if am["spam"] and not self.is_command(message):   # частые команды казино/работы — не флуд
            now, q = time.monotonic(), self.recent[(message.guild.id, message.author.id)]
            q.append(now)
            while q and now - q[0] > 7:
                q.popleft()
            if len(q) >= 5:
                q.clear()
                return "флуд", timedelta(minutes=5)
        return None, None

    # ══ Новички ═══════════════════════════════════════════════
    @commands.command(name="autorole", brief="[Админ] Роль, которую получает каждый новичок",
                      help="`!autorole @роль` — включить, `!autorole off` — выключить.")
    @commands.has_permissions(administrator=True)
    async def autorole(self, ctx, *, role: str = None):
        cfg = guild_cfg(ctx.guild.id)
        if role and role.lower() in OFF:
            cfg.pop("autorole", None)
            save_guild_cfg()
            return await ctx.send("✅ Автороль выключена.", delete_after=10)
        if not ctx.message.role_mentions:
            current = ctx.guild.get_role(cfg.get("autorole") or 0)
            return await ctx.send(f"Автороль: {current.mention if current else 'не задана'}. "
                                  f"Формат: `!autorole @роль` или `!autorole off`", delete_after=15)
        r = ctx.message.role_mentions[0]
        if r >= ctx.guild.me.top_role or r.managed:
            return await ctx.send("❌ Эту роль я выдавать не могу — она выше моей.", delete_after=10)
        cfg["autorole"] = r.id
        save_guild_cfg()
        await ctx.send(f"✅ Новички будут получать роль {r.mention}.", delete_after=10)

    @commands.command(name="welcome", brief="[Админ] Приветствие новичков в канале",
                      help="`!welcome #канал Текст` — {user}, {name}, {server}, {count} подставятся.\n"
                           "`!welcome off` — выключить, `!welcome test` — проверить на себе.")
    @commands.has_permissions(administrator=True)
    async def welcome(self, ctx, *, text: str = ""):
        cfg = guild_cfg(ctx.guild.id)
        if text.lower() in OFF:
            cfg.pop("welcome", None)
            save_guild_cfg()
            return await ctx.send("✅ Приветствие выключено.", delete_after=10)
        if text.lower() == "test" and cfg.get("welcome"):
            return await ctx.send(fill_placeholders(cfg["welcome"]["text"], ctx.author))
        if not ctx.message.channel_mentions:
            return await ctx.send("Формат: `!welcome #канал Привет, {user}! Ты {count}-й на {server} 🎉`",
                                  delete_after=15)
        channel = ctx.message.channel_mentions[0]
        body = text.replace(channel.mention, "", 1).strip() or "👋 Привет, {user}! Добро пожаловать на **{server}**!"
        cfg["welcome"] = {"channel": channel.id, "text": body}
        save_guild_cfg()
        await ctx.send(f"✅ Приветствие будет в {channel.mention}:\n> {fill_placeholders(body, ctx.author)}",
                       delete_after=20)

    # ══ Меню ролей ════════════════════════════════════════════
    @commands.command(name="rolemenu", brief="[Админ] Сообщение с кнопками самовыдачи ролей",
                      help="`!rolemenu Заголовок | @роль1 @роль2 ...` — до 25 ролей. "
                           "Кнопки работают и после перезапуска бота.")
    @commands.has_permissions(manage_roles=True)
    async def rolemenu(self, ctx, *, text: str = ""):
        roles = [r for r in ctx.message.role_mentions if r < ctx.guild.me.top_role and not r.managed][:25]
        if not roles:
            return await ctx.send("❌ Упомяни роли (ниже роли бота): `!rolemenu Выбери игры | @CS2 @Dota`",
                                  delete_after=12)
        title = text.split("|", 1)[0].strip() if "|" in text else "🎭 Выбери роли"
        view = discord.ui.View(timeout=None)
        for r in roles:
            view.add_item(discord.ui.Button(label=r.name[:80], custom_id=f"rolemenu:{r.id}",
                                            style=discord.ButtonStyle.secondary))
        e = discord.Embed(title=title[:256], color=discord.Color.blurple(),
                          description="Нажми на кнопку, чтобы взять или снять роль.\n\n" +
                                      "\n".join(r.mention for r in roles))
        await ctx.send(embed=e, view=view)
        view.stop()   # нажатия обрабатывает on_interaction ниже — так кнопки живут после рестарта

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        custom_id = (interaction.data or {}).get("custom_id", "")
        if not custom_id.startswith("rolemenu:") or interaction.guild is None:
            return
        role = interaction.guild.get_role(int(custom_id.split(":", 1)[1]))
        if role is None:
            return await interaction.response.send_message("❌ Этой роли больше нет.", ephemeral=True)
        member = interaction.user
        try:
            if role in member.roles:
                await member.remove_roles(role, reason="Меню ролей")
                text = f"➖ Роль {role.mention} снята."
            else:
                await member.add_roles(role, reason="Меню ролей")
                text = f"➕ Роль {role.mention} выдана."
        except discord.Forbidden:
            text = "❌ Не хватает прав: роль бота должна быть выше этой роли."
        await interaction.response.send_message(text, ephemeral=True)

    # ══ Утилиты ═══════════════════════════════════════════════
    @commands.command(name="snipe", brief="[Мод] Последнее удалённое сообщение в канале")
    @commands.has_permissions(manage_messages=True)
    async def snipe(self, ctx):
        data = self.snipes.get(ctx.channel.id)
        if not data:
            return await ctx.send("🔍 Здесь ничего не удаляли.", delete_after=8)
        author, content, when, files = data
        e = discord.Embed(description=content or "_(без текста)_", color=discord.Color.dark_teal(), timestamp=when)
        e.set_author(name=str(author), icon_url=author.display_avatar.url)
        if files:
            e.add_field(name="Файлы", value=", ".join(files)[:1000])
        await ctx.send(embed=e)

    @commands.command(name="botstatus", aliases=["status"], brief="[Админ] Состояние бота")
    @commands.has_permissions(administrator=True)
    async def botstatus(self, ctx):
        started = getattr(self.bot, "start_time", self.started)
        failed  = getattr(self.bot, "failed_cogs", {})
        e = discord.Embed(title="🤖 Состояние бота", color=discord.Color.blurple())
        e.add_field(name="Аптайм", value=fmt_duration(timedelta(seconds=int(time.time() - started))))
        e.add_field(name="Пинг", value=f"{round(self.bot.latency * 1000)} мс")
        e.add_field(name="Серверов", value=str(len(self.bot.guilds)))
        e.add_field(name="Модули", value=f"{len(self.bot.cogs)} загружено" +
                                        (f"\n❌ {', '.join(failed)}" if failed else ""))
        e.add_field(name="Python / py-cord", value=f"{platform.python_version()} / {discord.__version__}")
        e.add_field(name="Кейсов модерации", value=str(mod_data.get("next_case", 1) - 1))
        e.add_field(name="ИИ (Groq)", value=ai.status(), inline=False)
        await ctx.send(embed=e)

    @commands.command(name="reload", brief="[Владелец] Перезагрузить модуль без рестарта",
                      help="`!reload mcdonalds` или `!reload all` — применяет изменения кода cogs на лету.")
    @commands.is_owner()
    async def reload(self, ctx, name: str = "all"):
        names = list(self.bot.extensions) if name == "all" else [name if name.startswith("cogs.") else f"cogs.{name}"]
        ok, bad = [], []
        for ext in names:
            try:
                if ext in self.bot.extensions:
                    self.bot.reload_extension(ext)
                else:
                    self.bot.load_extension(ext)
                ok.append(ext.split(".")[-1])
                getattr(self.bot, "failed_cogs", {}).pop(ext, None)
            except Exception as e:
                bad.append(f"`{ext}`: {e}")
        text = f"🔄 Перезагружено: {', '.join(ok) or '—'}"
        if bad:
            text += "\n❌ " + "\n❌ ".join(bad)
        await ctx.send(text[:1990], delete_after=30)

    @commands.command(name="backup", brief="[Админ] Бэкап всех данных бота в ЛС")
    @commands.has_permissions(administrator=True)
    async def backup(self, ctx):
        buf = io.BytesIO()
        files = sorted(glob.glob("*.json"))
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for path in files:
                z.write(path)
        buf.seek(0)
        name = f"bazarcik_backup_{utcnow():%Y%m%d_%H%M}.zip"
        try:
            await ctx.author.send(f"💾 Бэкап данных: {len(files)} файлов.", file=discord.File(buf, name))
            await ctx.send("📬 Бэкап отправлен тебе в ЛС.", delete_after=8)
        except discord.Forbidden:
            await ctx.send("❌ Не могу написать в ЛС — разреши личные сообщения.", delete_after=8)

    @commands.command(name="adminhelp", aliases=["modhelp"], brief="Список команд администрации")
    async def adminhelp(self, ctx):
        e = discord.Embed(title="🛡️ Команды администрации", color=discord.Color.dark_red())
        e.add_field(name="Наказания", inline=False, value=(
            "`!mute @u [срок] [причина]` • `!unmute @u` — тайм-аут (10m, 2h, 1d)\n"
            "`!ban @u|ID [срок] [причина]` • `!unban ID` — бан, срок снимается сам\n"
            "`!kick @u [причина]` • `!warn @u [причина]` — 3/5/7 варнов: тайм-аут 1ч/1д/кик\n"
            "`!warns [@u]` • `!delwarn @u N` • `!clearwarn @u`\n"
            "`!case N` • `!history @u` — журнал наказаний"))
        e.add_field(name="Каналы и сообщения", inline=False, value=(
            "`!clear [N] [@u] [за 2ч] [до/после 18.10 20:00] [bots|links|files] [\"текст\"]` — фильтры сочетаются\n"
            "`!lock [#канал]` • `!unlock` • `!slowmode 10s|off`\n"
            "`!lockdown` / `!unlockdown` — закрыть/открыть весь сервер при рейде\n"
            "`!snipe` — последнее удалённое сообщение"))
        e.add_field(name="Настройка сервера", inline=False, value=(
            "`!setlog #канал` — логи событий и наказаний\n"
            "`!automod [on|off|правило on/off]` • `!badword add/remove/list`\n"
            "`!autorole @роль` • `!welcome #канал текст` • `!rolemenu Заголовок | @роли`\n"
            "`!nick @u [ник]` • `!role @u @роль`\n"
            "`!упоминания реакция [🔥|авто]|игнор|ответ` — когда о боте говорят в третьем лице"))
        e.add_field(name="Бот", inline=False, value=(
            "`!botstatus` — аптайм, пинг, модули, ИИ • `!backup` — данные в ЛС\n"
            "`!reload [модуль|all]` — перезагрузка кода (владелец бота)"))
        await ctx.send(embed=e)


def setup(bot):
    bot.add_cog(AdminCog(bot))
