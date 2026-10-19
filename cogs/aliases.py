"""
aliases.py — прозвища участников: «Петруха», «Юрчик» → конкретный ID. По ним бот понимает, о ком речь:
«@BazarčikPM замуть Петруху», «Базарчик, сколько денег у Юрчика». Хранилище и сравнение имён — names.py.

Кто что может:
• администратор (право «Администратор» или владелец сервера) — меняет прозвища любого участника сразу
  и без ограничений: может забрать прозвище у другого, совпасть с чужим именем, превысить лимит;
• остальные — только СВОИ прозвища и только с одобрения администратора: бот публикует запрос с кнопками,
  одобрить может любой администратор (в течение APPROVAL_SEC). Чужие прозвища — нельзя совсем.
Смотреть: свои — любой (`!alias`), чужие и весь список сервера — только администраторы.
"""
from dataclasses import dataclass
from typing import Optional
import discord
from discord.ext import commands
import names
from views import GREEN, RED

APPROVAL_SEC = 3600
COLOR = discord.Color.blurple()


def is_admin(member, channel) -> bool:
    guild = member.guild
    if getattr(guild, "owner_id", None) == member.id or getattr(getattr(guild, "owner", None), "id", None) == member.id:
        return True
    return bool(channel.permissions_for(member).administrator)


def clean(alias: str) -> str:
    return names.clean_alias(alias)


def problem(guild, target, alias: str, admin: bool) -> Optional[str]:
    """Почему прозвище нельзя добавить; None — можно. Администратору — только технические проверки."""
    low, high = names.ALIAS_LEN
    if "<@" in alias or "@everyone" in alias or "@here" in alias:
        return "в прозвище не должно быть упоминаний"
    if not low <= len(alias) <= high:
        return f"прозвище — от {low} до {high} символов"
    key = names.norm_name(alias)
    if not key:
        return "в прозвище нужны буквы или цифры"
    if alias.lower() in names.SELF_WORDS:
        return "это слово бот понимает как «я» — выбери другое"
    if names.stored_alias(guild.id, target.id, alias):
        return f"у {target.display_name} уже есть прозвище «{alias}»"
    if admin:
        return None
    owner = names.alias_owner(guild.id, alias)
    if owner is not None and owner != target.id:
        who = guild.get_member(owner)
        return f"прозвище «{alias}» уже у {who.display_name if who else 'другого участника'}"
    for m in getattr(guild, "members", []):
        if m.id != target.id and not m.bot and any(
                names.norm_name(n) == key for n in (m.display_name, m.name, getattr(m, "global_name", None) or "")):
            return f"так зовут {m.display_name} — будет путаница"
    if len(names.aliases_of(guild.id, target.id)) >= names.MAX_ALIASES:
        return f"у {target.display_name} уже {names.MAX_ALIASES} прозвищ — это максимум"
    return None


@dataclass
class Change:
    kind: str           # add, remove, clear
    target: object
    alias: str
    author: object

    @property
    def what(self) -> str:
        alias = discord.utils.escape_markdown(self.alias)
        whom = "себе" if self.target.id == self.author.id else self.target.mention
        return {"add": f"добавить {whom} прозвище «{alias}»",
                "remove": f"убрать {'своё' if whom == 'себе' else 'у ' + whom} прозвище «{alias}»",
                "clear": f"убрать {'все свои прозвища' if whom == 'себе' else 'все прозвища у ' + whom}"}[self.kind]


def apply(change: Change) -> str:
    """Применяет изменение и возвращает текст для чата."""
    guild, t, alias = change.target.guild, change.target, change.alias
    shown = discord.utils.escape_markdown(alias)
    if change.kind == "add":
        previous = names.add_alias(guild.id, t.id, alias)
        took = guild.get_member(previous) if previous else None
        text = f"🏷️ {t.mention} теперь откликается и на «{shown}»" + (
            f" (прозвище забрано у {took.display_name if took else 'другого участника'})" if previous else "") + "."
    elif change.kind == "remove":
        names.remove_alias(guild.id, t.id, alias)
        text = f"🗑️ У {t.mention} больше нет прозвища «{shown}»."
    else:
        text = f"🧽 У {t.mention} убраны все прозвища ({names.clear_aliases(guild.id, t.id)})."
    print(f"[alias] {change.author.display_name}: {change.kind} «{alias}» → {t.display_name}")
    return text


