import discord
from discord.ext import commands
from data import player_funds, player_bank, player_xp, priemer_data, player_warns
from cogs.xp import get_level
from cogs.economy import init_player


class InfoCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="profile", brief="Показать профиль игрока")
    async def profile(self, ctx, member: discord.Member = None):
        await ctx.message.delete()
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
        await ctx.message.delete()
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
        await ctx.message.delete()
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

    @commands.command(name="moneyhelp", brief="Гайд по денежной системе")
    async def moneyhelp(self, ctx):
        await ctx.message.delete()
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


async def setup(bot):
    await bot.add_cog(InfoCog(bot))
