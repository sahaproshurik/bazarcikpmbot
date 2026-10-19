"""
moderation.py — модерация: нативные тайм-ауты Discord, баны с автоснятием (переживают перезапуск),
варны с автоэскалацией, очистка сообщений с фильтрами, блокировка каналов и локдаун сервера.
Каждое действие получает номер кейса и уходит в лог-канал (см. !setlog).
"""
import time
from datetime import datetime, timedelta
from typing import Optional, Union
import discord
from discord.ext import commands, tasks
from data import player_warns, save_warns, mod_data, save_mod
from names import MemberRef, find_member
from purge_filters import ClearSpec, parse_clear, SCAN as CLEAR_SCAN
from utils import parse_duration, fmt_duration, utcnow, log_action

MAX_TIMEOUT = timedelta(days=28)   # лимит Discord на тайм-аут
LEGACY_MUTE_ROLE = "БАН банан🍌"   # роль старой системы мутов — снимаем при !unmute
PERMANENT = {"0", "perm", "навсегда", "forever", "-"}
# количество варнов → автоматическое наказание
WARN_ESCALATION = {
    3: ("mute", timedelta(hours=1)),
    5: ("mute", timedelta(days=1)),
    7: ("kick", None),
}


def hierarchy_error(ctx, member: MemberRef):
    """Нельзя наказать себя, владельца, бота и того, чья роль не ниже твоей или моей."""
    if member == ctx.author:
        return "Нельзя применить к самому себе."
    if member == ctx.guild.owner:
        return "Нельзя наказать владельца сервера."
    if member == ctx.guild.me:
        return "Я не буду наказывать сам себя 🙃"
    if ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role:
        return "Роль участника не ниже твоей."
    if member.top_role >= ctx.guild.me.top_role:
        return "Моя роль ниже роли участника — подними роль бота в настройках сервера."
    return None


async def dm(user, text: str):
    try:
        await user.send(text)
    except (discord.Forbidden, discord.HTTPException):
        pass


def split_duration(duration: Optional[str], reason: str, default_unit: str):
    """Если первый аргумент — не срок, значит это начало причины."""
    td = parse_duration(duration, default_unit) if duration else None
    if duration and td is None and duration.lower() not in PERMANENT:
        reason = duration if reason == "Не указана" else f"{duration} {reason}"
    return td, reason


