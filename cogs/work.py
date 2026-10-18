"""
work.py — смена на складе GymBeam: пикинг по маршруту и упаковка (balenie).

• Пикинг: сканер ведёт по уличкам склада — сканируй правильную уличку, собери заказ и отправь его.
  Оплата зависит от Приемера (!priemer), который растёт от собранных позиций.
• Упаковка: подбери коробку под заказ и упакуй в правильном порядке.
Точность важна: без ошибок +10%, каждая ошибка −5% (не больше −30%).
"""
import asyncio
import random
import time
from collections import Counter
import discord
from discord.ext import commands, tasks
from discord import Interaction
from data import (
    player_funds, player_inventory, priemer_data,
    SPORT_ITEMS_WITH_BRANDS, ORDERS, order_history,
    save_funds, save_priemer,
)
from cogs.economy import init_player, work_tax
from views import OwnedView, progress_bar, GREY, GREEN, BLUE, RED

GB_ORANGE = discord.Color.from_rgb(255, 102, 0)
ZONES     = "BC"
SHELVES   = "ABCDEFGHJ"
BOXES     = {"A": range(1, 7), "B": range(7, 13), "C": range(13, 19), "D": range(19, 25), "E": range(25, 31)}
PACK_STEPS = {"fill": ("Výplň", "📄"), "tape": ("Zalepiť", "🧻"), "label": ("Štítok", "🏷")}
PACK_ORDER = list(PACK_STEPS)
JOB_ALIASES = {
    "pick": "pick", "picking": "pick", "пикинг": "pick", "pikovanie": "pick",
    "pack": "pack", "packing": "pack", "balenie": "pack", "баление": "pack", "упаковка": "pack",
}
# (приемер меньше чем, оплата от, оплата до) — вилка оплаты за собранный заказ
PRIEMER_TIERS = [(60, 50, 10_000), (80, 10_000, 20_000), (120, 20_000, 50_000), (None, 50_000, 100_000)]
SCANNER_ERROR_CHANCE = 0.03


def pick_pay_range(pm: int):
    for limit, lo, hi in PRIEMER_TIERS:
        if limit is None or pm < limit:
            return lo, hi


def priemer_level(pm: int) -> str:
    return "🔴 Низкий" if pm < 60 else "🟡 Средний" if pm < 80 else "🟢 Высокий" if pm < 120 else "💎 Максимум"


def accuracy(mistakes: int) -> float:
    return 1.1 if mistakes == 0 else max(0.7, 1 - 0.05 * mistakes)


def fmt_time(secs: float) -> str:
    m, s = divmod(int(secs), 60)
    return f"{m:02d}:{s:02d}"


def random_item() -> str:
    brand = random.choice(list(SPORT_ITEMS_WITH_BRANDS))
    return f"{brand} — {random.choice(SPORT_ITEMS_WITH_BRANDS[brand])}"


def aisle_code(aisle) -> str:
    zone, num = aisle
    return f"3{zone}-{num:02d}"


def generate_route(size: int) -> list:
    """Позиции заказа, сгруппированные по уличкам (1–5 на уличку) в порядке обхода склада."""
    stops, used, left = [], set(), size
    while left > 0:
        k = min(left, random.randint(1, 5))
        aisle = (random.choice(ZONES), random.randint(1, 56))
        if aisle in used:
            continue
        used.add(aisle)
        items = [{"shelf": f"{random.choice(SHELVES)}{random.randint(1, 4)}", "item": random_item()}
                 for _ in range(k)]
        stops.append({"aisle": aisle, "items": items})
        left -= k
    stops.sort(key=lambda s: s["aisle"])
    return stops


def decoys(aisle) -> list:
    """Две похожие, но неправильные улички: соседний номер или та же уличка в другой зоне."""
    zone, num = aisle
    out = set()
    while len(out) < 2:
        if random.random() < 0.5:
            cand = (zone, min(56, max(1, num + random.choice((-3, -2, -1, 1, 2, 3)))))
        else:
            cand = ("C" if zone == "B" else "B", num)
        if cand != aisle:
            out.add(cand)
    return list(out)


