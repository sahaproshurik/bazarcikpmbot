import asyncio
import discord
from discord.ext import commands
from data import player_funds, player_bank, player_xp, priemer_data, player_warns, whatsnew_seen, save_whatsnew
import whatsnew
from cogs.xp import get_level
from cogs.economy import init_player


class InfoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="profile", brief="Показать профиль игрока")
    async def profile(self, ctx, member: discord.Member = None):
        if member is None: member = ctx.author
        await init_player(self.bot, ctx)
        uid    = str(member.id)
        total  = player_xp.get(uid, 0)
        lvl, _ = get_level(total)
        cash   = player_funds.get(uid, 0)
        bank   = player_bank.get(uid, 0)
        pm     = priemer_data.get(uid, 0)
        warns  = len(player_warns.get(uid, []))

        embed = discord.Embed(title=f"👤 Профиль {member.display_name}", color=discord.Color.blurple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="⭐ Уровень",    value=str(lvl),           inline=True)
        embed.add_field(name="✨ Всего XP",   value=f"{total:,}",       inline=True)
        embed.add_field(name="💰 Наличные",   value=f"{cash:,}",        inline=True)
        embed.add_field(name="🏦 Банк",       value=f"{bank:,}",        inline=True)
        embed.add_field(name="📦 Приемер",    value=str(pm),             inline=True)
        embed.add_field(name="⚠️ Варны",      value=str(warns),          inline=True)
        embed.add_field(name="📅 На сервере", value=member.joined_at.strftime("%d.%m.%Y"), inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="userinfo", brief="Информация об участнике сервера")
    async def user_info(self, ctx, member: discord.Member = None):
        if member is None: member = ctx.author
        embed = discord.Embed(title=f"👤 {member.display_name}", color=discord.Color.blue())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="Имя",            value=member.display_name)
        embed.add_field(name="ID",             value=str(member.id))
        embed.add_field(name="Присоединился",  value=member.joined_at.strftime("%d.%m.%Y %H:%M"))
        embed.add_field(name="Аккаунт создан", value=member.created_at.strftime("%d.%m.%Y %H:%M"))
        embed.add_field(name="Роли",           value=", ".join(r.mention for r in member.roles[1:]) or "—")
        await ctx.send(embed=embed)

    @commands.command(name="serverinfo", brief="Информация о сервере")
    async def server_info(self, ctx):
        g     = ctx.guild
        embed = discord.Embed(title=f"🖥️ {g.name}", color=discord.Color.green())
        embed.add_field(name="ID",        value=str(g.id))
        embed.add_field(name="Создан",    value=g.created_at.strftime("%d.%m.%Y"))
        embed.add_field(name="Участники", value=str(g.member_count))
        embed.add_field(name="Каналы",    value=str(len(g.channels)))
        embed.add_field(name="Роли",      value=str(len(g.roles)))
        embed.add_field(name="Эмодзи",    value=str(len(g.emojis)))
        if g.icon: embed.set_thumbnail(url=g.icon.url)
        await ctx.send(embed=embed)

    @commands.command(name="whatsnew", aliases=["чтонового", "обновления"],
                      brief="Чему бот научился: что добавили с прошлого раза",
                      help="`!чтонового` — что добавили в бота с прошлого рассказа на этом сервере. После крупного "
                           "обновления — подборка по одному сообщению: дальше — кнопка ▶ или `!чтонового далее`.\n"
                           "`!чтонового все` — свежие обновления заново, `!чтонового подборка` — подборку с начала.\n"
                           "Словами: «@BazarčikPM чему новому ты научился», «что ещё нового».")
    async def whatsnew_cmd(self, ctx, *, mode: str = ""):
        gid = str(ctx.guild.id) if ctx.guild else "dm"
        mode = mode.strip().lower()
        rel = whatsnew.release()
        if rel is not None and mode in ("подборка", "сначала", "release"):
            whatsnew_seen.pop(whatsnew.release_key(gid), None)
        if rel is not None and mode not in ("все", "всё", "all", "заново"):
            page = whatsnew.release_page(whatsnew_seen, gid, rel)
            if page is not None:                              # подборка к обновлению — по странице на вопрос
                return await show_release(gid, rel, page, ctx.send)
        items = await asyncio.to_thread(whatsnew.history)      # git log — не держим цикл событий
        again = mode in ("все", "всё", "all", "заново")
        new = whatsnew.pick_new(items, None if again else whatsnew_seen.get(gid))
        shown, rest = whatsnew.batch(new)
        for embed in whatsnew.embeds_for(shown, items, rest):    # каждое изменение — своим сообщением
            await ctx.send(embed=embed)
        last = shown[-1]["id"] if shown else (items[0]["id"] if items else None)
        if last and whatsnew_seen.get(gid) != last:          # с остатком — продолжим с этого места
            whatsnew_seen[gid] = last
            save_whatsnew()

    @commands.command(name="moneyhelp", brief="Гайд по денежной системе")
    async def moneyhelp(self, ctx):
        try:
            with open("moneyhelp.txt", "r", encoding="utf-8") as f:
                await ctx.send(f.read())
        except FileNotFoundError:
            embed = discord.Embed(title="💰 Денежная система", color=discord.Color.gold())
            cmds  = [
                ("!money",                "Баланс (наличные + банк)"),
                ("!pay @user сумма",      "Перевод"),
                ("!deposit сумма",        "Положить в банк"),
                ("!withdraw сумма",       "Снять из банка"),
                ("!daily",                "Ежедневный бонус"),
                ("!rob @user",            "Ограбить (cooldown 1ч)"),
                ("!crime",                "Преступление (cooldown 30мин)"),
                ("!shop",                 "Магазин"),
                ("!buy <id>",             "Купить предмет"),
                ("!inventory",            "Инвентарь"),
                ("!applyloan сумма дней", "Оформить кредит"),
                ("!payloan сумма",        "Погасить кредит"),
                ("!checkloan",            "Статус кредита"),
                ("!top",                  "Топ богатейших"),
            ]
            for c, d in cmds:
                embed.add_field(name=f"`{c}`", value=d, inline=False)
            await ctx.send(embed=embed)


