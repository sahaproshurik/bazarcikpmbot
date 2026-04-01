import random
import asyncio
import discord
from discord.ext import commands
from discord.ui import View, Button
from discord import Interaction
from data import (
    player_funds, player_inventory, priemer_data,
    SPORT_ITEMS_WITH_BRANDS, ORDERS, ORDER_MESSAGES, order_history,
    save_funds, save_priemer,
)
from cogs.economy import init_player


def generate_order():
    n = random.randint(1, 30)
    positions = []
    for _ in range(n):
        brand    = random.choice(list(SPORT_ITEMS_WITH_BRANDS.keys()))
        item     = random.choice(SPORT_ITEMS_WITH_BRANDS[brand])
        location = f"3{random.choice('BC')}{random.randint(1,56)}{random.choice('ABCDEFGHJ')}{random.randint(1,4)}"
        positions.append({"location": location, "item": f"{brand} - {item}", "status": "не выполнено"})
    return positions


# ── PickingView ───────────────────────────────────────────────
class PickingView(View):
    def __init__(self, user_id: str):
        super().__init__(timeout=None)
        self.user_id  = str(user_id)
        self._picking = False

        self.pick_btn = Button(label="Skenovat' produkt", style=discord.ButtonStyle.green)
        self.pick_btn.callback = self._pick

        self.exit_btn = Button(label="Выйти с работы", style=discord.ButtonStyle.red, disabled=True)
        self.exit_btn.callback = self._exit

        self.add_item(self.pick_btn)
        self.add_item(self.exit_btn)

    async def _pick(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        uid = self.user_id
        if uid not in ORDERS:
            await interaction.response.send_message("Нет активного заказа!", ephemeral=True); return
        if self._picking:
            await interaction.response.send_message("Подождите!", ephemeral=True); return

        await interaction.response.defer()
        self._picking = True

        positions = [p for p in ORDERS[uid] if p["status"] == "не выполнено"]
        if not positions:
            self._picking = False
            await self._switch_to_finish(interaction); return

        if random.random() < 0.03:
            self.pick_btn.disabled = True
            wait = random.randint(30, 180)
            for r in range(wait, 0, -15):
                try:
                    await interaction.message.edit(
                        content=f"{interaction.user.mention}, ошибка телефона — ждём сапорта. Ожидание: {r}с.", view=self)
                except Exception: pass
                await asyncio.sleep(15)
            self.pick_btn.disabled = False
            self._picking = False
            await interaction.message.edit(content=f"{interaction.user.mention}, продолжай пикинг.", view=self)
            return

        num = random.randint(1, 5)
        picked = 0
        for p in ORDERS[uid]:
            if p["status"] == "не выполнено" and picked < num:
                p["status"] = "выполнено"; picked += 1

        done = [f"✅ ~~{i+1}. {p['location']} ({p['item']})~~"
                for i, p in enumerate(ORDERS[uid]) if p["status"] == "выполнено"]
        todo = [f"{i+1}. {p['location']} ({p['item']})"
                for i, p in enumerate(ORDERS[uid]) if p["status"] == "не выполнено"]

        content = f"{interaction.user.mention}\n" + "\n".join(done[-10:]) + "\n\n" + "\n".join(todo[:20])
        if len(content) > 1950: content = content[:1950] + "..."

        remaining = [p for p in ORDERS[uid] if p["status"] == "не выполнено"]
        if not remaining:
            self._picking = False
            await self._switch_to_finish(interaction)
        else:
            delay = random.randint(1, 4)
            self.pick_btn.disabled = True
            try: await interaction.message.edit(content=content, view=self)
            except Exception: pass
            await asyncio.sleep(delay)
            self.pick_btn.disabled = False
            self._picking = False
            try: await interaction.message.edit(view=self)
            except Exception: pass

    async def _switch_to_finish(self, interaction: Interaction):
        self.clear_items()
        fb = Button(label="Odoslat' objednavku", style=discord.ButtonStyle.blurple)
        fb.callback = self._finish
        self.exit_btn.disabled = False
        self.add_item(fb); self.add_item(self.exit_btn)
        try: await interaction.message.edit(content=f"{interaction.user.mention}, все позиции собраны! Отправь заказ.", view=self)
        except Exception: pass

    async def _finish(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        await interaction.response.defer()
        uid = self.user_id
        num = len(ORDERS.get(uid, []))
        if uid not in order_history: order_history[uid] = []
        order_history[uid].append(num)

        pm = priemer_data.get(uid, 0)
        if   pm < 60:  earnings = random.randint(50,    10_000)
        elif pm < 80:  earnings = random.randint(10_000, 20_000)
        elif pm < 120: earnings = random.randint(20_000, 50_000)
        else:          earnings = random.randint(50_000, 100_000)

        if player_inventory.get(uid, {}).get("pickaxe", 0) > 0:
            earnings = int(earnings * 1.2)

        rate       = 0.07 if earnings <= 47000 else 0.19
        tax_amount = int(earnings * rate)
        net        = earnings - tax_amount

        player_funds[uid] = player_funds.get(uid, 0) + net
        save_funds()
        if uid in ORDERS:        del ORDERS[uid]
        if uid in ORDER_MESSAGES: del ORDER_MESSAGES[uid]

        self.clear_items()
        nb = Button(label="Новый заказ", style=discord.ButtonStyle.green)
        nb.callback = self._new_order
        self.exit_btn.disabled = False
        self.add_item(nb); self.add_item(self.exit_btn)
        try:
            await interaction.message.edit(
                content=(f"{interaction.user.mention}, заказ завершён!\n"
                         f"Начислено: **{earnings:,}** | Налог: **{tax_amount:,}** | Итого: **{net:,}** 💰\n"
                         f"Приемер: **{pm}**"),
                view=self)
        except Exception: pass

    async def _new_order(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        await interaction.response.defer()
        uid = self.user_id
        ORDERS[uid] = generate_order()
        priemer_data[uid] = priemer_data.get(uid, 0)
        save_priemer()

        pickup = "\n".join(f"{i+1}. {o['location']} ({o['item']})" for i,o in enumerate(ORDERS[uid]))
        if len(pickup) > 1800: pickup = pickup[:1800] + "..."
        nv  = PickingView(uid)
        msg = await interaction.channel.send(
            f"{interaction.user.mention}, новый заказ **{len(ORDERS[uid])}** позиций. Приемер: **{priemer_data[uid]}**\n\n**Пикап лист:**\n{pickup}",
            view=nv)
        ORDER_MESSAGES[uid] = msg.id
        try: await interaction.message.delete()
        except Exception: pass

    async def _exit(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        uid = self.user_id
        ORDERS.pop(uid, None); ORDER_MESSAGES.pop(uid, None)
        await interaction.message.edit(content=f"{interaction.user.mention}, вы вышли с работы.", view=None)


# ── PackingView ───────────────────────────────────────────────
class PackingView(View):
    def __init__(self, user_id: str, order_size: int):
        super().__init__(timeout=None)
        self.user_id      = str(user_id)
        self.order_size   = order_size
        self.remaining    = order_size
        self.selected_box = None

        box_map = {"A":range(1,7),"B":range(7,13),"C":range(13,19),"D":range(19,25),"E":range(25,31)}
        for box in box_map:
            btn = Button(label=f"Коробка {box}", style=discord.ButtonStyle.blurple)
            btn.callback = self._make_cb(box)
            self.add_item(btn)

        self.collect_btn = Button(label="Собрать товар", style=discord.ButtonStyle.green, disabled=True)
        self.collect_btn.callback = self._collect

        self.exit_btn = Button(label="Выйти с работы", style=discord.ButtonStyle.red, disabled=True)
        self.exit_btn.callback = self._exit

        self.add_item(self.collect_btn)
        self.add_item(self.exit_btn)

    def _make_cb(self, box):
        async def cb(interaction: Interaction):
            await self._select_box(interaction, box)
        return cb

    async def _select_box(self, interaction: Interaction, box: str):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        box_map = {"A":range(1,7),"B":range(7,13),"C":range(13,19),"D":range(19,25),"E":range(25,31)}
        if self.order_size not in box_map[box]:
            await interaction.response.send_message(
                f"Коробка **{box}** не подходит для {self.order_size} товаров!", ephemeral=True); return
        self.selected_box         = box
        self.collect_btn.disabled = False
        await interaction.message.edit(
            content=f"{interaction.user.mention}, коробка **{box}** выбрана. Осталось: **{self.remaining}** товаров.", view=self)

    async def _collect(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        if self.remaining > 0:
            self.remaining -= random.randint(1, min(5, self.remaining))
            if self.remaining > 0:
                await interaction.message.edit(
                    content=f"{interaction.user.mention}, осталось: **{self.remaining}** товаров.", view=self)
            else:
                await self._complete(interaction)

    async def _complete(self, interaction: Interaction):
        uid      = self.user_id
        earnings = random.randint(50, 10_000)
        player_funds[uid] = player_funds.get(uid, 0) + earnings
        save_funds()
        if uid in ORDERS: del ORDERS[uid]

        self.clear_items()
        self.exit_btn.disabled = False
        nb = Button(label="Новый заказ", style=discord.ButtonStyle.green)
        nb.callback = self._new_order
        self.add_item(nb); self.add_item(self.exit_btn)
        await interaction.message.edit(
            content=f"{interaction.user.mention}, баление завершено! Заработано: **{earnings:,}** 💰", view=self)

    async def _new_order(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        ns  = random.randint(1, 30)
        nv  = PackingView(self.user_id, ns)
        await interaction.message.edit(
            content=f"{interaction.user.mention}, новый заказ: **{ns}** товаров. Выберите коробку.", view=nv)

    async def _exit(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        uid = self.user_id
        ORDERS.pop(uid, None); ORDER_MESSAGES.pop(uid, None)
        await interaction.message.edit(content=f"{interaction.user.mention}, вы вышли с работы.", view=None)


# ── Cog ───────────────────────────────────────────────────────
class WorkCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self._update_priemer())

    @commands.command(name="gb", brief="Пойти работать на склад")
    async def start_job(self, ctx):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)
        job = random.choice(["пикинг", "баление"])

        if job == "пикинг":
            ORDERS[uid]       = generate_order()
            priemer_data[uid] = priemer_data.get(uid, 0)
            save_priemer()
            pickup = "\n".join(f"{i+1}. {o['location']} ({o['item']})" for i,o in enumerate(ORDERS[uid]))
            if len(pickup) > 1800: pickup = pickup[:1800] + "..."
            view = PickingView(uid)
            msg  = await ctx.send(
                f"{ctx.author.mention} 📦 Работа: **пикинг** | Заказ: **{len(ORDERS[uid])}** позиций | Приемер: **{priemer_data[uid]}**\n\n**Пикап лист:**\n{pickup}",
                view=view)
            ORDER_MESSAGES[uid] = msg.id
        else:
            order_size = random.randint(1, 30)
            ORDERS[uid] = [{"item": random.choice(random.choice(list(SPORT_ITEMS_WITH_BRANDS.values())))} for _ in range(order_size)]
            view = PackingView(uid, order_size)
            msg  = await ctx.send(
                f"{ctx.author.mention} 📦 Работа: **баление** | Заказ: **{order_size}** товаров. Выберите коробку.",
                view=view)
            ORDER_MESSAGES[uid] = msg.id

    @commands.command(name="priemer", brief="Посмотреть показатель эффективности работы")
    async def priemer_cmd(self, ctx):
        await ctx.message.delete()
        uid = str(ctx.author.id)
        pm  = priemer_data.get(uid, 0)
        embed = discord.Embed(title=f"📦 Приемер {ctx.author.display_name}", color=discord.Color.orange())
        bar_fill = int((pm / 150) * 20)
        bar = "█" * bar_fill + "░" * (20 - bar_fill)
        embed.add_field(name="Приемер",  value=f"{pm}/150")
        embed.add_field(name="Прогресс", value=f"`[{bar}]`")
        lv = "🔴 Низкий" if pm < 60 else ("🟡 Средний" if pm < 80 else ("🟢 Высокий" if pm < 120 else "💎 Максимум"))
        embed.add_field(name="Статус", value=lv)
        await ctx.send(embed=embed)

    async def _update_priemer(self):
        await self.bot.wait_until_ready()
        decay_counter = 0
        while not self.bot.is_closed():
            await asyncio.sleep(60)
            decay_counter += 1
            for uid in list(priemer_data.keys()):
                orders = order_history.get(uid, [])
                if orders:
                    avg_o   = len(orders)
                    avg_pos = sum(orders) / avg_o
                    priemer_data[uid] = int(min(150, priemer_data[uid] + (avg_o * avg_pos) / 10))
                elif decay_counter >= 60:
                    priemer_data[uid] = int(max(0, priemer_data[uid] - 1))
            if decay_counter >= 60:
                decay_counter = 0
            save_priemer()
            order_history.clear()


def setup(bot):
    bot.add_cog(WorkCog(bot))