# ── Базовая смена на складе ───────────────────────────────────
class WarehouseView(OwnedView):
    TITLE = "📦 GymBeam"
    deny_text = "Это не твоя смена на складе!"

    def __init__(self, user):
        super().__init__(user, timeout=300)
        self.orders_done  = 0
        self.shift_earned = 0
        self.done         = False
        self.new_order()

    # ── реализуют пикинг и упаковка ──
    def build_order(self): ...
    def render_order(self) -> discord.Embed: ...
    def summary_extra(self, e: discord.Embed): ...

    def new_order(self):
        self.no       = f"GB-{random.randint(100000, 999999)}"
        self.size     = random.randint(1, 30)
        self.mistakes = 0
        self.t0       = time.monotonic()
        self.note     = ""
        self.summary  = None

    def note_line(self) -> str:
        note, self.note = self.note, ""
        return f"{note}\n\n" if note else ""

    def mistake(self, note: str):
        self.mistakes += 1
        self.note = note

    def status_line(self) -> str:
        return f"⏱ {fmt_time(time.monotonic() - self.t0)} • ❌ chyby: {self.mistakes}"

    def embed(self, desc: str, color=GB_ORANGE) -> discord.Embed:
        e = discord.Embed(title=self.TITLE, description=desc, color=color)
        e.set_footer(text=f"{self.user.display_name} • objednávok za smenu: {self.orders_done} • "
                          f"zarobené: {self.shift_earned:,} 💰")
        return e

    def render(self) -> discord.Embed:
        return self.render_summary() if self.summary else self.render_order()

    def prepare(self):
        self.clear_items()
        if self.summary:
            self.btn("Nová objednávka", self._next, GREEN, emoji="📦")
            self.btn("Koniec smeny", self._quit, RED, emoji="🚪")
        else:
            self.build_order()
            self.btn("Koniec smeny", self._quit, RED, emoji="🚪", row=4)

    async def show(self, interaction=None):
        self.prepare()
        await self.push(interaction, content=None, embed=self.render(), view=self)

    def pay(self, base: int, label: str):
        """Оплата заказа: точность, кирка (+20%) и налог на зарплату."""
        acc     = accuracy(self.mistakes)
        gross   = int(base * acc)
        pickaxe = player_inventory.get(self.uid, {}).get("pickaxe", 0) > 0
        if pickaxe:
            gross = int(gross * 1.2)
        tax = work_tax(gross)
        net = gross - tax
        player_funds[self.uid] = player_funds.get(self.uid, 0) + net
        save_funds()
        self.orders_done  += 1
        self.shift_earned += net
        self.summary = {"label": label, "acc": acc, "pickaxe": pickaxe, "gross": gross, "tax": tax,
                        "net": net, "time": time.monotonic() - self.t0}

    def render_summary(self) -> discord.Embed:
        s = self.summary
        acc = "🎯 без ошибок: +10%" if self.mistakes == 0 else f"❌ {self.mistakes} → ×{s['acc']:.2f}"
        e = self.embed(f"{self.note_line()}🚚 **Objednávka #{self.no} odoslaná!**\n{s['label']}",
                       color=discord.Color.green())
        e.add_field(name="Kusov", value=str(self.size))
        e.add_field(name="Čas", value=fmt_time(s["time"]))
        e.add_field(name="Presnosť", value=acc)
        e.add_field(name="Výplata", inline=False,
                    value=f"Начислено: **{s['gross']:,}** | Налог: **{s['tax']:,}** | На руки: **{s['net']:,}** 💰")
        if s["pickaxe"]:
            e.add_field(name="Bonus", value="⛏ Кирка: +20%", inline=False)
        self.summary_extra(e)
        return e

    async def _next(self, interaction: Interaction):
        self.new_order()
        await self.show(interaction)

    def release(self):
        if ORDERS.get(self.uid) is self:
            del ORDERS[self.uid]

    def shift_report(self) -> str:
        text = f"Objednávok: **{self.orders_done}**, zarobené: **{self.shift_earned:,}** 💰."
        if self.summary is None:
            text += " Nedokončená objednávka sa neplatí."
        return text

    async def _quit(self, interaction: Interaction):
        self.done = True
        self.release()
        self.stop()
        await interaction.response.edit_message(
            content=f"🚪 {self.user.mention}, smena skončila. {self.shift_report()}", embed=None, view=None)

    async def on_timeout(self):
        if self.done:
            return
        self.done = True
        self.release()
        if self.message is not None:
            try:
                await self.message.edit(content=f"⌛ {self.user.mention}, smena ukončená pre nečinnosť. "
                                                f"{self.shift_report()}", embed=None, view=None)
            except discord.HTTPException:
                pass


