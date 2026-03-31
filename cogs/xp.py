import time
import random
import discord
from discord.ext import commands
from data import player_xp, XP_CD, XP_PER_MESSAGE, save_xp


def xp_for_level(lvl: int) -> int:
    return int(100 * (lvl ** 1.5))


def get_level(total_xp: int):
    lvl = 1
    xp  = total_xp
    while xp >= xp_for_level(lvl):
        xp -= xp_for_level(lvl)
        lvl += 1
    return lvl, xp


class XPCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        uid = str(message.author.id)
        now = time.time()
        if now - XP_CD.get(uid, 0) >= 60:
            gain = random.randint(*XP_PER_MESSAGE)
            old_xp = player_xp.get(uid, 0)
            player_xp[uid] = old_xp + gain
            XP_CD[uid] = now
            save_xp()
            old_lvl, _ = get_level(old_xp)
            new_lvl, _ = get_level(player_xp[uid])
            if new_lvl > old_lvl:
                try:
                    await message.channel.send(
                        f"🎉 {message.author.mention} достиг **{new_lvl} уровня**!",
                        delete_after=10,
                    )
                except Exception:
                    pass
        await self.bot.process_commands(message)

    @commands.command(
        name="level",
        brief="Показать уровень и XP",
        help=(
            "Показывает текущий уровень, количество XP и прогресс до следующего уровня.\n\n"
            "XP начисляется автоматически за сообщения (2–8 XP каждые 60 секунд).\n\n"
            "**Использование:**\n"
            "`!level` — твой уровень\n"
            "`!level @user` — уровень другого игрока\n\n"
            "**Формула:**\n"
            "XP для уровня N = 100 × N^1.5"
        ),
    )
    async def show_level(self, ctx, member: discord.Member = None):
        await ctx.message.delete()
        if member is None:
            member = ctx.author
        uid      = str(member.id)
        total    = player_xp.get(uid, 0)
        lvl, cur = get_level(total)
        needed   = xp_for_level(lvl)
        bar_fill = int((cur / needed) * 20) if needed else 20
        bar      = "█" * bar_fill + "░" * (20 - bar_fill)
        embed = discord.Embed(title=f"📊 Уровень {member.display_name}", color=discord.Color.purple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="⭐ Уровень",  value=str(lvl),                        inline=True)
        embed.add_field(name="✨ Всего XP", value=str(total),                       inline=True)
        embed.add_field(name="📈 Прогресс", value=f"`[{bar}]` {cur}/{needed}",      inline=False)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(XPCog(bot))