async def show_release(gid: str, rel: dict, page: int, send):
    """Страница подборки к обновлению; под ней — «▶ Далее», на последней — подборка досмотрена:
    коммиты, о которых она рассказала, считаются рассказанными, дальше — только новые."""
    last = page == len(rel["pages"]) - 1
    view = None if last else ReleaseView(gid, rel, page + 2)
    message = await send(embed=whatsnew.release_embed(rel, page), view=view)
    if view is not None:
        view.message = message
    key = whatsnew.release_key(gid)
    if last:
        whatsnew_seen[key] = {"id": rel["id"], "done": True}
        covered = await asyncio.to_thread(whatsnew.release_commit)
        if covered is None:                                  # без git — по последнему разделу CHANGES.md
            items = await asyncio.to_thread(whatsnew.history)
            covered = items[0]["id"] if items else None
        if covered:
            whatsnew_seen[gid] = covered
    else:
        whatsnew_seen[key] = {"id": rel["id"], "page": page + 1, "done": False}
    save_whatsnew()
    print(f"[whatsnew] {gid}: подборка {rel['id']} — {page + 1}/{len(rel['pages'])}"
          + (" (досмотрена)" if last else ""))


class ReleaseView(discord.ui.View):
    """«▶ Далее» под страницей подборки — жмёт любой: подборка общая для сервера."""

    def __init__(self, gid: str, rel: dict, number: int):
        super().__init__(timeout=15 * 60)
        self.gid, self.rel, self.message, self.used = gid, rel, None, False
        button = discord.ui.Button(label=f"Далее ({number}/{len(rel['pages'])})", emoji="▶️",
                                   style=discord.ButtonStyle.primary)
        button.callback = self._next
        self.add_item(button)

    async def _next(self, interaction: discord.Interaction):
        page = whatsnew.release_page(whatsnew_seen, self.gid, self.rel)
        if self.used or page is None:
            await interaction.response.send_message("Подборку уже досмотрели — дальше расскажу о новом, "
                                                    "когда добавим.", ephemeral=True)
            return
        self.used = True
        self.stop()
        await interaction.response.edit_message(view=None)
        await show_release(self.gid, self.rel, page, interaction.channel.send)

    async def on_timeout(self):
        if self.message is not None and not self.used:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


def setup(bot):
    bot.add_cog(InfoCog(bot))