# ── 📟 Пикинг ─────────────────────────────────────────────────
class PickingView(WarehouseView):
    TITLE = "📦 GymBeam • Pikovanie"

    def new_order(self):
        super().new_order()
        self.stops   = generate_route(self.size)
        self.stop_i  = 0
        self.picked  = 0
        self.phase   = "pick"         # pick → (error) → ready
        self.token   = None
        self.task    = None
        self.options = self._options()
        if self.uid not in priemer_data:
            priemer_data[self.uid] = 0
            save_priemer()

    def _options(self) -> list:
        aisle = self.stops[self.stop_i]["aisle"]
        opts = [aisle] + decoys(aisle)
        random.shuffle(opts)
        return opts

    def build_order(self):
        if self.phase == "pick":
            for a in self.options:
                self.btn(f"Skenovať {aisle_code(a)}", self._scan(a), BLUE, emoji="📟")
        elif self.phase == "error":
            self.btn("Čakáme na support…", self._wait, GREY, emoji="📵", disabled=True)
        else:
            self.btn("Odoslať objednávku", self._send, GREEN, emoji="🚚")

    def render_order(self) -> discord.Embed:
        pm = priemer_data.get(self.uid, 0)
        head = (f"📟 **Skener** • objednávka **#{self.no}** • {self.size} ks\n"
                f"{progress_bar(self.picked, self.size)} **{self.picked}/{self.size}**\n"
                f"{self.status_line()} • 📈 Priemer: {pm}\n\n")
        if self.phase == "ready":
            body = "✅ **Všetko vychystané!** Вези тележку на упаковку и отправляй заказ."
        else:
            stop  = self.stops[self.stop_i]
            items = "\n".join(f"• `{it['shelf']}` — {it['item']}" for it in stop["items"])
            ahead = [aisle_code(s["aisle"]) for s in self.stops[self.stop_i + 1:self.stop_i + 4]]
            route = ("🗺 Ďalej: " + " → ".join(ahead) + (" → …" if len(self.stops) > self.stop_i + 4 else "")
                     if ahead else "🏁 Posledná ulička!")
            hint  = ("📵 Skener zamrzol — čakáme na support." if self.phase == "error"
                     else "Отсканируй штрихкод нужной улички.")
            body  = (f"📍 **Choď do uličky {aisle_code(stop['aisle'])}** "
                     f"({self.stop_i + 1}/{len(self.stops)})\n{items}\n\n{route}\n{hint}")
        return self.embed(self.note_line() + head + body)

    async def _wait(self, interaction: Interaction):
        await interaction.response.defer()

    def _scan(self, aisle):
        async def cb(interaction: Interaction):
            if self.phase != "pick":
                await interaction.response.defer()
                return
            stop = self.stops[self.stop_i]
            if aisle != stop["aisle"]:
                self.mistake(f"❌ **Nesprávna lokácia!** Это {aisle_code(aisle)}, а товар лежит "
                             f"в {aisle_code(stop['aisle'])}.")
                self.options = self._options()
            elif random.random() < SCANNER_ERROR_CHANCE:
                self.phase = "error"
                self.token = token = object()
                self.note  = "📵 **Chyba skenera!** Skener zamrzol, čakáme na support…"
                self.task  = asyncio.create_task(self._scanner_error(token))
            else:
                self.picked += len(stop["items"])
                self.stop_i += 1
                self.note = f"✅ Naskenované: {len(stop['items'])} ks z {aisle_code(stop['aisle'])}"
                if self.stop_i >= len(self.stops):
                    self.phase = "ready"
                else:
                    self.options = self._options()
            await self.show(interaction)
        return cb

    async def _scanner_error(self, token):
        """Как в жизни: сканер зависает, и приходится ждать support (20–60 секунд)."""
        left = random.randint(20, 60)
        while left > 0:
            await asyncio.sleep(min(10, left))
            left -= 10
            if self.done or self.token is not token:
                return
            self.note = (f"📵 **Chyba skenera** — čakáme na support, ešte ~{left} s." if left > 0
                         else "🛠 Support pomohol, skener funguje. Pokračuj!")
            if left <= 0:
                self.phase = "pick"
                self.options = self._options()
            try:
                await self.show()
            except discord.HTTPException:
                pass

    async def _send(self, interaction: Interaction):
        if self.phase != "ready":
            await interaction.response.defer()
            return
        pm = priemer_data.get(self.uid, 0)
        lo, hi = pick_pay_range(pm)
        self.pay(random.randint(lo, hi), f"Priemer **{pm}** → вилка оплаты {lo:,}–{hi:,} 💰")
        order_history.setdefault(self.uid, []).append(self.size)
        await self.show(interaction)

    def summary_extra(self, e: discord.Embed):
        pm = priemer_data.get(self.uid, 0)
        e.add_field(name="📈 Priemer", inline=False,
                    value=f"{pm}/150 {progress_bar(pm, 150)} {priemer_level(pm)}\n"
                          f"Растёт от собранных позиций — обновляется раз в минуту.")


