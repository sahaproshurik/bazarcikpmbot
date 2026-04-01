import random
import time
import discord
from discord.ext import commands
from data import (
    player_funds, player_inventory, SHOP_ITEMS, FISH_TABLE, FISH_CD,
    LOTTO_POOL,
    save_funds, save_inventory,
)
from cogs.economy import init_player


class ShopCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Shop ──────────────────────────────────────────────────
    @commands.command(name="shop", brief="Показать магазин предметов")
    async def shop(self, ctx):
        await ctx.message.delete()
        embed = discord.Embed(title="🏪 Магазин BAZARCIK_PM", color=discord.Color.green())
        for iid, item in SHOP_ITEMS.items():
            embed.add_field(
                name=f"{item['name']} — {item['price']:,} 💰",
                value=f"`!buy {iid}` — {item['desc']}",
                inline=False,
            )
        await ctx.send(embed=embed)

    @commands.command(name="buy", brief="Купить предмет из магазина")
    async def buy_shop_item(self, ctx, item_id: str):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)
        if item_id not in SHOP_ITEMS:
            await ctx.send("❌ Товар не найден. Смотри `!shop`", delete_after=5); return
        item  = SHOP_ITEMS[item_id]
        price = item["price"]
        if player_funds.get(uid, 0) < price:
            await ctx.send(f"❌ Нужно **{price:,}** 💰, у вас **{player_funds.get(uid,0):,}**", delete_after=5); return
        player_funds[uid] -= price
        inv = player_inventory.get(uid, {})
        inv[item_id] = inv.get(item_id, 0) + 1
        player_inventory[uid] = inv
        save_funds(); save_inventory()
        await ctx.send(f"✅ {ctx.author.mention} купил **{item['name']}** за **{price:,}** 💰!")

    @commands.command(name="inventory", brief="Показать свой инвентарь")
    async def inventory(self, ctx, member: discord.Member = None):
        await ctx.message.delete()
        if member is None:
            member = ctx.author
        uid = str(member.id)
        inv = {k: v for k, v in player_inventory.get(uid, {}).items() if v > 0 and k in SHOP_ITEMS}
        if not inv:
            await ctx.send(f"{member.mention}, инвентарь пуст.", delete_after=5); return
        embed = discord.Embed(title=f"🎒 Инвентарь {member.display_name}", color=discord.Color.blue())
        for iid, qty in inv.items():
            embed.add_field(name=SHOP_ITEMS[iid]["name"], value=f"x{qty}", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="use", brief="Использовать предмет из инвентаря")
    async def use_item(self, ctx, item_id: str, member: discord.Member = None):
        await ctx.message.delete()
        uid = str(ctx.author.id)
        inv = player_inventory.get(uid, {})

        if inv.get(item_id, 0) <= 0:
            await ctx.send("❌ У вас нет этого предмета!", delete_after=5); return

        if item_id == "bomb":
            if member is None:
                await ctx.send("❌ Укажи цель: `!use bomb @user`", delete_after=5); return
            target = str(member.id)
            amount = int(player_funds.get(target, 0) * random.uniform(0.10, 0.30))
            player_funds[target] = max(0, player_funds.get(target, 0) - amount)
            player_funds[uid]    = player_funds.get(uid, 0) + amount
            inv[item_id] -= 1
            if inv[item_id] == 0: del inv[item_id]
            player_inventory[uid] = inv
            save_funds(); save_inventory()
            await ctx.send(f"💣 {ctx.author.mention} взорвал бомбу рядом с {member.mention} и украл **{amount:,}** 💰!")
        elif item_id == "lottery_ticket":
            await ctx.send("🎟 Используй команду `!lotto` для розыгрыша!", delete_after=5)
        else:
            await ctx.send(f"❌ Предмет `{item_id}` нельзя использовать напрямую.", delete_after=5)

    # ── Lottery ───────────────────────────────────────────────
    @commands.command(name="lotto", brief="Добавить билет в общую лотерею")
    async def lottery(self, ctx):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)
        gid = str(ctx.guild.id)
        inv = player_inventory.get(uid, {})

        if inv.get("lottery_ticket", 0) <= 0:
            await ctx.send(f"{ctx.author.mention}, купи лотерейный билет в `!shop`!", delete_after=5); return

        inv["lottery_ticket"] -= 1
        if inv["lottery_ticket"] == 0:
            del inv["lottery_ticket"]
        player_inventory[uid] = inv
        save_inventory()

        if gid not in LOTTO_POOL:
            LOTTO_POOL[gid] = {}
        LOTTO_POOL[gid][uid] = LOTTO_POOL[gid].get(uid, 0) + 1
        total = sum(LOTTO_POOL[gid].values())
        await ctx.send(f"🎟️ {ctx.author.mention} добавил билет в лотерею! Всего билетов: **{total}**. Розыгрыш через `!drawlotto`.")

    @commands.command(name="drawlotto", brief="[Админ] Провести розыгрыш лотереи")
    @commands.has_permissions(administrator=True)
    async def draw_lottery(self, ctx):
        await ctx.message.delete()
        gid = str(ctx.guild.id)
        if gid not in LOTTO_POOL or not LOTTO_POOL[gid]:
            await ctx.send("🎟 Нет билетов в пуле!", delete_after=5); return

        pool    = LOTTO_POOL[gid]
        tickets = []
        for uid, count in pool.items():
            tickets.extend([uid] * count)

        winner_id = random.choice(tickets)
        prize     = len(tickets) * 400
        player_funds[winner_id] = player_funds.get(winner_id, 0) + prize
        save_funds()
        LOTTO_POOL[gid] = {}

        try:
            winner = ctx.guild.get_member(int(winner_id)) or await ctx.guild.fetch_member(int(winner_id))
            name   = winner.mention
        except Exception:
            name = f"<@{winner_id}>"
        await ctx.send(f"🎉 **ЛОТЕРЕЯ!** Победитель: {name} с призом **{prize:,}** 💰! 🎊")

    # ── Fishing ───────────────────────────────────────────────
    @commands.command(name="fish", brief="Порыбачить и заработать деньги")
    async def fish(self, ctx):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)

        if player_inventory.get(uid, {}).get("fishing_rod", 0) <= 0:
            await ctx.send(f"{ctx.author.mention}, нужна удочка! Купи в `!shop`.", delete_after=5); return

        now = time.time()
        if now - FISH_CD.get(uid, 0) < 300:
            rem = int(300 - (now - FISH_CD.get(uid, 0)))
            await ctx.send(f"⏳ Следующая рыбалка через **{rem}сек**.", delete_after=10); return

        FISH_CD[uid] = now
        items, weights = zip(*((f[0], f[2]) for f in FISH_TABLE))
        catch  = random.choices(items, weights=weights, k=1)[0]
        reward = next(f[1] for f in FISH_TABLE if f[0] == catch)
        player_funds[uid] = player_funds.get(uid, 0) + reward
        save_funds()
        await ctx.send(f"🎣 {ctx.author.mention} поймал **{catch}** и получил **{reward}** 💰!")


def setup(bot):
    bot.add_cog(ShopCog(bot))
