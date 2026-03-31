import asyncio
from datetime import datetime, timedelta, timezone
import discord
from discord.ext import commands
from data import player_warns, save_warns


class ModerationCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="mute", brief="[Админ] Замутить участника")
    @commands.has_permissions(administrator=True)
    async def mute(self, ctx, member: discord.Member, mute_time: int):
        await ctx.message.delete()
        await ctx.send(f"⏳ {member.mention}, у тебя 1 минута перед мутом на **{mute_time}** минут.")
        await asyncio.sleep(60)
        role = discord.utils.get(ctx.guild.roles, name="БАН банан🍌")
        if not role:
            role = await ctx.guild.create_role(name="БАН банан🍌")
            for ch in ctx.guild.text_channels:
                await ch.set_permissions(role, speak=False, send_messages=False)
        await member.add_roles(role)
        await ctx.send(f"🔇 {member.mention} замучен на **{mute_time}** минут.")
        await asyncio.sleep(mute_time * 60)
        await member.remove_roles(role)
        await ctx.send(f"🔊 {member.mention} размучен.")

    @commands.command(name="unmute", brief="[Админ] Снять мут с участника")
    @commands.has_permissions(administrator=True)
    async def unmute(self, ctx, member: discord.Member):
        await ctx.message.delete()
        role = discord.utils.get(ctx.guild.roles, name="БАН банан🍌")
        if role and role in member.roles:
            await member.remove_roles(role)
            await ctx.send(f"🔊 {member.mention} размучен.")
        else:
            await ctx.send(f"{member.mention} не замучен.", delete_after=5)

    @commands.command(name="ban", brief="[Админ] Забанить участника")
    @commands.has_permissions(administrator=True)
    async def ban(self, ctx, member: discord.Member, ban_days: int):
        await ctx.message.delete()
        await ctx.send(f"⏳ {member.mention}, у тебя 1 минута перед баном на **{ban_days}** дней.")
        await asyncio.sleep(60)
        await member.ban(reason=f"Бан на {ban_days} дней", delete_message_days=7)
        await ctx.send(f"🔨 {member.mention} забанен на **{ban_days}** дней.")
        await asyncio.sleep(ban_days * 86400)
        await ctx.guild.unban(member)
        await ctx.send(f"✅ {member.mention} разбанен.")

    @commands.command(name="kick", brief="[Админ] Кикнуть участника с сервера")
    @commands.has_permissions(administrator=True)
    async def kick(self, ctx, member: discord.Member, *, reason: str = "Не указана"):
        await ctx.message.delete()
        await member.kick(reason=reason)
        await ctx.send(f"👢 {member.mention} выгнан. Причина: **{reason}**")

    @commands.command(name="warn", brief="[Админ] Выдать предупреждение участнику")
    @commands.has_permissions(administrator=True)
    async def warn_member(self, ctx, member: discord.Member, *, reason: str = "Не указана"):
        await ctx.message.delete()
        uid = str(member.id)
        if uid not in player_warns: player_warns[uid] = []
        player_warns[uid].append({
            "reason": reason,
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
            "by": str(ctx.author.id),
        })
        save_warns()
        count = len(player_warns[uid])
        await ctx.send(f"⚠️ {member.mention}, предупреждение #{count}! Причина: **{reason}**")
        try: await member.send(f"⚠️ Вы получили предупреждение на **{ctx.guild.name}**.\nПричина: {reason}\nВарн #{count}")
        except Exception: pass

    @commands.command(name="warns", brief="Посмотреть предупреждения игрока")
    async def check_warns(self, ctx, member: discord.Member = None):
        await ctx.message.delete()
        if member is None: member = ctx.author
        uid  = str(member.id)
        wrnl = player_warns.get(uid, [])
        embed = discord.Embed(title=f"⚠️ Варны {member.display_name}", color=discord.Color.orange())
        if not wrnl:
            embed.description = "Нет предупреждений. ✅"
        else:
            for i, w in enumerate(wrnl[-10:], 1):
                embed.add_field(name=f"#{i}", value=f"{w['reason']} ({w['date']})", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="clearwarn", brief="[Админ] Снять все варны с участника")
    @commands.has_permissions(administrator=True)
    async def clear_warns(self, ctx, member: discord.Member):
        await ctx.message.delete()
        player_warns[str(member.id)] = []
        save_warns()
        await ctx.send(f"✅ Все предупреждения {member.mention} сброшены.")

    @commands.command(name="clear", brief="[Админ] Удалить сообщения в канале")
    @commands.has_permissions(administrator=True)
    async def clear_messages(self, ctx, amount: int):
        await ctx.message.delete()
        if not 1 <= amount <= 100:
            await ctx.send("Количество от 1 до 100.", delete_after=5); return
        deleted = await ctx.channel.purge(limit=amount)
        msg = await ctx.send(f"🗑️ Удалено **{len(deleted)}** сообщений.")
        await asyncio.sleep(3); await msg.delete()

    @commands.command(name="clearday", brief="[Админ] Удалить сообщения за N дней")
    @commands.has_permissions(administrator=True)
    async def clearday(self, ctx, days: int):
        await ctx.message.delete()
        if days <= 0:
            await ctx.send("Дней > 0.", delete_after=5); return
        limit   = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = await ctx.channel.purge(after=limit)
        msg = await ctx.send(f"🗑️ Удалено **{len(deleted)}** сообщений за {days} дней.")
        await asyncio.sleep(3); await msg.delete()

    @commands.command(name="clearuser", brief="[Админ] Удалить сообщения конкретного участника")
    @commands.has_permissions(administrator=True)
    async def clearuser(self, ctx, member: discord.Member, amount: int):
        await ctx.message.delete()
        if amount <= 0:
            await ctx.send("Количество > 0.", delete_after=5); return
        deleted = await ctx.channel.purge(limit=amount, check=lambda m: m.author == member)
        await ctx.send(f"🗑️ Удалено **{len(deleted)}** сообщений от {member.mention}.", delete_after=5)

    @commands.command(name="clearuserday", brief="[Админ] Удалить сообщения участника за N дней")
    @commands.has_permissions(administrator=True)
    async def clearuserdays(self, ctx, member: discord.Member, days: int):
        await ctx.message.delete()
        if days <= 0:
            await ctx.send("Дней > 0.", delete_after=5); return
        limit   = datetime.now(timezone.utc) - timedelta(days=days)
        deleted = 0
        async for msg in ctx.channel.history(limit=500):
            if msg.author == member and msg.created_at.replace(tzinfo=timezone.utc) >= limit:
                await msg.delete(); deleted += 1
        await ctx.send(f"🗑️ Удалено **{deleted}** сообщений от {member.mention} за {days} дней.", delete_after=5)


async def setup(bot):
    await bot.add_cog(ModerationCog(bot))