# ── 📦 Упаковка ───────────────────────────────────────────────
class PackingView(WarehouseView):
    TITLE = "📦 GymBeam • Balenie"

    def new_order(self):
        super().new_order()
        self.items  = Counter(random_item() for _ in range(self.size))
        self.box    = None
        self.packed = 0
        self.steps  = []
        self.phase  = "box"           # box → pack

    def build_order(self):
        if self.phase == "box":
            for letter in BOXES:
                self.btn(f"Krabica {letter}", self._box(letter), BLUE, emoji="📦")
            return
        self.btn("Vložiť produkty", self._insert, BLUE, emoji="📥", disabled=self.packed >= self.size)
        for key, (name, emoji) in PACK_STEPS.items():
            done = key in self.steps
            self.btn(name, self._step(key), GREEN if done else GREY, emoji=emoji, disabled=done)
        self.btn("Odoslať", self._send, GREEN, emoji="✅", row=1)

    def render_order(self) -> discord.Embed:
        lines = [f"• {item}" + (f" ×{n}" if n > 1 else "") for item, n in self.items.most_common()]
        if len(lines) > 10:
            lines = lines[:10] + [f"…a ďalšie {len(lines) - 10} druhy"]
        head = (f"🧾 **Objednávka #{self.no}** • **{self.size} ks**\n" + "\n".join(lines) +
                f"\n\n{self.status_line()}\n")
        if self.phase == "box":
            legend = " · ".join(f"**{k}** {r.start}–{r.stop - 1}" for k, r in BOXES.items())
            body = f"📐 Krabice: {legend}\nВыбери коробку под количество товара."
        else:
            mark = lambda ok: "✅" if ok else "⬜"
            steps = " · ".join(f"{mark(k in self.steps)} {name}" for k, (name, _) in PACK_STEPS.items())
            body = (f"📦 Krabica **{self.box}** • {progress_bar(self.packed, self.size)} "
                    f"**{self.packed}/{self.size}**\n"
                    f"{mark(self.packed >= self.size)} Produkty · {steps}\n\n"
                    f"Порядок: produkty → výplň → zalepiť → štítok → odoslať.")
        return self.embed(self.note_line() + head + body)

    def _box(self, letter: str):
        async def cb(interaction: Interaction):
            fits = BOXES[letter]
            if self.size in fits:
                self.box, self.phase = letter, "pack"
                self.note = f"✅ Krabica **{letter}** sedí na {self.size} ks."
            else:
                size = "malá" if self.size >= fits.stop else "veľká"
                self.mistake(f"❌ Krabica **{letter}** je príliš {size} na {self.size} ks.")
            await self.show(interaction)
        return cb

    async def _insert(self, interaction: Interaction):
        k = random.randint(1, min(5, self.size - self.packed))
        self.packed += k
        self.note = f"📥 Vložené +{k} ks." + (" Všetko v krabici!" if self.packed >= self.size else "")
        await self.show(interaction)

    def _step(self, key: str):
        async def cb(interaction: Interaction):
            name = PACK_STEPS[key][0]
            if self.packed < self.size:
                self.mistake(f"❌ Najprv vlož všetky produkty — {name} až potom!")
            else:
                expected = PACK_ORDER[len(self.steps)]
                if key != expected:
                    self.mistake(f"❌ Teraz ide **{PACK_STEPS[expected][0]}**, nie {name}.")
                else:
                    self.steps.append(key)
                    self.note = f"{PACK_STEPS[key][1]} {name} — hotovo."
            await self.show(interaction)
        return cb

    async def _send(self, interaction: Interaction):
        if self.packed < self.size or len(self.steps) < len(PACK_ORDER):
            self.mistake("❌ Balík ešte nie je hotový — kuriér ho nezoberie!")
        else:
            self.pay(random.randint(50, 10_000), f"📦 Krabica **{self.box}** zabalená a odovzdaná kuriérovi.")
        await self.show(interaction)