class ApprovalView(discord.ui.View):
    """Запрос на своё прозвище: одобряет администратор, отклонить может он же или автор запроса."""

    def __init__(self, cog, change: Change):
        super().__init__(timeout=APPROVAL_SEC)
        self.cog, self.change, self.done, self.message = cog, change, False, None
        for label, emoji, style, cb in (("Одобрить", "✅", GREEN, self.on_approve), ("Отклонить", "✖️", RED, self.on_reject)):
            button = discord.ui.Button(label=label, emoji=emoji, style=style)
            button.callback = cb
            self.add_item(button)

    async def on_approve(self, interaction):
        if not is_admin(interaction.user, interaction.channel):
            return await interaction.response.send_message("Одобрить может только администратор.", ephemeral=True)
        await self.finish(interaction, True)

    async def on_reject(self, interaction):
        if not (is_admin(interaction.user, interaction.channel) or interaction.user.id == self.change.author.id):
            return await interaction.response.send_message("Отклонить может администратор или автор запроса.",
                                                           ephemeral=True)
        await self.finish(interaction, False)

    def close(self) -> bool:
        if self.done:
            return False
        self.done = True
        self.cog.requests.pop((self.change.target.guild.id, self.change.author.id), None)
        self.stop()
        return True

    async def finish(self, interaction, approved: bool):
        if not self.close():
            return await interaction.response.send_message("Запрос уже решён.", ephemeral=True)
        who = interaction.user.display_name
        if not approved:
            status = f"✖️ Отклонил {who}."
        elif self.change.kind == "add" and (err := problem(self.change.target.guild, self.change.target,
                                                           self.change.alias, admin=False)):
            status = f"❌ Не применено: {err}."
        else:
            status = f"✅ Одобрил {who}. {apply(self.change)}"
        print(f"[alias] Запрос {self.change.author.display_name} «{self.change.alias}»: "
              f"{'одобрен' if approved else 'отклонён'} ({who})")
        await interaction.response.edit_message(embed=request_embed(self.change, status), view=None)

    async def on_timeout(self):
        if self.close() and self.message is not None:
            try:
                await self.message.edit(embed=request_embed(self.change, "⌛ Никто из администраторов не ответил "
                                                                         "за час — запрос закрыт."), view=None)
            except discord.HTTPException:
                pass


def request_embed(change: Change, status: str = None) -> discord.Embed:
    e = discord.Embed(title="🏷️ Запрос на прозвище", color=discord.Color.orange() if not status else COLOR,
                      description=f"{change.author.mention} хочет {change.what}.")
    if status:
        e.add_field(name="Итог", value=status, inline=False)
    else:
        e.set_footer(text="Одобрить может администратор • запрос действует час")
    return e


class AliasCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.requests: dict = {}            # (guild_id, user_id) → ApprovalView — по одному запросу на человека

    async def change(self, ctx, change: Change):
        """Администратор — сразу, остальные — запрос администраторам (только для своих прозвищ)."""
        if is_admin(ctx.author, ctx.channel):
            return await ctx.send(apply(change))
        if change.target.id != ctx.author.id:
            return await ctx.send("❌ Чужие прозвища меняют только администраторы. Свои — можно, "
                                  "с одобрения администратора.", delete_after=12)
        key = (ctx.guild.id, ctx.author.id)
        if key in self.requests:
            return await ctx.send("⏳ У тебя уже есть запрос на прозвище — дождись решения администратора.",
                                  delete_after=12)
        view = ApprovalView(self, change)
        self.requests[key] = view
        view.message = await ctx.send(embed=request_embed(change), view=view)
        print(f"[alias] {ctx.author.display_name}: запрос «{change.kind} {change.alias}» ждёт администратора")

    # ── Команды ───────────────────────────────────────────────
    @commands.group(
        name="alias", aliases=["прозвища", "aka"], invoke_without_command=True,
        brief="Прозвища участника — по ним бот понимает, о ком речь",
        help="`!alias` — твои прозвища. Администраторам: `!alias @user` — прозвища участника, "
             "`!alias list` — все на сервере.\n"
             "`!alias add [@user] прозвище` — добавить, `!alias remove [@user] прозвище` — убрать, "
             "`!alias clear [@user]` — убрать все.\n"
             "Администраторы меняют прозвища любого участника сразу. Остальные — только свои и только "
             "с одобрения администратора (бот пришлёт запрос с кнопками).\n"
             "Можно и словами: «@BazarčikPM запомни, что Петруха — это Петя», «зови меня Сашка».")
    @commands.guild_only()
    async def alias(self, ctx, *, member: discord.Member = None):
        member = member or ctx.author
        if member.id != ctx.author.id and not is_admin(ctx.author, ctx.channel):
            return await ctx.send("❌ Чужие прозвища смотрят только администраторы. Свои — `!alias`.", delete_after=10)
        found = names.aliases_of(ctx.guild.id, member.id)
        e = discord.Embed(title=f"🏷️ {member.display_name}", color=COLOR, description=(
            "Откликается на: " + ", ".join(f"«{discord.utils.escape_markdown(a)}»" for a in found) if found
            else "Прозвищ пока нет. Добавить: `!alias add прозвище`"))
        await ctx.send(embed=e)

    @alias.command(name="add", aliases=["добавить"], brief="Добавить прозвище")
    @commands.guild_only()
    async def alias_add(self, ctx, member: Optional[discord.Member] = None, *, alias: str):
        target, alias = member or ctx.author, clean(alias)
        if target.bot:
            return await ctx.send("❌ Ботам прозвища не нужны.", delete_after=8)
        if err := problem(ctx.guild, target, alias, is_admin(ctx.author, ctx.channel)):
            return await ctx.send(f"❌ Нельзя: {err}.", delete_after=12)
        await self.change(ctx, Change("add", target, alias, ctx.author))

    @alias.command(name="remove", aliases=["del", "убрать"], brief="Убрать прозвище")
    @commands.guild_only()
    async def alias_remove(self, ctx, member: Optional[discord.Member] = None, *, alias: str):
        alias = clean(alias)
        if member is None:                  # «убери прозвище Петруха» — у кого оно есть
            owner = names.alias_owner(ctx.guild.id, alias)
            member = ctx.guild.get_member(owner) if owner else ctx.author
        stored = names.stored_alias(ctx.guild.id, member.id, alias)
        if stored is None:
            return await ctx.send(f"❌ У {member.display_name} нет прозвища «{discord.utils.escape_markdown(alias)}».",
                                  delete_after=10)
        await self.change(ctx, Change("remove", member, stored, ctx.author))

    @alias.command(name="clear", aliases=["очистить"], brief="Убрать все прозвища участника")
    @commands.guild_only()
    async def alias_clear(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        if not names.aliases_of(ctx.guild.id, member.id):
            return await ctx.send(f"❌ У {member.display_name} нет прозвищ.", delete_after=8)
        await self.change(ctx, Change("clear", member, "", ctx.author))

    @alias.command(name="list", aliases=["все", "all"], brief="Все прозвища на сервере")
    @commands.guild_only()
    async def alias_list(self, ctx):
        if not is_admin(ctx.author, ctx.channel):
            return await ctx.send("❌ Все прозвища сервера смотрят только администраторы. Свои — `!alias`.",
                                  delete_after=10)
        lines = []
        for uid, found in sorted(names.all_aliases(ctx.guild.id).items()):
            member = ctx.guild.get_member(uid)
            if member is not None:
                lines.append(f"**{discord.utils.escape_markdown(member.display_name)}** — "
                             + ", ".join(discord.utils.escape_markdown(a) for a in found))
        e = discord.Embed(title="🏷️ Прозвища на сервере", color=COLOR,
                          description="\n".join(lines)[:4000] or "Пока ни у кого нет прозвищ.")
        await ctx.send(embed=e)


def setup(bot):
    bot.add_cog(AliasCog(bot))
