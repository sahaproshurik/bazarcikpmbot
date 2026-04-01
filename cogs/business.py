import random
import time
from datetime import datetime, timezone
import discord
from discord.ext import commands, tasks
from data import (
    player_funds, player_businesses, server_effects,
    business_types, unique_items_biz,
    save_funds, save_businesses, save_server_eff,
)

INCOME_CHANNEL_ID = 1353724972677201980


def calc_next_biz_cost(uid, base_cost):
    count = len(player_businesses.get(str(uid), []))
    return base_cost if count == 0 else (base_cost * 5 if count == 1 else base_cost * 10)


def is_biz_name_unique(uid, name):
    return all(b["name"] != name for b in player_businesses.get(str(uid), []))


def apply_server_effect(effect: str, duration: int):
    server_effects[effect] = time.time() + duration
    save_server_eff()


def check_active_effects():
    now     = time.time()
    expired = [k for k, v in server_effects.items() if v < now]
    for k in expired: del server_effects[k]
    if expired: save_server_eff()


def _apply_biz_unique(uid: str, btype: str) -> str:
    if btype not in unique_items_biz:
        return "❌ Неизвестный тип бизнеса."
    item = unique_items_biz[btype]
    apply_server_effect(item["effect"], item["duration"])
    return f"🛠 **{item['item_name']}** применён! {item['description']}"


class BusinessCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.daily_business_income.start()
        self.tax_deduction_task.start()
        self.weekend_competition.start()

    def cog_unload(self):
        self.daily_business_income.cancel()
        self.tax_deduction_task.cancel()
        self.weekend_competition.cancel()

    @commands.command(name="buy_business", brief="Купить бизнес")
    async def buy_business(self, ctx, business_name: str, *, custom_name: str):
        await ctx.message.delete()
        uid = str(ctx.author.id)

        if business_name not in business_types:
            blist = ", ".join(business_types.keys())
            await ctx.send(f"❌ Тип не найден! Доступные: {blist}", delete_after=10); return
        if len(player_businesses.get(uid, [])) >= 3:
            await ctx.send("🚫 Максимум 3 бизнеса!", delete_after=5); return
        if not is_biz_name_unique(uid, custom_name):
            await ctx.send(f"❌ Название '{custom_name}' занято.", delete_after=5); return

        base = business_types[business_name]["base_cost"]
        cost = calc_next_biz_cost(uid, base)

        if player_funds.get(uid, 0) < cost:
            await ctx.send(f"❌ Нужно **{cost:,}** 💰 (есть **{player_funds.get(uid,0):,}**)", delete_after=5); return

        player_funds[uid] -= cost
        if uid not in player_businesses: player_businesses[uid] = []
        player_businesses[uid].append({
            "name": custom_name, "business_type": business_name,
            "profit": business_types[business_name]["base_profit"],
            "taxes":  business_types[business_name]["taxes"],
            "service_cost": business_types[business_name]["service_cost"],
            "upgraded": False, "upgrade_cost": business_types[business_name]["upgrade_cost"],
            "upgrade_count": 0, "last_upgrade": 0,
        })
        save_funds(); save_businesses()
        await ctx.send(f"✅ Бизнес **{custom_name}** ({business_name}) куплен за **{cost:,}** 💰!")

    @commands.command(name="sell_business", brief="Продать свой бизнес")
    async def sell_business_cmd(self, ctx, *, business_name: str):
        await ctx.message.delete()
        uid = str(ctx.author.id)
        for b in player_businesses.get(uid, []):
            if b["name"] == business_name:
                btype = b["business_type"]
                price = int(business_types[btype]["base_cost"] * 0.7)
                player_funds[uid] = player_funds.get(uid, 0) + price
                player_businesses[uid].remove(b)
                save_funds(); save_businesses()
                await ctx.send(f"💰 **{business_name}** продан за **{price:,}** 💰!"); return
        await ctx.send("❌ Бизнес не найден.", delete_after=5)

    @commands.command(name="upgrade_business", brief="Улучшить бизнес для роста прибыли")
    async def upgrade_business_cmd(self, ctx, *, business_name: str):
        await ctx.message.delete()
        uid = str(ctx.author.id)
        for b in player_businesses.get(uid, []):
            if b["name"] == business_name:
                if time.time() - b.get("last_upgrade", 0) < 86400:
                    await ctx.send("⏳ Улучшать раз в сутки!", delete_after=5); return
                cnt  = b.get("upgrade_count", 0)
                cost = int(business_types[b["business_type"]]["upgrade_cost"] * (1.5 ** cnt))
                mult = max(1.2, 2 - 0.2 * cnt)
                if player_funds.get(uid, 0) < cost:
                    await ctx.send(f"❌ Нужно **{cost:,}** 💰", delete_after=5); return
                player_funds[uid] -= cost
                b["profit"]        = int(b["profit"] * mult)
                b["upgrade_count"] = cnt + 1
                b["last_upgrade"]  = time.time()
                b["upgraded"]      = True
                msg = f"🔧 **{business_name}** улучшен! Прибыль: **{b['profit']}**/день"
                if random.random() < 0.1:
                    msg += "\n" + _apply_biz_unique(uid, b["business_type"])
                save_funds(); save_businesses()
                await ctx.send(msg); return
        await ctx.send("❌ Бизнес не найден.", delete_after=5)

    @commands.command(name="repair_business", brief="Отремонтировать бизнес")
    async def repair_business_cmd(self, ctx, *, business_name: str):
        await ctx.message.delete()
        uid = str(ctx.author.id)
        for b in player_businesses.get(uid, []):
            if b["name"] == business_name:
                btype = b["business_type"]
                cost  = int(business_types[btype]["base_cost"] * business_types[btype]["repair_cost"])
                if player_funds.get(uid, 0) < cost:
                    await ctx.send(f"❌ Нужно **{cost:,}** 💰", delete_after=5); return
                player_funds[uid] -= cost
                save_funds(); save_businesses()
                await ctx.send(f"🔧 **{business_name}** отремонтирован! Стоимость: **{cost:,}** 💰"); return
        await ctx.send("❌ Бизнес не найден.", delete_after=5)

    @commands.command(name="businesses", brief="Список своих бизнесов")
    async def list_businesses(self, ctx, member: discord.Member = None):
        await ctx.message.delete()
        if member is None: member = ctx.author
        uid   = str(member.id)
        blist = player_businesses.get(uid, [])
        if not blist:
            await ctx.send(f"{member.mention} не имеет бизнесов.", delete_after=5); return
        embed = discord.Embed(title=f"🏢 Бизнесы {member.display_name}", color=discord.Color.gold())
        for b in blist:
            status = "⬆️ Улучшен" if b.get("upgraded") else "🔷 Обычный"
            embed.add_field(
                name=f"{b['name']} ({b['business_type']})",
                value=f"💰 {b['profit']}/день | {status} | Ул: {b.get('upgrade_count',0)}",
                inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="business_info", brief="Информация о типах бизнесов")
    async def business_info_cmd(self, ctx):
        await ctx.message.delete()
        embed = discord.Embed(title="📋 Типы бизнесов", color=discord.Color.blue())
        for name, d in business_types.items():
            embed.add_field(
                name=f"🏢 {name}",
                value=(f"Стоимость: **{d['base_cost']:,}** 💰\n"
                       f"Прибыль: **{d['base_profit']}**/день\n"
                       f"Налог: {d['taxes']} | Улучшение: {d['upgrade_cost']}"),
                inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="use_item", brief="Применить уникальный эффект бизнеса")
    async def use_item_biz_cmd(self, ctx, *, business_type: str):
        await ctx.message.delete()
        uid = str(ctx.author.id)
        await ctx.send(_apply_biz_unique(uid, business_type))

    @commands.command(name="active_effects", brief="Посмотреть активные серверные эффекты")
    async def active_effects_cmd(self, ctx):
        await ctx.message.delete()
        check_active_effects()
        if not server_effects:
            await ctx.send("❌ Нет активных эффектов.", delete_after=5); return
        embed = discord.Embed(title="🔮 Активные серверные эффекты", color=discord.Color.purple())
        for eff, end in server_effects.items():
            dt = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%H:%M:%S UTC")
            embed.add_field(name=eff, value=f"До: {dt}", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="business_help", brief="Гайд по системе бизнесов")
    async def business_help_cmd(self, ctx):
        await ctx.message.delete()
        try:
            with open("business_help.txt", "r", encoding="utf-8") as f:
                await ctx.send(f.read())
        except FileNotFoundError:
            embed = discord.Embed(title="🏢 Помощь по бизнесам", color=discord.Color.green())
            cmds  = [
                ("!buy_business <тип> <название>", "Купить бизнес"),
                ("!sell_business <название>",      "Продать бизнес"),
                ("!upgrade_business <название>",   "Улучшить (раз в сутки)"),
                ("!repair_business <название>",    "Отремонтировать"),
                ("!businesses",                    "Мои бизнесы"),
                ("!business_info",                 "Типы и цены"),
                ("!active_effects",                "Серверные эффекты"),
            ]
            for cmd, desc in cmds:
                embed.add_field(name=f"`{cmd}`", value=desc, inline=False)
            await ctx.send(embed=embed)

    # ── Scheduled tasks ───────────────────────────────────────
    @tasks.loop(hours=1)
    async def daily_business_income(self):
        if datetime.now(timezone.utc).hour == 20:
            channel = self.bot.get_channel(INCOME_CHANNEL_ID)
            for uid, biznesy in player_businesses.items():
                total = sum(b["profit"] for b in biznesy)
                if total > 0:
                    player_funds[uid] = player_funds.get(uid, 0) + total
                    if channel:
                        try: await channel.send(f"💼 <@{uid}> получил прибыль от бизнесов: **{total:,}** 💰")
                        except Exception: pass
            save_funds()

    @tasks.loop(hours=1)
    async def tax_deduction_task(self):
        if datetime.now(timezone.utc).hour == 19:
            for uid, biznesy in player_businesses.items():
                total_tax = sum(b["taxes"] for b in biznesy)
                if total_tax > 0:
                    player_funds[uid] = max(0, player_funds.get(uid, 0) - total_tax)
            save_funds()

    @tasks.loop(hours=1)
    async def weekend_competition(self):
        now = datetime.now(timezone.utc)
        if now.weekday() == 6 and now.hour == 23:
            earnings = {uid: sum(b["profit"] for b in blist) for uid, blist in player_businesses.items()}
            top3     = sorted(earnings.items(), key=lambda x: x[1], reverse=True)[:3]
            rewards  = [{"money":500,"upgrades":3},{"money":200,"upgrades":1},{"money":100,"upgrades":0}]
            medals   = ["🥇","🥈","🥉"]
            lines    = ["**🏆 Итоги недельного соревнования бизнесов:**"]
            for i, (uid, profit) in enumerate(top3):
                r = rewards[i]
                player_funds[uid] = player_funds.get(uid, 0) + r["money"]
                if uid in player_businesses:
                    for _ in range(r["upgrades"]):
                        if player_businesses[uid]:
                            b = random.choice(player_businesses[uid])
                            b["profit"] = int(b["profit"] * 1.2)
                lines.append(f"{medals[i]} <@{uid}> — {profit:,} прибыли | Приз: {r['money']:,} 💰, улучшений: {r['upgrades']}")
            save_funds(); save_businesses()
            channel = self.bot.get_channel(INCOME_CHANNEL_ID)
            if channel:
                try: await channel.send("\n".join(lines))
                except Exception: pass


def setup(bot):
    bot.add_cog(BusinessCog(bot))