class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.clearing: set = set()        # каналы, где сейчас идёт !clear — вторую очистку не запускаем
        self.tempban_watcher.start()

    def cog_unload(self):
        self.tempban_watcher.cancel()

    async def deny(self, ctx, text: str):
        await ctx.send(f"❌ {text}", delete_after=8)

    # ── Тайм-ауты ─────────────────────────────────────────────
    @commands.command(
        name="mute", aliases=["timeout"], brief="[Мод] Тайм-аут участнику",
        help="`!mute @user [срок] [причина]` — срок: 30s, 10m, 2h, 1d, 1h30m (число = минуты), "
             "по умолчанию 10 минут, максимум 28 дней. Работает через нативный тайм-аут Discord.")
    @commands.has_permissions(moderate_members=True)
    async def mute(self, ctx, member: MemberRef, duration: str = None, *, reason: str = "Не указана"):
        if err := hierarchy_error(ctx, member):
            return await self.deny(ctx, err)
        td, reason = split_duration(duration, reason, "m")
        td = min(td or timedelta(minutes=10), MAX_TIMEOUT)
        await member.timeout_for(td, reason=f"{ctx.author}: {reason}")
        case = await log_action(ctx.guild, "mute", member, ctx.author, reason, td)
        await ctx.send(f"🔇 {member.mention} в тайм-ауте на **{fmt_duration(td)}**. "
                       f"Причина: **{reason}** • кейс #{case}")
        await dm(member, f"🔇 Вы получили тайм-аут на **{ctx.guild.name}** на {fmt_duration(td)}.\nПричина: {reason}")

    @commands.command(name="unmute", aliases=["untimeout"], brief="[Мод] Снять тайм-аут")
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx, member: MemberRef, *, reason: str = "Не указана"):
        legacy = discord.utils.get(ctx.guild.roles, name=LEGACY_MUTE_ROLE)
        had_legacy = legacy is not None and legacy in member.roles
        if not member.timed_out and not had_legacy:
            return await self.deny(ctx, f"{member.mention} не в тайм-ауте.")
        if member.timed_out:
            await member.remove_timeout(reason=f"{ctx.author}: {reason}")
        if had_legacy:
            await member.remove_roles(legacy, reason="Снятие мута старой системы")
        case = await log_action(ctx.guild, "unmute", member, ctx.author, reason)
        await ctx.send(f"🔊 С {member.mention} снят тайм-аут • кейс #{case}")

    # ── Баны и кики ───────────────────────────────────────────
    @commands.command(
        name="ban", brief="[Мод] Забанить (можно на срок)",
        help="`!ban @user|ID [срок] [причина]` — срок: 7 (дней), 12h, 2w, perm. Без срока — навсегда.\n"
             "Временный бан снимется автоматически, даже если бот перезапускался. "
             "Можно банить по ID тех, кого нет на сервере.")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, user: MemberRef(allow_users=True), duration: str = None, *,
                  reason: str = "Не указана"):
        if isinstance(user, discord.Member) and (err := hierarchy_error(ctx, user)):
            return await self.deny(ctx, err)
        td, reason = split_duration(duration, reason, "d")
        term = f"на {fmt_duration(td)}" if td else "навсегда"
        await dm(user, f"🔨 Вы забанены на **{ctx.guild.name}** {term}.\nПричина: {reason}")
        await ctx.guild.ban(user, reason=f"{ctx.author}: {reason}", delete_message_seconds=7 * 86400)
        mod_data["tempbans"] = [t for t in mod_data["tempbans"]
                                if not (t["guild"] == ctx.guild.id and t["user"] == user.id)]
        if td:
            mod_data["tempbans"].append({"guild": ctx.guild.id, "user": user.id,
                                         "until": (utcnow() + td).isoformat()})
        save_mod()
        case = await log_action(ctx.guild, "ban", user, ctx.author, reason, td)
        await ctx.send(f"🔨 {user.mention} забанен **{term}**. Причина: **{reason}** • кейс #{case}")

    @commands.command(name="unban", brief="[Мод] Разбанить по ID или имени")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, who: str, *, reason: str = "Не указана"):
        target = None
        async for entry in ctx.guild.bans(limit=None):
            u = entry.user
            if who.strip("<@!>") == str(u.id) or who.lower() in (u.name.lower(), str(u).lower()):
                target = u
                break
        if target is None:
            return await self.deny(ctx, f"В списке банов нет `{who}`.")
        await ctx.guild.unban(target, reason=f"{ctx.author}: {reason}")
        mod_data["tempbans"] = [t for t in mod_data["tempbans"]
                                if not (t["guild"] == ctx.guild.id and t["user"] == target.id)]
        save_mod()
        case = await log_action(ctx.guild, "unban", target, ctx.author, reason)
        await ctx.send(f"✅ {target.mention} разбанен • кейс #{case}")

    @tasks.loop(minutes=1)
    async def tempban_watcher(self):
        now, done, due = utcnow(), [], []
        for tb in mod_data["tempbans"]:
            try:
                if datetime.fromisoformat(tb["until"]) <= now:
                    due.append(tb)
            except (KeyError, TypeError, ValueError):
                print(f"[moderation] Удаляю некорректную запись временного бана: {tb}")
                done.append(tb)
        for tb in due:
            if await self._lift_ban(tb):
                done.append(tb)
        if done:
            # пересобираем список заново: пока шли запросы, модераторы могли добавить новые баны
            mod_data["tempbans"] = [t for t in mod_data["tempbans"] if t not in done]
            save_mod()

    async def _lift_ban(self, tb: dict) -> bool:
        """Снимает истёкший бан. False — временная ошибка, запись остаётся и повторится через минуту."""
        guild = self.bot.get_guild(tb["guild"])
        if guild is None:
            return True                      # бота больше нет на этом сервере
        try:
            user = await self.bot.fetch_user(tb["user"])
            await guild.unban(user, reason="Срок бана истёк")
        except discord.NotFound:
            return True                      # уже разбанен вручную или аккаунт удалён
        except discord.HTTPException as e:
            print(f"[moderation] Не удалось снять бан {tb}, повторю через минуту: {e}")
            return False
        await log_action(guild, "unban", user, self.bot.user, "Срок бана истёк")
        return True

    @tempban_watcher.before_loop
    async def _before_watcher(self):
        await self.bot.wait_until_ready()

    @commands.command(name="kick", brief="[Мод] Кикнуть участника с сервера")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, member: MemberRef, *, reason: str = "Не указана"):
        if err := hierarchy_error(ctx, member):
            return await self.deny(ctx, err)
        await dm(member, f"👢 Вас выгнали с **{ctx.guild.name}**.\nПричина: {reason}")
        await member.kick(reason=f"{ctx.author}: {reason}")
        case = await log_action(ctx.guild, "kick", member, ctx.author, reason)
        await ctx.send(f"👢 {member.mention} выгнан. Причина: **{reason}** • кейс #{case}")

    # ── Варны ─────────────────────────────────────────────────
    @commands.command(
        name="warn", brief="[Мод] Выдать предупреждение",
        help="`!warn @user [причина]`. Автоэскалация: 3 варна — тайм-аут 1ч, 5 — тайм-аут 1д, 7 — кик.")
    @commands.has_permissions(moderate_members=True)
    async def warn_member(self, ctx, member: MemberRef, *, reason: str = "Не указана"):
        if member.bot:
            return await self.deny(ctx, "Ботов не предупреждают.")
        warns = player_warns.setdefault(str(member.id), [])
        warns.append({"reason": reason, "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
                      "by": str(ctx.author.id)})
        save_warns()
        count = len(warns)
        case  = await log_action(ctx.guild, "warn", member, ctx.author, f"#{count}: {reason}")
        text  = f"⚠️ {member.mention}, предупреждение **#{count}**! Причина: **{reason}** • кейс #{case}"
        await dm(member, f"⚠️ Вы получили предупреждение на **{ctx.guild.name}**.\nПричина: {reason}\nВарн #{count}")

        step = WARN_ESCALATION.get(count)
        if step:
            action, td = step
            auto = f"Автоэскалация: {count} варнов"
            if hierarchy_error(ctx, member):
                text += "\n⚠️ Автонаказание пропущено: не хватает прав по иерархии ролей."
            elif action == "mute":
                await member.timeout_for(td, reason=auto)
                await log_action(ctx.guild, "mute", member, self.bot.user, auto, td)
                text += f"\n🔇 Автоматически: тайм-аут на **{fmt_duration(td)}**."
            elif action == "kick":
                await dm(member, f"👢 Вы выгнаны с **{ctx.guild.name}**: {auto}.")
                await member.kick(reason=auto)
                await log_action(ctx.guild, "kick", member, self.bot.user, auto)
                text += "\n👢 Автоматически: кик с сервера."
        await ctx.send(text)

    @commands.command(name="warns", brief="Посмотреть предупреждения игрока")
    async def check_warns(self, ctx, member: MemberRef = None):
        member = member or ctx.author
        warns  = player_warns.get(str(member.id), [])
        embed  = discord.Embed(title=f"⚠️ Варны {member.display_name}: {len(warns)}", color=discord.Color.orange())
        if not warns:
            embed.description = "Нет предупреждений. ✅"
        for i, w in enumerate(warns, 1):
            if i > len(warns) - 10:
                by = f" • выдал <@{w['by']}>" if w.get("by") else ""
                embed.add_field(name=f"#{i} — {w['date']}", value=f"{w['reason']}{by}", inline=False)
        nxt = [(n, a) for n, a in sorted(WARN_ESCALATION.items()) if n > len(warns)]
        if nxt:
            n, (action, td) = nxt[0]
            what = f"тайм-аут {fmt_duration(td)}" if action == "mute" else "кик"
            embed.set_footer(text=f"На {n}-м варне: {what}")
        await ctx.send(embed=embed)

    @commands.command(name="delwarn", brief="[Мод] Удалить один варн по номеру")
    @commands.has_permissions(moderate_members=True)
    async def delwarn(self, ctx, member: MemberRef, number: int):
        warns = player_warns.get(str(member.id), [])
        if not 1 <= number <= len(warns):
            return await self.deny(ctx, f"У {member.display_name} нет варна #{number}.")
        removed = warns.pop(number - 1)
        save_warns()
        await ctx.send(f"🧽 Варн #{number} ({removed['reason']}) снят с {member.mention}. Осталось: {len(warns)}")

    @commands.command(name="clearwarn", brief="[Мод] Снять все варны с участника")
    @commands.has_permissions(moderate_members=True)
    async def clear_warns(self, ctx, member: MemberRef):
        player_warns[str(member.id)] = []
        save_warns()
        await ctx.send(f"✅ Все предупреждения {member.mention} сброшены.")

    # ── Очистка сообщений ─────────────────────────────────────
    async def purge(self, ctx, spec: ClearSpec):
        """Удаляет по фильтрам (purge_filters.py). Одна очистка на канал, лимиты — там же."""
        key = getattr(ctx.channel, "id", None)
        if key in self.clearing:
            return await self.deny(ctx, "В этом канале уже идёт очистка — дождись, пока она закончится.")
        scan = CLEAR_SCAN if spec.filtered else min(CLEAR_SCAN, spec.limit + 100)   # +запас на закреплённые
        self.clearing.add(key)
        started = time.monotonic()
        deleted = []
        try:
            # не purge: он листает все scan сообщений, даже когда нужные уже набрались; after — не старше 14 дней
            async for m in ctx.channel.history(limit=scan, after=spec.after, before=spec.before, oldest_first=False):
                if spec.match(m):
                    deleted.append(m)
                    if len(deleted) >= spec.limit:
                        break
            for i in range(0, len(deleted), 100):
                await ctx.channel.delete_messages(deleted[i:i + 100], reason=f"{ctx.author}: !clear")
        finally:
            self.clearing.discard(key)
        what = spec.describe(ctx.guild)
        print(f"[clear] {ctx.author}: удалено {len(deleted)} ({what}), просмотрено до {scan}, "
              f"{time.monotonic() - started:.1f} с")
        if not deleted:
            return await ctx.send(f"🔎 Ничего не нашлось: {what} (смотрел до {scan} последних сообщений "
                                  "моложе 14 дней, закреплённые не трогаю).", delete_after=12)
        await ctx.send(f"🗑️ Удалено **{len(deleted)}** сообщ.: {what}.", delete_after=8)

    async def purge_query(self, ctx, query: str):
        try:
            spec = parse_clear(query, resolve=lambda name: find_member(ctx.guild, name, ctx.author).id)
        except ValueError as e:
            return await self.deny(ctx, f"{e}.")
        await self.purge(ctx, spec)

    @commands.command(
        name="clear", aliases=["purge"], brief="[Мод] Удалить сообщения: сколько, чьи, за какое время",
        help="`!clear [N] [фильтры]` — фильтры можно сочетать:\n"
             "• число — сколько удалить (1–500); без числа — до 500 подходящих\n"
             "• `@user`, ID, ник или прозвище («от Петрухи», можно нескольких) — только их сообщения\n"
             "• `за 2ч` / `за 30m` / `за сегодня` / `за вчера` — за период\n"
             "• `после 18.10 12:00` / `до 20:00` / `до вчера` — с какого или до какого момента\n"
             "• `bots`, `humans`, `links`, `files` — от ботов, от людей, со ссылками, с файлами\n"
             "• `\"текст\"` — в сообщении есть этот текст\n"
             "Примеры: `!clear 50`, `!clear @Петя за 2ч`, `!clear до 18.10 20:00 bots`, `!clear за сегодня \"казино\"`.\n"
             "Ограничения: до 500 удалений и до 2000 просмотренных сообщений за раз, только моложе 14 дней "
             "(старше Discord пачкой не удаляет), закреплённые не трогаются. Время — по Братиславе.")
    @commands.has_permissions(manage_messages=True)
    async def clear_messages(self, ctx, *, query: str = ""):
        await self.purge_query(ctx, query)

    @commands.command(name="clearday", brief="[Мод] Удалить сообщения за N дней (то же, что !clear за Nd)")
    @commands.has_permissions(manage_messages=True)
    async def clearday(self, ctx, days: int):
        if not 1 <= days <= 14:
            return await self.deny(ctx, "Дней от 1 до 14.")
        await self.purge_query(ctx, f"за {days}d")

    @commands.command(name="clearuser", brief="[Мод] Удалить N последних сообщений участника (!clear @user N)")
    @commands.has_permissions(manage_messages=True)
    async def clearuser(self, ctx, member: MemberRef, amount: int):
        await self.purge_query(ctx, f"<@{member.id}> {amount}")

    @commands.command(name="clearuserday", brief="[Мод] Удалить сообщения участника за N дней (!clear @user за Nd)")
    @commands.has_permissions(manage_messages=True)
    async def clearuserdays(self, ctx, member: MemberRef, days: int):
        if not 1 <= days <= 14:
            return await self.deny(ctx, "Дней от 1 до 14.")
        await self.purge_query(ctx, f"<@{member.id}> за {days}d")

    # ── Каналы ────────────────────────────────────────────────
    async def _set_send(self, channel: discord.TextChannel, allow: Optional[bool], reason: str):
        everyone = channel.guild.default_role
        ow = channel.overwrites_for(everyone)
        ow.send_messages = allow
        ow.send_messages_in_threads = allow
        await channel.set_permissions(everyone, overwrite=ow, reason=reason)

    @commands.command(name="lock", brief="[Мод] Закрыть канал для сообщений")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx, channel: Optional[discord.TextChannel] = None, *, reason: str = "Не указана"):
        channel = channel or ctx.channel
        await self._set_send(channel, False, f"{ctx.author}: {reason}")
        await log_action(ctx.guild, "lock", channel, ctx.author, reason)
        await channel.send(f"🔒 Канал закрыт модератором. Причина: **{reason}**")

    @commands.command(name="unlock", brief="[Мод] Открыть канал")
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx, channel: Optional[discord.TextChannel] = None):
        channel = channel or ctx.channel
        await self._set_send(channel, None, f"{ctx.author}: unlock")
        await log_action(ctx.guild, "unlock", channel, ctx.author)
        await channel.send("🔓 Канал снова открыт.")

    @commands.command(name="lockdown", brief="[Админ] Закрыть ВСЕ текстовые каналы (рейд)")
    @commands.has_permissions(administrator=True)
    async def lockdown(self, ctx, *, reason: str = "Рейд / экстренная ситуация"):
        everyone, locked = ctx.guild.default_role, []
        for ch in ctx.guild.text_channels:
            if ch.permissions_for(everyone).send_messages and ch.permissions_for(ctx.guild.me).manage_roles:
                await self._set_send(ch, False, f"Локдаун: {reason}")
                locked.append(ch.id)
        prev = mod_data["lockdown"].get(str(ctx.guild.id), [])
        mod_data["lockdown"][str(ctx.guild.id)] = sorted(set(prev) | set(locked))
        save_mod()
        await log_action(ctx.guild, "lock", f"{len(locked)} каналов (локдаун)", ctx.author, reason)
        await ctx.send(f"🚨 **Локдаун!** Закрыто каналов: **{len(locked)}**. Причина: {reason}\n"
                       f"Снять: `!unlockdown`")

    @commands.command(name="unlockdown", brief="[Админ] Снять локдаун сервера")
    @commands.has_permissions(administrator=True)
    async def unlockdown(self, ctx):
        ids = mod_data["lockdown"].pop(str(ctx.guild.id), [])
        save_mod()
        opened = 0
        for cid in ids:
            ch = ctx.guild.get_channel(cid)
            if ch is not None:
                await self._set_send(ch, None, "Локдаун снят")
                opened += 1
        await log_action(ctx.guild, "unlock", f"{opened} каналов (локдаун)", ctx.author)
        await ctx.send(f"✅ Локдаун снят, открыто каналов: **{opened}**.")

    @commands.command(name="slowmode", aliases=["slow"], brief="[Мод] Медленный режим канала")
    @commands.has_permissions(manage_channels=True)
    async def slowmode(self, ctx, delay: str = "off", channel: Optional[discord.TextChannel] = None):
        channel = channel or ctx.channel
        if delay.lower() in ("off", "0", "выкл"):
            seconds = 0
        else:
            td = parse_duration(delay, "s")
            if td is None or td.total_seconds() > 21600:
                return await self.deny(ctx, "Задержка: от 1s до 6h, например `!slowmode 10s` или `!slowmode off`.")
            seconds = int(td.total_seconds())
        await channel.edit(slowmode_delay=seconds)
        if seconds:
            text = f"🐢 Медленный режим: **{fmt_duration(timedelta(seconds=seconds))}**"
        else:
            text = "🐇 Медленный режим выключен"
        await ctx.send(f"{text} в {channel.mention}.", delete_after=10)

    # ── Участники ─────────────────────────────────────────────
    @commands.command(name="nick", brief="[Мод] Сменить или сбросить ник участника")
    @commands.has_permissions(manage_nicknames=True)
    async def nick(self, ctx, member: MemberRef, *, nickname: str = None):
        await member.edit(nick=nickname, reason=f"{ctx.author}")
        result = f"изменён на **{nickname}**" if nickname else "сброшен"
        await ctx.send(f"✏️ Ник {member.mention} {result}.", delete_after=10)

    @commands.command(name="role", brief="[Мод] Выдать/забрать роль участнику")
    @commands.has_permissions(manage_roles=True)
    async def role(self, ctx, member: MemberRef, *, role: discord.Role):
        if ctx.author != ctx.guild.owner and role >= ctx.author.top_role:
            return await self.deny(ctx, "Эта роль не ниже твоей — выдать её нельзя.")
        if role >= ctx.guild.me.top_role or role.managed:
            return await self.deny(ctx, "Эту роль я выдать не могу (она выше моей или управляется интеграцией).")
        if role in member.roles:
            await member.remove_roles(role, reason=f"{ctx.author}")
            await ctx.send(f"➖ У {member.mention} забрана роль **{role.name}**.", delete_after=10)
        else:
            await member.add_roles(role, reason=f"{ctx.author}")
            await ctx.send(f"➕ {member.mention} получает роль **{role.name}**.", delete_after=10)

    # ── Журнал ────────────────────────────────────────────────
    @commands.command(name="case", brief="[Мод] Показать кейс модерации по номеру")
    @commands.has_permissions(moderate_members=True)
    async def case(self, ctx, case_id: int):
        c = next((c for c in mod_data["cases"] if c["id"] == case_id and c["guild"] == ctx.guild.id), None)
        if c is None:
            return await self.deny(ctx, f"Кейс #{case_id} не найден.")
        e = discord.Embed(title=f"📁 Кейс #{c['id']} — {c['action']}", color=discord.Color.blurple())
        e.add_field(name="Цель", value=f"<@{c['target']}>" if c["target"] else c["target_name"])
        e.add_field(name="Модератор", value=f"<@{c['moderator']}>" if c["moderator"] else "—")
        if c["duration"]:
            e.add_field(name="Срок", value=fmt_duration(timedelta(seconds=c["duration"])))
        e.add_field(name="Причина", value=c["reason"] or "—", inline=False)
        e.add_field(name="Когда", value=f"<t:{int(datetime.fromisoformat(c['at']).timestamp())}:f>", inline=False)
        await ctx.send(embed=e)

    @commands.command(name="history", aliases=["modlog"], brief="[Мод] История наказаний участника")
    @commands.has_permissions(moderate_members=True)
    async def history(self, ctx, user: MemberRef(allow_users=True)):
        cases = [c for c in mod_data["cases"] if c["target"] == user.id and c["guild"] == ctx.guild.id]
        e = discord.Embed(title=f"📁 История {user.display_name}: {len(cases)} кейсов", color=discord.Color.blurple())
        e.description = "\n".join(
            f"`#{c['id']}` <t:{int(datetime.fromisoformat(c['at']).timestamp())}:d> **{c['action']}** — {c['reason']}"
            for c in cases[-15:]) or "Чисто ✅"
        await ctx.send(embed=e)


def setup(bot):
    bot.add_cog(ModerationCog(bot))
