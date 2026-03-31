import random
import time
from datetime import datetime, timezone
import discord
from discord.ext import commands
from data import (
    player_funds, player_bank, player_daily, player_xp,
    DAILY_REWARDS, TAX_THRESHOLD, ROB_CD, CRIME_CD, SHOP_ITEMS,
    player_inventory,
    save_funds, save_bank, save_daily, save_inventory,
)


async def init_player(bot, uid_or_ctx):
    uid = str(uid_or_ctx.author.id) if hasattr(uid_or_ctx, "author") else str(uid_or_ctx)
    if uid not in player_funds:
        player_funds[uid] = 1000
        save_funds()
    if uid not in player_bank:
        player_bank[uid] = 0
        save_bank()


def calculate_tax(profit: int) -> int:
    return int(profit * 0.18) if profit > TAX_THRESHOLD else 0


class EconomyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Balance ───────────────────────────────────────────────
    @commands.command(name="money", brief="Проверить баланс")
    async def check_funds(self, ctx):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid  = str(ctx.author.id)
        cash = player_funds.get(uid, 0)
        bank = player_bank.get(uid, 0)
        embed = discord.Embed(title=f"💼 Баланс {ctx.author.display_name}", color=discord.Color.gold())
        embed.add_field(name="💰 Наличные", value=f"{cash:,}", inline=True)
        embed.add_field(name="🏦 Банк",     value=f"{bank:,}", inline=True)
        embed.add_field(name="💎 Всего",    value=f"{cash+bank:,}", inline=True)
        embed.set_thumbnail(url=ctx.author.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="pay", brief="Перевести деньги другому игроку")
    async def pay(self, ctx, member: discord.Member, amount: int):
        await ctx.message.delete()
        sender   = str(ctx.author.id)
        receiver = str(member.id)
        if amount <= 0:
            await ctx.send(f"{ctx.author.mention}, сумма должна быть > 0!", delete_after=5); return
        if player_funds.get(sender, 0) < amount:
            await ctx.send(f"{ctx.author.mention}, недостаточно средств!", delete_after=5); return
        player_funds[sender] -= amount
        player_funds[receiver] = player_funds.get(receiver, 0) + amount
        save_funds()
        await ctx.send(f"💸 {ctx.author.mention} перевёл **{amount:,}** 💰 → {member.mention}")

    @commands.command(name="deposit", brief="Положить деньги в банк")
    async def deposit(self, ctx, amount: int):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)
        if amount <= 0 or player_funds.get(uid, 0) < amount:
            await ctx.send("❌ Неверная сумма или недостаточно наличных!", delete_after=5); return
        player_funds[uid] -= amount
        player_bank[uid]   = player_bank.get(uid, 0) + amount
        save_funds(); save_bank()
        await ctx.send(f"🏦 {ctx.author.mention} внёс **{amount:,}** в банк. Банк: **{player_bank[uid]:,}** 💰")

    @commands.command(name="withdraw", brief="Снять деньги из банка")
    async def withdraw(self, ctx, amount: int):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)
        if amount <= 0 or player_bank.get(uid, 0) < amount:
            await ctx.send("❌ Неверная сумма или недостаточно в банке!", delete_after=5); return
        player_bank[uid]  -= amount
        player_funds[uid]  = player_funds.get(uid, 0) + amount
        save_funds(); save_bank()
        await ctx.send(f"💰 {ctx.author.mention} снял **{amount:,}** из банка. Наличные: **{player_funds[uid]:,}** 💰")

    # ── Leaderboards ──────────────────────────────────────────
    @commands.command(name="top", brief="Топ-10 богатейших игроков")
    async def leaderboard(self, ctx):
        await ctx.message.delete()
        combined = {}
        for uid in set(list(player_funds.keys()) + list(player_bank.keys())):
            combined[uid] = player_funds.get(uid, 0) + player_bank.get(uid, 0)
        top    = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:10]
        medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        lines  = []
        for i, (uid, total) in enumerate(top):
            try:
                m    = ctx.guild.get_member(int(uid)) or await ctx.guild.fetch_member(int(uid))
                name = m.display_name
            except Exception:
                name = f"<@{uid}>"
            lines.append(f"{medals[i]} **{name}** — {total:,} 💰")
        embed = discord.Embed(title="💎 Топ-10 богатейших", color=discord.Color.gold(),
                              description="\n".join(lines) or "—")
        await ctx.send(embed=embed)

    @commands.command(name="toplevel", brief="Топ-10 игроков по уровню")
    async def top_level(self, ctx):
        await ctx.message.delete()
        from cogs.xp import get_level
        top    = sorted(player_xp.items(), key=lambda x: x[1], reverse=True)[:10]
        medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
        lines  = []
        for i, (uid, xp) in enumerate(top):
            lvl, _ = get_level(xp)
            try:
                m    = ctx.guild.get_member(int(uid)) or await ctx.guild.fetch_member(int(uid))
                name = m.display_name
            except Exception:
                name = f"<@{uid}>"
            lines.append(f"{medals[i]} **{name}** — Lvl {lvl} ({xp:,} XP)")
        embed = discord.Embed(title="⭐ Топ-10 по уровням", color=discord.Color.blurple(),
                              description="\n".join(lines) or "—")
        await ctx.send(embed=embed)

    # ── Daily ─────────────────────────────────────────────────
    @commands.command(name="daily", brief="Получить ежедневный бонус")
    async def daily_bonus(self, ctx):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid  = str(ctx.author.id)
        now  = datetime.now(timezone.utc)
        data = player_daily.get(uid, {"last": None, "streak": 0})

        if data["last"]:
            last_dt = datetime.fromisoformat(data["last"])
            diff    = (now - last_dt).total_seconds()
            if diff < 86400:
                rem  = int(86400 - diff)
                h, r = divmod(rem, 3600)
                m    = r // 60
                await ctx.send(f"⏳ {ctx.author.mention}, следующий бонус через **{h}ч {m}мин**.", delete_after=10)
                return
            if diff > 172800:
                data["streak"] = 0

        streak = min(data["streak"] + 1, len(DAILY_REWARDS))
        bonus  = DAILY_REWARDS[streak - 1]
        if player_inventory.get(uid, {}).get("vip_pass", 0) > 0:
            bonus = int(bonus * 1.5)

        data["streak"] = streak
        data["last"]   = now.isoformat()
        player_daily[uid] = data
        player_funds[uid] = player_funds.get(uid, 0) + bonus
        save_daily(); save_funds()
        await ctx.send(f"🎁 {ctx.author.mention} ежедневный бонус: **+{bonus:,}** 💰 | Серия: **{streak}** 🔥")

    # ── Rob ───────────────────────────────────────────────────
    @commands.command(name="rob", brief="Ограбить другого игрока")
    async def rob(self, ctx, member: discord.Member):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        robber = str(ctx.author.id)
        victim = str(member.id)

        if member.id == ctx.author.id:
            await ctx.send("Нельзя ограбить самого себя!", delete_after=5); return

        victim_inv = player_inventory.get(victim, {})
        if victim_inv.get("shield", 0) > 0:
            victim_inv["shield"] -= 1
            if victim_inv["shield"] == 0:
                del victim_inv["shield"]
            player_inventory[victim] = victim_inv
            save_inventory()
            await ctx.send(f"🛡️ {member.mention} был защищён щитом! {ctx.author.mention} ушёл ни с чем.", delete_after=10)
            return

        now = time.time()
        if now - ROB_CD.get(robber, 0) < 3600:
            rem = int(3600 - (now - ROB_CD.get(robber, 0)))
            await ctx.send(f"⏳ Следующее ограбление через **{rem//60}мин {rem%60}сек**.", delete_after=10); return

        victim_cash = player_funds.get(victim, 0)
        if victim_cash < 200:
            await ctx.send(f"💸 {member.mention} слишком беден — не стоит рисковать!", delete_after=5); return

        ROB_CD[robber] = now
        if random.random() < 0.45:
            amount = random.randint(100, min(5000, int(victim_cash * 0.3)))
            player_funds[victim]  = victim_cash - amount
            player_funds[robber]  = player_funds.get(robber, 0) + amount
            save_funds()
            await ctx.send(f"🦹 {ctx.author.mention} ограбил {member.mention} на **{amount:,}** 💰!")
        else:
            fine = random.randint(200, 1500)
            player_funds[robber] = max(0, player_funds.get(robber, 0) - fine)
            save_funds()
            await ctx.send(f"👮 {ctx.author.mention} попался и заплатил штраф **{fine:,}** 💰!")

    # ── Crime ─────────────────────────────────────────────────
    @commands.command(name="crime", brief="Совершить преступление (заработок/риск)")
    async def crime(self, ctx):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)
        now = time.time()
        if now - CRIME_CD.get(uid, 0) < 1800:
            rem = int(1800 - (now - CRIME_CD.get(uid, 0)))
            await ctx.send(f"⏳ Следующее преступление через **{rem//60}мин**.", delete_after=10); return
        CRIME_CD[uid] = now

        crimes = [
            ("карманную кражу",       200,  800),
            ("угон велосипеда",       300, 1200),
            ("мошенничество в сети",  500, 2000),
            ("кражу в магазине",      150,  600),
            ("незаконную торговлю",  1000, 5000),
            ("взлом банкомата",       800, 4000),
        ]
        name, fine_max, reward_max = random.choice(crimes)
        if random.random() < 0.4:
            fine = random.randint(fine_max // 2, fine_max)
            player_funds[uid] = max(0, player_funds.get(uid, 0) - fine)
            save_funds()
            await ctx.send(f"👮 {ctx.author.mention} попался на **{name}** и заплатил штраф **{fine:,}** 💰!")
        else:
            reward = random.randint(fine_max, reward_max)
            player_funds[uid] = player_funds.get(uid, 0) + reward
            save_funds()
            await ctx.send(f"😈 {ctx.author.mention} успешно провернул **{name}** и заработал **{reward:,}** 💰!")

    # ── Admin money ───────────────────────────────────────────
    @commands.command(name="give", brief="[Админ] Выдать деньги участнику")
    @commands.has_permissions(administrator=True)
    async def give_money(self, ctx, member: discord.Member, amount: int):
        await ctx.message.delete()
        uid = str(member.id)
        player_funds[uid] = player_funds.get(uid, 0) + amount
        save_funds()
        await ctx.send(f"✅ {member.mention} получил **{amount:,}** 💰. Баланс: **{player_funds[uid]:,}**")

    @commands.command(name="take", brief="[Админ] Снять деньги с участника")
    @commands.has_permissions(administrator=True)
    async def take_money(self, ctx, member: discord.Member, amount: int):
        await ctx.message.delete()
        uid = str(member.id)
        player_funds[uid] = max(0, player_funds.get(uid, 0) - amount)
        save_funds()
        await ctx.send(f"✅ У {member.mention} снято **{amount:,}** 💰. Баланс: **{player_funds[uid]:,}**")

    @commands.command(name="setmoney", brief="[Админ] Установить баланс участника")
    @commands.has_permissions(administrator=True)
    async def set_money(self, ctx, member: discord.Member, amount: int):
        await ctx.message.delete()
        uid = str(member.id)
        player_funds[uid] = amount
        save_funds()
        await ctx.send(f"✅ Баланс {member.mention} установлен: **{amount:,}** 💰")


async def setup(bot):
    await bot.add_cog(EconomyCog(bot))