# ── Cog ───────────────────────────────────────────────────────
class WorkCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.decay_counter = 0
        self.update_priemer.start()

    def cog_unload(self):
        self.update_priemer.cancel()

    @commands.command(
        name="gb", brief="Смена на складе GymBeam",
        help="`!gb` — смена на складе GymBeam (работа выбирается случайно), `!gb pick` — пикинг, "
             "`!gb pack` — упаковка.\n\n"
             "📟 **Пикинг:** сканер ведёт по уличкам — жми кнопку с правильной уличкой, собери все позиции "
             "и отправь заказ. Оплата зависит от Приемера (`!priemer`): <60 — 50–10 000, <80 — 10–20 тыс., "
             "<120 — 20–50 тыс., выше — 50–100 тыс. Иногда сканер зависает — подожди support.\n"
             "📦 **Упаковка:** выбери коробку (A 1–6, B 7–12, C 13–18, D 19–24, E 25–30), вложи товар, "
             "затем výplň → zalepiť → štítok → odoslať.\n\n"
             "Без ошибок +10%, каждая ошибка −5%. ⛏ Кирка +20%. Налог 7% (до 47 000) или 19%.")
    async def start_job(self, ctx, job: str = None):
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)
        if uid in ORDERS:
            await ctx.send(f"{ctx.author.mention}, у тебя уже идёт смена на складе — "
                           f"закончи её кнопкой «Koniec smeny».", delete_after=8)
            return
        key = JOB_ALIASES.get(job.lower().strip()) if job else random.choice(["pick", "pack"])
        if key is None:
            await ctx.send("❌ Работа: `!gb pick` (пикинг) или `!gb pack` (упаковка).", delete_after=8)
            return
        view = (PickingView if key == "pick" else PackingView)(ctx.author)
        ORDERS[uid] = view
        view.prepare()
        view.message = await ctx.send(embed=view.render(), view=view)

    @commands.command(name="priemer", brief="Показатель эффективности на складе")
    async def priemer_cmd(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        pm = priemer_data.get(str(member.id), 0)
        lo, hi = pick_pay_range(pm)
        e = discord.Embed(title=f"📈 Priemer — {member.display_name}", color=GB_ORANGE,
                          description=f"## {pm}/150\n{progress_bar(pm, 150, 20)}")
        e.add_field(name="Úroveň", value=priemer_level(pm))
        e.add_field(name="Výplata za pikovanie", value=f"{lo:,}–{hi:,} 💰")
        nxt = next((limit for limit, _, _ in PRIEMER_TIERS if limit is not None and pm < limit), None)
        e.add_field(name="Ďalšia úroveň", value=f"ещё {nxt - pm}" if nxt else "максимум 💎")
        e.set_footer(text="Растёт от собранных позиций пикинга, без работы медленно падает.")
        await ctx.send(embed=e)

    @tasks.loop(minutes=1)
    async def update_priemer(self):
        self.decay_counter += 1
        for uid in list(priemer_data.keys()):
            orders = order_history.get(uid, [])
            if orders:
                avg_o   = len(orders)
                avg_pos = sum(orders) / avg_o
                priemer_data[uid] = int(min(150, priemer_data[uid] + (avg_o * avg_pos) / 10))
            elif self.decay_counter >= 60:
                priemer_data[uid] = int(max(0, priemer_data[uid] - 1))
        if self.decay_counter >= 60:
            self.decay_counter = 0
        save_priemer()
        order_history.clear()

    @update_priemer.before_loop
    async def _wait_ready(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(60)   # первое обновление — через минуту после старта, как раньше


def setup(bot):
    bot.add_cog(WorkCog(bot))
