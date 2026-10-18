"""
mcdonalds.py — работа в McDonald's по реальному рабочему процессу ресторана.

Позиции повторяют станции настоящего ресторана:
  🧹 Зал → 🧾 Касса → 🍟 Фри → 🛍 Выдача → 🍔 Сборка (Made For You) → 🚗 МакАвто → 🔥 Гриль/UHC.
Новички начинают с зала, остальные станции открываются по мере обучения (отработанных смен).
Ошибки попадают в КЛН (контрольный лист наблюдения), от рейтинга смен зависит карьера:
Член бригады → Инструктор → Свинг-менеджер → Менеджер смены → Директор ресторана.
"""
import asyncio
import random
import time
import discord
from discord.ext import commands
from discord.ui import View, Button
from discord import Interaction
from data import player_funds, player_inventory, mcd_data, save_funds, save_mcd
from cogs.economy import init_player, work_tax

GREY  = discord.ButtonStyle.secondary
GREEN = discord.ButtonStyle.success
BLUE  = discord.ButtonStyle.primary
RED   = discord.ButtonStyle.danger

MCD_RED  = discord.Color.from_rgb(218, 41, 28)
MCD_GOLD = discord.Color.from_rgb(255, 199, 44)

MANAGERS = ["Оля", "Дима", "Марина", "Саша", "Катя", "Артём", "Лена", "Макс"]
THANKS   = ["«Спасибо!»", "«Супер, спасибо!»", "«Благодарю!»", "Гость доволен 😊"]

# ── Позиции ресторана ─────────────────────────────────────────
# unlock — сколько смен нужно отработать, чтобы пройти обучение на позицию
STATIONS: dict = {
    "lobby":    {"name": "Зал",         "emoji": "🧹", "unlock": 0,  "pay": 2500},
    "counter":  {"name": "Касса",       "emoji": "🧾", "unlock": 1,  "pay": 3500},
    "fries":    {"name": "Фри",         "emoji": "🍟", "unlock": 2,  "pay": 3500},
    "present":  {"name": "Выдача",      "emoji": "🛍", "unlock": 3,  "pay": 4000},
    "assembly": {"name": "Сборка",      "emoji": "🍔", "unlock": 5,  "pay": 5000},
    "drive":    {"name": "МакАвто",     "emoji": "🚗", "unlock": 7,  "pay": 5000},
    "grill":    {"name": "Гриль и UHC", "emoji": "🔥", "unlock": 10, "pay": 6000},
}
STATION_ALIASES: dict = {
    "зал": "lobby", "уборка": "lobby", "lobby": "lobby",
    "касса": "counter", "кассир": "counter", "counter": "counter",
    "фри": "fries", "картошка": "fries", "фритюр": "fries", "fries": "fries",
    "выдача": "present", "раннер": "present", "present": "present",
    "сборка": "assembly", "кухня": "assembly", "assembly": "assembly",
    "макавто": "drive", "мкавто": "drive", "авто": "drive", "drive": "drive",
    "гриль": "grill", "uhc": "grill", "grill": "grill",
}

# ── Карьерная лестница ────────────────────────────────────────
# (звание, смен, мин. средний рейтинг %, множитель зарплаты)
RANKS = [
    ("🧢 Член бригады",       0,   0, 1.0),
    ("🎓 Инструктор",         15, 70, 1.2),
    ("🔰 Свинг-менеджер",     35, 78, 1.3),
    ("👔 Менеджер смены",     60, 85, 1.5),
    ("🏆 Директор ресторана", 100, 90, 2.0),
]

# ── Меню (касса / МакАвто) ────────────────────────────────────
MENU: dict = {
    "bigmac": ("Биг Мак",        "🍔", 289),
    "cheese": ("Чизбургер",      "🧀", 99),
    "royal":  ("Роял Чизбургер", "👑", 249),
    "chick":  ("МакЧикен",       "🐔", 179),
    "fish":   ("Филе-О-Фиш",     "🐟", 199),
    "nugg":   ("Наггетсы",       "🍗", 159),
    "fries":  ("Картофель фри",  "🍟", 119),
    "cola":   ("Кока-Кола",      "🥤", 99),
    "coffee": ("Кофе",           "☕", 109),
    "pie":    ("Пирожок",        "🥧", 79),
}
GUEST_LINES = ["Мне, пожалуйста: {o}.", "Так… {o}. И всё!", "Здравствуйте! {o}.",
               "Можно {o}? Спасибо!", "Давайте {o}."]

# ── Зал ───────────────────────────────────────────────────────
LOBBY_TOOLS: dict = {
    "sign":   "⚠️ Знак «Мокрый пол»",
    "mop":    "🧹 Швабра (зал)",
    "mop_wc": "🪣 Швабра (туалет)",
    "cloth":  "🧽 Тряпка (столы)",
    "trays":  "🍱 Собрать подносы",
    "sanit":  "🧴 Дезинфектор",
    "bag":    "🗑 Новый мешок",
    "supply": "🧻 Расходники",
}
LOBBY_EVENTS = [
    ("🥤 Гость пролил колу у кассы",                ["sign", "mop"]),
    ("🧊 У автомата с напитками рассыпали лёд",     ["sign", "mop"]),
    ("🚻 В туалете лужа на полу",                   ["sign", "mop_wc"]),
    ("🚻 Плановый обход туалета (каждые 30 минут)", ["mop_wc", "supply"]),
    ("🍽 Столик №{n}: оставили подносы и крошки",   ["trays", "cloth"]),
    ("🍽 Столик №{n} липкий от соуса",              ["sanit", "cloth"]),
    ("👶 Детский стульчик в кетчупе",               ["sanit", "cloth"]),
    ("🗑 Мусорный бак у выхода переполнен",         ["bag"]),
    ("🙋 Гость просит салфетки и трубочку",         ["supply"]),
]

# ── Выдача ────────────────────────────────────────────────────
SHELF_ITEMS = ["Биг Мак", "Чизбургер", "Роял Чизбургер", "МакЧикен", "Филе-О-Фиш",
               "Наггетсы 6 шт", "Фри S", "Фри M", "Фри L", "Кока-Кола", "Кофе",
               "Пирожок", "МакФлурри"]

# ── Сборка (плакаты сборки) ───────────────────────────────────
INGR: dict = {
    "bun":     ("Булочка из тостера", "🍞"),
    "ketch":   ("Кетчуп",             "🥫"),
    "must":    ("Горчица",            "🟡"),
    "bmsauce": ("Соус Биг Мак",       "🟠"),
    "mayo":    ("Майонез",            "⚪"),
    "tartar":  ("Соус тартар",        "🥣"),
    "onion":   ("Лук",                "🧅"),
    "pickle":  ("Огурцы",             "🥒"),
    "lettuce": ("Салат",              "🥬"),
    "cheese":  ("Сыр",                "🧀"),
    "club":    ("Средняя булочка",    "🥯"),
    "p10":     ("Котлета 10:1",       "🥩"),
    "p4":      ("Котлета 4:1",        "🍖"),
    "chick":   ("Курица",             "🍗"),
    "fish":    ("Рыба",               "🐟"),
}
RECIPES: dict = {
    "Гамбургер":      ["bun", "ketch", "must", "onion", "pickle", "p10"],
    "Чизбургер":      ["bun", "ketch", "must", "onion", "pickle", "cheese", "p10"],
    "Роял Чизбургер": ["bun", "ketch", "must", "onion", "pickle", "cheese", "p4", "cheese"],
    "Биг Мак":        ["bun", "bmsauce", "onion", "lettuce", "cheese", "p10",
                       "club", "bmsauce", "onion", "lettuce", "pickle", "p10"],
    "МакЧикен":       ["bun", "mayo", "lettuce", "chick"],
    "Филе-О-Фиш":     ["bun", "tartar", "cheese", "fish"],
}
MODS: dict = {"onion": "БЕЗ ЛУКА", "pickle": "БЕЗ ОГУРЦОВ", "cheese": "БЕЗ СЫРА",
              "lettuce": "БЕЗ САЛАТА", "must": "БЕЗ ГОРЧИЦЫ"}

# ── Гриль / шкаф UHC ──────────────────────────────────────────
# (название, эмодзи, штук в партии, диапазон спроса за минуту)
UHC_ITEMS: dict = {
    "p10":   ("Котлета 10:1", "🥩", 4, (1, 5)),
    "p4":    ("Котлета 4:1",  "🍖", 2, (0, 2)),
    "chick": ("Курица",       "🍗", 2, (0, 2)),
    "nugg":  ("Наггетсы",     "🐔", 2, (0, 2)),
}
HOLD_TICKS  = 3   # сколько «минут» продукт может стоять в UHC
GRILL_SLOTS = 3   # сколько партий помещается на гриль за минуту

ACTIVE: dict = {}   # uid -> текущая смена (одна смена на игрока)


# ── Хелперы ───────────────────────────────────────────────────
def get_stats(uid: str) -> dict:
    st = mcd_data.setdefault(uid, {})
    for k in ("shifts", "rating_sum", "errors", "earned", "rank"):
        st.setdefault(k, 0)
    st.setdefault("stations", {})
    return st


def avg_rating(st: dict) -> int:
    return round(st["rating_sum"] / st["shifts"]) if st["shifts"] else 0


def unlocked(st: dict) -> list:
    return [k for k, s in STATIONS.items() if st["shifts"] >= s["unlock"]]


def rank_for(st: dict) -> int:
    idx = 0
    for i, (_, need, min_rating, _) in enumerate(RANKS):
        if st["shifts"] >= need and avg_rating(st) >= min_rating:
            idx = i
    return idx


def grade(rating: int) -> str:
    return ("💎 Отлично" if rating >= 90 else "🟢 Хорошо" if rating >= 75
            else "🟡 Нормально" if rating >= 50 else "🔴 Плохо")


def random_order(max_lines: int = 4) -> dict:
    keys = random.sample(list(MENU), random.randint(1, max_lines))
    return {k: random.choice([1, 1, 1, 2]) for k in keys}


def order_text(order: dict, emoji: bool = True) -> str:
    return ", ".join((f"{MENU[k][1]} " if emoji else "") + MENU[k][0] + (f" ×{q}" if q > 1 else "")
                     for k, q in order.items())


def order_total(order: dict) -> int:
    return sum(MENU[k][2] * q for k, q in order.items())


# ── Базовая смена ─────────────────────────────────────────────
class ShiftView(View):
    ROUNDS = 5
    BRIEF  = ""

    def __init__(self, user, station: str):
        super().__init__(timeout=180)
        self.user, self.uid, self.station = user, str(user.id), station
        self.manager = random.choice(MANAGERS)
        self.round   = 0
        self.scores: list = []
        self.errors  = 0
        self.bonus   = 0        # доплата сверх ставки (например, за допродажи)
        self.bonus_label = ""
        self.note    = ""       # обратная связь игроку, показывается один раз
        self.started = False
        self.done    = False
        self.btn("Начать смену", self._begin, GREEN, emoji="▶️")
        self.btn("Уйти домой", self._quit, RED, emoji="🚪")

    @property
    def info(self) -> dict:
        return STATIONS[self.station]

    # ── Методы, которые реализуют позиции ──
    def new_round(self): ...
    def build(self): ...
    def render(self) -> discord.Embed: ...

    # ── Общая механика ──
    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message("Это не твоя смена!", ephemeral=True)
            return False
        self.message = interaction.message
        return True

    def btn(self, label, cb, style=GREY, row=None, emoji=None, disabled=False):
        b = Button(label=label, style=style, row=row, emoji=emoji, disabled=disabled)
        b.callback = cb
        self.add_item(b)
        return b

    def exit_button(self, row: int):
        self.btn("Уйти", self._quit, RED, emoji="🚪", row=row)

    def embed(self, desc: str) -> discord.Embed:
        title = f"{self.info['emoji']} McDonald's — {self.info['name']}"
        if self.started and not self.done:
            title += f"  •  {self.round + 1}/{self.ROUNDS}"
        e = discord.Embed(title=title, description=desc, color=MCD_RED)
        e.set_footer(text=f"{self.user.display_name} • ошибок в КЛН: {self.errors}")
        return e

    def note_line(self) -> str:
        note, self.note = self.note, ""
        return f"{note}\n\n" if note else ""

    def mistake(self, note: str):
        self.errors += 1
        self.note = note

    def render_brief(self) -> discord.Embed:
        st = get_stats(self.uid)
        e = discord.Embed(
            title=f"{self.info['emoji']} McDonald's — {self.info['name']}",
            description=(f"🔰 Свинг-менеджер **{self.manager}**: «{self.user.display_name}, "
                         f"сегодня ты на позиции **{self.info['name']}**.»\n\n{self.BRIEF}"),
            color=MCD_GOLD,
        )
        e.set_footer(text=f"{RANKS[st['rank']][0]} • смена №{st['shifts'] + 1} • заданий: {self.ROUNDS}")
        return e

    async def push(self, interaction, **kw):
        if interaction is not None and not interaction.response.is_done():
            await interaction.response.edit_message(**kw)
        elif self.message is not None:
            await self.message.edit(**kw)

    async def show(self, interaction=None):
        self.clear_items()
        self.build()
        await self.push(interaction, content=None, embed=self.render(), view=self)

    async def end_round(self, interaction, quality: float, note: str = None):
        self.scores.append(max(0.0, min(1.0, quality)))
        if note is not None:
            self.note = note
        self.round += 1
        if self.round >= self.ROUNDS:
            await self.finish(interaction)
        else:
            self.new_round()
            await self.show(interaction)

    def release(self):
        if ACTIVE.get(self.uid) is self:
            del ACTIVE[self.uid]

    async def _begin(self, interaction: Interaction):
        self.started = True
        self.new_round()
        await self.show(interaction)

    async def _quit(self, interaction: Interaction):
        self.done = True
        self.release()
        self.stop()
        await interaction.response.edit_message(
            content=f"🚪 {self.user.mention}: смена прервана и не засчитана.", embed=None, view=None)

    async def on_timeout(self):
        if self.message is None:
            return
        try:
            if self.done:                    # итог смены остаётся, убираем только мёртвые кнопки
                await self.message.edit(view=None)
                return
            self.done = True
            self.release()
            await self.message.edit(
                content=f"⌛ {self.user.mention}, смена закрыта: долгое бездействие. "
                        f"Менеджер отправил тебя домой без оплаты.", embed=None, view=None)
        except discord.HTTPException:
            pass

    # ── Конец смены ──
    async def finish(self, interaction):
        self.done = True
        self.release()
        rating = round(100 * sum(self.scores) / len(self.scores))

        st = get_stats(self.uid)
        old_rank, old_open = st["rank"], unlocked(st)
        st["shifts"]     += 1
        st["rating_sum"] += rating
        st["errors"]     += self.errors
        st["stations"][self.station] = st["stations"].get(self.station, 0) + 1
        st["rank"] = max(st["rank"], rank_for(st))

        lines = []
        gross = int(self.info["pay"] * (0.3 + 0.7 * rating / 100)
                    * RANKS[old_rank][3] * random.uniform(0.9, 1.1))
        if RANKS[old_rank][3] > 1:
            lines.append(f"{RANKS[old_rank][0]}: ставка ×{RANKS[old_rank][3]}")
        if self.bonus:
            gross += self.bonus
            lines.append(f"{self.bonus_label}: +{self.bonus:,}")
        if self.errors == 0 and rating >= 80:
            kln = int(gross * 0.15)
            gross += kln
            lines.append(f"🏅 Премия за чистый КЛН: +{kln:,}")
        if player_inventory.get(self.uid, {}).get("pickaxe", 0) > 0:
            gross = int(gross * 1.2)
            lines.append("⛏ Кирка: +20%")

        tax = work_tax(gross)
        net = gross - tax
        player_funds[self.uid] = player_funds.get(self.uid, 0) + net
        st["earned"] += net
        save_funds()
        save_mcd()

        e = discord.Embed(title=f"🍟 Смена окончена — {self.info['emoji']} {self.info['name']}", color=MCD_GOLD)
        if self.note:
            e.description = self.note
        e.add_field(name="Рейтинг смены", value=f"**{rating}%** {grade(rating)}")
        e.add_field(name="Ошибок в КЛН", value=str(self.errors))
        e.add_field(name="Зарплата",
                    value=f"Начислено: **{gross:,}** | Налог: **{tax:,}** | Итого: **{net:,}** 💰", inline=False)
        if lines:
            e.add_field(name="Надбавки", value="\n".join(lines), inline=False)
        news = []
        if st["rank"] > old_rank:
            news.append(f"🎉 **Повышение!** Теперь ты — {RANKS[st['rank']][0]}")
        for k in unlocked(st):
            if k not in old_open:
                news.append(f"🔓 Обучение пройдено: открыта позиция {STATIONS[k]['emoji']} **{STATIONS[k]['name']}**")
        if news:
            e.add_field(name="Новости", value="\n".join(news), inline=False)
        e.set_footer(text=f"{self.user.display_name} • смен: {st['shifts']} • средний рейтинг: {avg_rating(st)}%")

        self.clear_items()
        self.btn("Ещё смена", self._again, GREEN, emoji="🔁")
        self.btn("Домой", self._home, GREY, emoji="🏠")
        await self.push(interaction, content=None, embed=e, view=self)

    async def _again(self, interaction: Interaction):
        if self.uid in ACTIVE:
            await interaction.response.send_message("У тебя уже идёт другая смена!", ephemeral=True)
            return
        self.stop()
        key  = random.choice(unlocked(get_stats(self.uid)))
        view = STATION_VIEWS[key](self.user, key)
        ACTIVE[self.uid] = view
        view.message = interaction.message
        await interaction.response.edit_message(content=None, embed=view.render_brief(), view=view)

    async def _home(self, interaction: Interaction):
        self.stop()
        await interaction.response.edit_message(view=None)


# ── 🧹 Зал ────────────────────────────────────────────────────
class LobbyView(ShiftView):
    ROUNDS = 5
    BRIEF  = ("Все новички начинают с зала. Убирай столы, следи за мусором и проверяй туалет по графику.\n"
              "• Для зала и туалета — **разный инвентарь**, путать нельзя.\n"
              "• Мокрый пол — **сначала знак**, потом швабра.\n"
              "• Две ошибки на одной задаче — менеджер доделает её за тебя.")

    def __init__(self, user, station="lobby"):
        super().__init__(user, station)
        self.queue = random.sample(LOBBY_EVENTS, self.ROUNDS)

    def new_round(self):
        text, self.need = self.queue[self.round]
        self.event = text.format(n=random.randint(1, 24))
        self.step  = 0
        self.slips = 0

    def build(self):
        for i, (key, label) in enumerate(LOBBY_TOOLS.items()):
            self.btn(label, self._tool(key), row=i // 4)
        self.exit_button(row=2)

    def render(self):
        done = " → ".join(LOBBY_TOOLS[k] for k in self.need[:self.step]) or "—"
        return self.embed(f"{self.note_line()}📋 **Задача:** {self.event}\n✔️ **Сделано:** {done}\n\n"
                          f"Выбери инвентарь.")

    def _tool(self, key):
        async def cb(interaction: Interaction):
            want = self.need[self.step]
            if key == want:
                self.step += 1
                if self.step == len(self.need):
                    await self.end_round(interaction, 1.0 - 0.4 * self.slips, f"✅ {self.event} — готово!")
                    return
                self.note = f"👍 {LOBBY_TOOLS[key]} — верно, дальше."
            else:
                self.slips += 1
                if {key, want} == {"mop", "mop_wc"}:
                    self.mistake("❌ Для зала и туалета — РАЗНЫЙ инвентарь! Ошибка в КЛН.")
                elif want == "sign":
                    self.mistake("❌ Сначала знак «Мокрый пол» — гость может поскользнуться! Ошибка в КЛН.")
                else:
                    self.mistake(f"❌ {LOBBY_TOOLS[key]} здесь не поможет. Ошибка в КЛН.")
                if self.slips >= 2:
                    await self.end_round(interaction, 0.0,
                                         f"{self.note}\n🔰 {self.manager} доделывает задачу за тебя.")
                    return
            await self.show(interaction)
        return cb


# ── 🧾 Касса / 🚗 МакАвто: общий пробой чека ──────────────────
class PunchView(ShiftView):
    def punch_buttons(self):
        for i, (key, (name, emoji, _)) in enumerate(MENU.items()):
            self.btn(name, self._add(key), emoji=emoji, row=i // 5)

    def new_order(self, max_lines: int):
        self.order  = random_order(max_lines)
        self.line   = random.choice(GUEST_LINES).format(o=order_text(self.order, emoji=False))
        self.ticket = {}
        self.t0     = time.monotonic()

    def ticket_text(self) -> str:
        return order_text(self.ticket) if self.ticket else "_пусто_"

    def _add(self, key):
        async def cb(interaction: Interaction):
            self.ticket[key] = self.ticket.get(key, 0) + 1
            await self.show(interaction)
        return cb

    async def _reset(self, interaction: Interaction):
        self.ticket = {}
        await self.show(interaction)


class CounterView(PunchView):
    ROUNDS = 5
    BRIEF  = ("Принимай заказы у стойки. Пробей **ровно то**, что сказал гость — лишнее или "
              "недостающее идёт в КЛН.\n"
              "• Предлагай пирожок к заказу (суггестивная продажа): согласился гость — "
              "не забудь добавить его в чек, за каждую допродажу доплата.\n"
              "• Быстро и без ошибок = высокий рейтинг.")

    def __init__(self, user, station="counter"):
        super().__init__(user, station)
        self.bonus_label = "💬 Допродажи"

    def new_round(self):
        self.new_order(4)
        self.upsold = False
        self.upsell_ok = False

    def build(self):
        self.punch_buttons()
        self.btn("Предложить пирожок", self._upsell, BLUE, emoji="💬", row=2,
                 disabled=self.upsold or "pie" in self.order)
        self.btn("Сбросить", self._reset, GREY, emoji="↩️", row=2)
        self.btn("Пробить чек", self._punch, GREEN, emoji="✅", row=2)
        self.exit_button(row=2)

    def render(self):
        extra = "\n💬 + 🥧 Пирожок (согласился на допродажу)" if self.upsell_ok else ""
        return self.embed(f"{self.note_line()}🙋 Гость: «{self.line}»{extra}\n\n🧾 **Чек:** {self.ticket_text()}")

    async def _upsell(self, interaction: Interaction):
        self.upsold = True
        if random.random() < 0.5:
            self.upsell_ok = True
            self.order["pie"] = self.order.get("pie", 0) + 1
            self.note = "💬 «А пирожок к заказу?» — «Давайте!» 🥧 Добавь его в чек."
        else:
            self.note = "💬 «А пирожок к заказу?» — «Нет, спасибо.»"
        await self.show(interaction)

    async def _punch(self, interaction: Interaction):
        if not self.ticket:
            await interaction.response.send_message("Чек пустой!", ephemeral=True)
            return
        secs = time.monotonic() - self.t0
        if self.ticket == self.order:
            if self.upsell_ok:
                self.bonus += 300
            q = 1.0 if secs <= 20 else 0.85 if secs <= 35 else 0.7
            await self.end_round(interaction, q, f"✅ Чек верный ({secs:.0f} сек). {random.choice(THANKS)}")
        else:
            self.errors += 1
            await self.end_round(interaction, 0.0,
                                 f"❌ Ошибка в чеке! Гость заказывал: {order_text(self.order)}\n"
                                 f"В чеке: {self.ticket_text()}. Ошибка в КЛН.")


class DriveView(PunchView):
    ROUNDS = 4
    TARGET = 45
    BRIEF  = ("МакАвто: гость говорит в микрофон, ты пробиваешь заказ, затем машина подъезжает к окну "
              "оплаты.\n"
              "• Пробей заказ без ошибок.\n"
              "• Оплата: картой — терминал, наличными — посчитай сдачу.\n"
              f"• Цель — машина за **{TARGET} секунд**. В реальном McDonald's приём простого заказа "
              "занимает ~17 секунд!")

    def __init__(self, user, station="drive"):
        super().__init__(user, station)

    def new_round(self):
        self.new_order(3)
        self.phase = "order"
        self.cars  = random.randint(1, 5)

    def build(self):
        if self.phase == "order":
            self.punch_buttons()
            self.btn("Сбросить", self._reset, GREY, emoji="↩️", row=2)
            self.btn("Пробить → окно оплаты", self._to_pay, GREEN, emoji="✅", row=2)
            self.exit_button(row=2)
        else:
            for label, ok in self.pay_options:
                self.btn(label, self._pay(ok), BLUE, row=0)
            self.exit_button(row=1)

    def render(self):
        secs = time.monotonic() - self.t0
        if self.phase == "order":
            desc = (f"🎧 **Окно заказа.** Очередь: {'🚗' * self.cars}\n"
                    f"Гость в наушниках: «{self.line}»\n\n🧾 **Чек:** {self.ticket_text()}")
        else:
            desc = (f"💰 **Окно оплаты.** {self.pay_line}\n"
                    f"⏱ Машина обслуживается {secs:.0f} сек (цель ≤ {self.TARGET})")
        return self.embed(self.note_line() + desc)

    async def _to_pay(self, interaction: Interaction):
        if not self.ticket:
            await interaction.response.send_message("Чек пустой!", ephemeral=True)
            return
        self.order_ok = self.ticket == self.order
        if not self.order_ok:
            self.mistake(f"❌ Заказ пробит неверно! Гость хотел: {order_text(self.order)}. Ошибка в КЛН.")
        total = order_total(self.ticket)
        card  = random.random() < 0.3
        if card:
            change = None
            base   = random.randint(5, 60) * 10
            self.pay_line = f"К оплате **{total} 💰**. Гость протягивает карту 💳"
        else:
            given  = next(b for b in (100, 200, 500, 1000, 2000, 5000) if b > total)
            change = base = given - total
            self.pay_line = f"К оплате **{total} 💰**. Гость даёт купюру **{given} 💰**"
        fakes = set()
        while len(fakes) < (3 if card else 2):
            f = base + random.choice((-100, -50, -10, 10, 50, 100))
            if f >= 0 and f != change:
                fakes.add(f)
        opts = [(f"Сдача {v}", False) for v in fakes]
        if change is not None:
            opts.append((f"Сдача {change}", True))
        random.shuffle(opts)
        self.pay_options = [("💳 Терминал", card)] + opts
        self.phase = "pay"
        await self.show(interaction)

    def _pay(self, ok: bool):
        async def cb(interaction: Interaction):
            secs = time.monotonic() - self.t0
            fast = secs <= self.TARGET
            q = (0.6 if self.order_ok else 0) + (0.3 if ok else 0) + (0.1 if fast else 0)
            note = f"🚗 Машина обслужена за {secs:.0f} сек" + (" ⚡" if fast else f" (цель ≤ {self.TARGET})")
            if not self.order_ok:
                note += "\n❌ Заказ был пробит неверно."
            if not ok:
                self.errors += 1
                note += "\n❌ Ошибка с оплатой! Ошибка в КЛН."
            await self.end_round(interaction, q, note)
        return cb


# ── 🍟 Фри ────────────────────────────────────────────────────
class FryView(ShiftView):
    ROUNDS = 4
    SIZES  = {"S": "Маленькая", "M": "Средняя", "L": "Большая"}
    BRIEF  = ("Станция фри. Опусти корзину во фритюр и **жди сигнала таймера**:\n"
              "• подняли раньше — картошка сырая, позже — пережарена, совсем забыли — сгорит.\n"
              "• После подъёма — **сначала посолить**, потом разложить порции по экрану KVS.\n"
              "• В реальном ресторане готовый фри живёт всего 7 минут, потом его списывают.")

    def __init__(self, user, station="fries"):
        super().__init__(user, station)
        self.token = None
        self.timer = None

    def new_round(self):
        self.phase   = "drop"     # drop → frying → pack
        self.need    = {s: random.randint(0, 2) for s in self.SIZES}
        if not any(self.need.values()):
            self.need[random.choice(list(self.SIZES))] = 1
        self.packed  = {s: 0 for s in self.SIZES}
        self.salted  = False
        self.cook_q  = 0.0
        self.retries = 0
        self.beep_at = None

    def build(self):
        if self.phase == "drop":
            self.btn("Опустить корзину", self._drop, GREEN, emoji="🍟")
        elif self.phase == "frying":
            self.btn("Поднять корзину", self._lift, BLUE, emoji="⬆️")
        else:
            self.btn("Посолить", self._salt, BLUE, emoji="🧂", disabled=self.salted)
            for s, name in self.SIZES.items():
                self.btn(f"{name} ({s})", self._pack(s))
            self.btn("Высыпать обратно", self._unpack, GREY, emoji="↩️", row=1)
            self.btn("Отдать на выдачу", self._serve, GREEN, emoji="✅", row=1)
        self.exit_button(row=1)

    def render(self):
        need = " · ".join(f"{s}×{n}" for s, n in self.need.items() if n)
        desc = f"🖥 **KVS:** нужно порций 🍟 {need}\n\n"
        if self.phase == "drop":
            desc += "🛢 Фритюр разогрет. Опускай корзину."
        elif self.phase == "frying" and self.beep_at is None:
            desc += "🛢 Жарится… ⏳ жди сигнала таймера (не поднимай раньше!)"
        elif self.phase == "frying":
            desc += "🔔 **БИП-БИП-БИП!** Таймер! Поднимай корзину!"
        else:
            packed = " · ".join(f"{s}×{n}" for s, n in self.packed.items() if n) or "—"
            desc += f"🧂 Посолено: **{'да' if self.salted else 'нет'}**\n📦 Разложено: {packed}"
        return self.embed(self.note_line() + desc)

    async def _drop(self, interaction: Interaction):
        self.phase   = "frying"
        self.beep_at = None
        self.token   = token = object()
        await self.show(interaction)
        self.timer = asyncio.create_task(self._fry_timer(token))

    async def _fry_timer(self, token):
        await asyncio.sleep(random.uniform(3, 6))
        if self.token is not token or self.done:
            return
        self.beep_at = time.monotonic()
        try: await self.show()
        except Exception: pass
        await asyncio.sleep(12)
        if self.token is not token or self.done:
            return
        self.token = None
        self.retries += 1
        self.phase = "drop"
        self.mistake("🔥 Картошка сгорела — корзину так и не подняли! Списание, ошибка в КЛН. Жарь заново.")
        try: await self.show()
        except Exception: pass

    async def _lift(self, interaction: Interaction):
        if self.phase != "frying":
            await interaction.response.defer()
            return
        self.token = None
        if self.beep_at is None:
            self.retries += 1
            self.phase = "drop"
            self.mistake("❌ Подняли раньше сигнала — картошка сырая! Списание, ошибка в КЛН. Жарь заново.")
        else:
            late = time.monotonic() - self.beep_at
            if late <= 4:
                self.cook_q, self.note = 1.0, "✨ Идеально золотистая!"
            elif late <= 8:
                self.cook_q, self.note = 0.7, "🙂 Чуть передержали, но нормально."
            else:
                self.cook_q, self.note = 0.4, "😬 Пережарена, но отдать можно."
            self.phase = "pack"
        await self.show(interaction)

    async def _salt(self, interaction: Interaction):
        self.salted = True
        await self.show(interaction)

    def _pack(self, size: str):
        async def cb(interaction: Interaction):
            if not self.salted:
                self.mistake("❌ Сначала соль, потом раскладка — несолёную картошку не отдаём! Ошибка в КЛН.")
            else:
                self.packed[size] += 1
            await self.show(interaction)
        return cb

    async def _unpack(self, interaction: Interaction):
        self.packed = {s: 0 for s in self.SIZES}
        await self.show(interaction)

    async def _serve(self, interaction: Interaction):
        q = self.cook_q - 0.3 * self.retries
        if self.packed == self.need:
            await self.end_round(interaction, q, "✅ Порции ушли на выдачу.")
        else:
            self.errors += 1
            await self.end_round(interaction, q * 0.4, "❌ Порции не совпали с экраном KVS! Ошибка в КЛН.")


# ── 🛍 Выдача ─────────────────────────────────────────────────
class PresentView(ShiftView):
    ROUNDS = 5
    BRIEF  = ("Ты на выдаче (презентер). Собери заказ по номеру с полки готовой продукции:\n"
              "• бери **только** позиции этого заказа — на полке лежат и чужие;\n"
              "• **«В зале»** — на подносе, **«С собой»** — в пакет.\n"
              "• Цель — 15 секунд на заказ.")

    def __init__(self, user, station="present"):
        super().__init__(user, station)

    def new_round(self):
        self.num     = random.randint(100, 999)
        self.need    = set(random.sample(SHELF_ITEMS, random.randint(2, 4)))
        others       = [i for i in SHELF_ITEMS if i not in self.need]
        self.shelf   = list(self.need) + random.sample(others, 10 - len(self.need))
        random.shuffle(self.shelf)
        self.picked  = set()
        self.dine_in = random.random() < 0.5
        self.t0      = time.monotonic()

    def build(self):
        for i, item in enumerate(self.shelf):
            self.btn(item, self._toggle(item), GREEN if item in self.picked else GREY, row=i // 5)
        self.btn("На подносе", self._give(True), BLUE, emoji="🍽", row=2)
        self.btn("В пакет", self._give(False), BLUE, emoji="🛍", row=2)
        self.exit_button(row=2)

    def render(self):
        where  = "🍽 **В ЗАЛЕ**" if self.dine_in else "🛍 **С СОБОЙ**"
        items  = "\n".join(f"• {i}" for i in sorted(self.need))
        picked = ", ".join(sorted(self.picked)) or "—"
        return self.embed(f"{self.note_line()}🖥 **Экран выдачи:** заказ **#{self.num}** — {where}\n{items}\n\n"
                          f"🧺 Собрано: {picked}\n\nНажимай на позиции на полке (зелёные — уже взяты).")

    def _toggle(self, item: str):
        async def cb(interaction: Interaction):
            self.picked ^= {item}
            await self.show(interaction)
        return cb

    def _give(self, tray: bool):
        async def cb(interaction: Interaction):
            secs = time.monotonic() - self.t0
            if self.picked != self.need:
                self.errors += 1
                missing = ", ".join(sorted(self.need - self.picked)) or "—"
                extra   = ", ".join(sorted(self.picked - self.need)) or "—"
                await self.end_round(interaction, 0.0,
                                     f"❌ Заказ #{self.num} собран неверно! Не хватало: {missing}. "
                                     f"Лишнее: {extra}. Ошибка в КЛН.")
            elif tray != self.dine_in:
                self.errors += 1
                await self.end_round(interaction, 0.5,
                                     "❌ Гость брал с собой, а получил поднос! Ошибка в КЛН." if not self.dine_in
                                     else "❌ Гость ест в зале, а ему выдали пакет. Ошибка в КЛН.")
            else:
                q = 1.0 if secs <= 15 else 0.8
                await self.end_round(interaction, q,
                                     f"✅ Заказ #{self.num} выдан за {secs:.0f} сек. «Приятного аппетита!»")
        return cb


# ── 🍔 Сборка (Made For You) ──────────────────────────────────
class AssemblyView(ShiftView):
    ROUNDS = 5
    BRIEF  = ("Система **Made For You**: бутерброд собирается только после заказа гостя.\n"
              "• Собирай строго по плакату сборки: булочка из тостера → соусы → овощи → сыр → "
              "мясо из шкафа UHC → завернуть.\n"
              "• Читай экран KVS: особые заказы вроде **«БЕЗ ЛУКА»** — не клади этот ингредиент!\n"
              "• Ошибся — бутерброд в брак, собирай заново. Цель — 20 секунд на бутерброд.")

    def __init__(self, user, station="assembly"):
        super().__init__(user, station)

    def new_round(self):
        self.item = random.choice(list(RECIPES))
        seq = RECIPES[self.item]
        self.mod = None
        mods = [k for k in MODS if k in seq]
        if mods and random.random() < 0.35:
            self.mod = random.choice(mods)
        self.seq   = [k for k in seq if k != self.mod]
        self.step  = 0
        self.slips = 0
        self.t0    = time.monotonic()

    def build(self):
        for i, (key, (name, emoji)) in enumerate(INGR.items()):
            self.btn(name, self._ingr(key), emoji=emoji, row=i // 5)
        self.btn("Выбросить и заново", self._restart, GREY, emoji="↩️", row=3)
        self.btn("Завернуть", self._wrap, GREEN, emoji="📦", row=3)
        self.exit_button(row=3)

    def render(self):
        card  = " → ".join(f"{INGR[k][1]} {INGR[k][0]}" for k in RECIPES[self.item])
        built = " → ".join(INGR[k][1] for k in self.seq[:self.step]) or "—"
        mod   = f"\n⚠️ **ОСОБЫЙ ЗАКАЗ: {MODS[self.mod]}**" if self.mod else ""
        return self.embed(f"{self.note_line()}🖥 **KVS:** {self.item}{mod}\n\n"
                          f"📋 Плакат сборки: {card}\n\n🍔 На обёртке: {built}")

    async def _fail(self, interaction: Interaction, note: str):
        self.slips += 1
        self.step = 0
        self.mistake(note)
        if self.slips >= 3:
            await self.end_round(interaction, 0.0,
                                 f"{self.note}\n🔰 {self.manager} собирает {self.item} за тебя.")
        else:
            await self.show(interaction)

    def _ingr(self, key: str):
        async def cb(interaction: Interaction):
            if self.step < len(self.seq) and key == self.seq[self.step]:
                self.step += 1
                await self.show(interaction)
                return
            why = "по особому заказу его быть не должно" if key == self.mod else "не по плакату сборки"
            await self._fail(interaction, f"❌ {INGR[key][0]} — {why}! Бутерброд в брак, собирай заново. "
                                          f"Ошибка в КЛН.")
        return cb

    async def _restart(self, interaction: Interaction):
        self.step = 0
        self.note = "↩️ Начинаем заново (время идёт!)"
        await self.show(interaction)

    async def _wrap(self, interaction: Interaction):
        if self.step < len(self.seq):
            await self._fail(interaction, "❌ Бутерброд недособран — заворачивать нельзя! Брак. Ошибка в КЛН.")
            return
        secs = time.monotonic() - self.t0
        q = (1.0 if secs <= 20 else 0.85 if secs <= 35 else 0.7) - 0.3 * self.slips
        note = f"📦 {self.item} собран за {secs:.0f} сек" + (" ⚡ в стандарте!" if secs <= 20 else "")
        await self.end_round(interaction, q, note)


# ── 🔥 Гриль и шкаф UHC ───────────────────────────────────────
class GrillView(ShiftView):
    ROUNDS = 6
    BRIEF  = ("Гриль и шкаф UHC: готовишь мясо **заранее под прогноз**, сборщики берут его из шкафа.\n"
              f"• За минуту на гриль помещается {GRILL_SLOTS} партии.\n"
              f"• Мясо в UHC живёт {HOLD_TICKS} минуты игры (в реальности ~20 мин). Шкаф отдаёт старое первым, "
              "поэтому **просрочку списывай сразу** — отдать её гостю = ошибка в КЛН.\n"
              "• Мало мяса — гости ждут, много — уйдёт в списание. Принцип McDonald's: **«меньше, но чаще»**.")

    def __init__(self, user, station="grill"):
        super().__init__(user, station)
        self.uhc = {k: [] for k in UHC_ITEMS}
        self.uhc["p10"] = [1, 1, 0, 0]   # запас к открытию

    def new_round(self):
        self.cook     = {k: 0 for k in UHC_ITEMS}
        self.forecast = {k: random.randint(*v[3]) for k, v in UHC_ITEMS.items()}
        self.wasted   = 0

    def expired(self) -> int:
        return sum(1 for ages in self.uhc.values() for a in ages if a >= HOLD_TICKS)

    def build(self):
        full = sum(self.cook.values()) >= GRILL_SLOTS
        for key, (name, emoji, batch, _) in UHC_ITEMS.items():
            self.btn(f"{name} (+{batch})", self._cook(key), emoji=emoji, disabled=full)
        self.btn("Списать просрочку", self._discard, RED if self.expired() else GREY, emoji="🗑",
                 row=1, disabled=not self.expired())
        self.btn("Снять с гриля", self._uncook, GREY, emoji="↩️", row=1)
        self.btn("Следующая минута", self._tick, GREEN, emoji="▶️", row=1)
        self.exit_button(row=1)

    def render(self):
        fc = " · ".join(f"{v[1]} {self.forecast[k]}" for k, v in UHC_ITEMS.items())
        rows = []
        for key, (name, emoji, _, _) in UHC_ITEMS.items():
            ages  = sorted(self.uhc[key], reverse=True)
            units = "".join("🔴" if a >= HOLD_TICKS else "🟡" if a == HOLD_TICKS - 1 else "🟢" for a in ages)
            rows.append(f"{emoji} {name}: **{len(ages)}** {units}")
        cooking = " · ".join(f"{UHC_ITEMS[k][1]}×{n}" for k, n in self.cook.items() if n) or "пусто"
        return self.embed(
            f"{self.note_line()}📈 **Прогноз KVS на эту минуту** (±1): {fc}\n\n"
            f"🗄 **Шкаф UHC** (🟢 свежее · 🟡 скоро истечёт · 🔴 просрочено):\n" + "\n".join(rows) +
            f"\n\n🔥 На гриле: {cooking} (мест {sum(self.cook.values())}/{GRILL_SLOTS})")

    def _cook(self, key: str):
        async def cb(interaction: Interaction):
            if sum(self.cook.values()) >= GRILL_SLOTS:
                await interaction.response.send_message("Гриль заполнен!", ephemeral=True)
                return
            self.cook[key] += 1
            await self.show(interaction)
        return cb

    async def _uncook(self, interaction: Interaction):
        self.cook = {k: 0 for k in UHC_ITEMS}
        await self.show(interaction)

    async def _discard(self, interaction: Interaction):
        n = self.expired()
        for key in self.uhc:
            self.uhc[key] = [a for a in self.uhc[key] if a < HOLD_TICKS]
        self.wasted += n
        self.note = f"🗑 Списано просрочки: {n} шт."
        await self.show(interaction)

    async def _tick(self, interaction: Interaction):
        demand = {k: max(0, f + random.choice((-1, 0, 0, 1))) for k, f in self.forecast.items()}
        for key, n in self.cook.items():
            self.uhc[key] += [0] * (n * UHC_ITEMS[key][2])
        served = short = bad = 0
        for key, d in demand.items():
            stock = sorted(self.uhc[key], reverse=True)       # FIFO: старое уходит первым
            take, rest = stock[:d], stock[d:]
            served += len(take)
            short  += d - len(take)
            bad    += sum(1 for a in take if a >= HOLD_TICKS)
            self.uhc[key] = [a + 1 for a in rest]
        total = sum(demand.values())
        q = (1.0 if total == 0 else (served - bad) / total) - 0.05 * self.wasted
        dem = " · ".join(f"{UHC_ITEMS[k][1]} {n}" for k, n in demand.items())
        note = f"⏱ Минута {self.round + 1}: спрос {dem} → выдано **{served}/{total}**"
        if short:
            note += f", гости ждали мясо: {short}"
        if bad:
            self.errors += 1
            note += f"\n❌ Гостям ушла просрочка: {bad} шт.! Ошибка в КЛН."
        await self.end_round(interaction, q, note)


STATION_VIEWS: dict = {
    "lobby":    LobbyView,
    "counter":  CounterView,
    "fries":    FryView,
    "present":  PresentView,
    "assembly": AssemblyView,
    "drive":    DriveView,
    "grill":    GrillView,
}


# ── Cog ───────────────────────────────────────────────────────
class McDonaldsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        name="mc", aliases=["mcd", "мак"], brief="Выйти на смену в McDonald's",
        help=("Смена в McDonald's. Без аргумента свинг-менеджер сам ставит тебя на позицию, "
              "можно выбрать: зал, касса, фри, выдача, сборка, макавто, гриль.\n"
              "Новые позиции открываются по мере отработанных смен. Подробнее: `!mchelp`"),
    )
    async def mc(self, ctx, *, position: str = None):
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)
        if uid in ACTIVE:
            await ctx.send(f"{ctx.author.mention}, у тебя уже идёт смена — закончи её или нажми «Уйти».",
                           delete_after=8)
            return
        st = get_stats(uid)
        opened = unlocked(st)
        if position:
            key = STATION_ALIASES.get(position.lower().strip())
            if key is None:
                await ctx.send("❌ Нет такой позиции. Доступные: зал, касса, фри, выдача, сборка, макавто, гриль",
                               delete_after=10)
                return
            if key not in opened:
                s = STATIONS[key]
                await ctx.send(f"🔒 {ctx.author.mention}, на позицию {s['emoji']} **{s['name']}** ставят после "
                               f"**{s['unlock']}** смен (у тебя {st['shifts']}).", delete_after=10)
                return
        else:
            key = random.choice(opened)
        view = STATION_VIEWS[key](ctx.author, key)
        ACTIVE[uid] = view
        view.message = await ctx.send(embed=view.render_brief(), view=view)

    @commands.command(name="mcstats", aliases=["mcprofile"], brief="Карьера в McDonald's")
    async def mcstats(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        uid = str(member.id)
        if uid not in mcd_data:
            await ctx.send(f"🍟 У **{member.display_name}** ещё нет ни одной смены в McDonald's. Начать: `!mc`",
                           delete_after=10)
            return
        st  = get_stats(uid)
        avg = avg_rating(st)
        e = discord.Embed(title=f"🍟 Карьера {member.display_name} в McDonald's", color=MCD_GOLD)
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Звание", value=RANKS[st["rank"]][0])
        e.add_field(name="Смен", value=str(st["shifts"]))
        e.add_field(name="Средний рейтинг", value=f"{avg}% {grade(avg)}")
        e.add_field(name="Ошибок в КЛН", value=str(st["errors"]))
        e.add_field(name="Заработано", value=f"{st['earned']:,} 💰")
        stations = []
        for key, s in STATIONS.items():
            if st["shifts"] >= s["unlock"]:
                stations.append(f"✅ {s['emoji']} {s['name']} — смен: {st['stations'].get(key, 0)}")
            else:
                stations.append(f"🔒 {s['emoji']} {s['name']} — после {s['unlock']} смен")
        e.add_field(name="Позиции", value="\n".join(stations), inline=False)
        if st["rank"] + 1 < len(RANKS):
            name, need, min_rating, mult = RANKS[st["rank"] + 1]
            e.add_field(name="Следующее звание",
                        value=f"{name} (ставка ×{mult}): смен {st['shifts']}/{need}, "
                              f"рейтинг {avg}/{min_rating}%", inline=False)
        await ctx.send(embed=e)

    @commands.command(name="mchelp", brief="Как устроена работа в McDonald's")
    async def mchelp(self, ctx):
        e = discord.Embed(title="🍔 Как устроен McDonald's", color=MCD_RED, description=(
            "**Путь заказа:** 🧾 касса / 🚗 МакАвто → заказ уходит на кухонные экраны **KVS** → "
            "🔥 гриль держит мясо в шкафах **UHC** → 🍔 сборка делает бутерброд только после заказа "
            "(система **Made For You**) → 🍟 фри → 🛍 выдача собирает поднос или пакет → гость.\n"
            "🧹 Зал всё это время держит ресторан чистым."))
        e.add_field(name="Позиции", inline=False, value="\n".join(
            f"{s['emoji']} **{s['name']}** — с {s['unlock']} смен, ставка ~{s['pay']:,} 💰"
            for s in STATIONS.values()))
        e.add_field(name="Карьера", inline=False, value="\n".join(
            f"{name} — {need}+ смен, рейтинг {min_rating}%+, ставка ×{mult}"
            for name, need, min_rating, mult in RANKS))
        e.add_field(name="КЛН", inline=False, value=(
            "Контрольный лист наблюдения: менеджер записывает каждую ошибку. "
            "Смена без ошибок с рейтингом 80%+ — **премия +15%**."))
        e.add_field(name="Команды", inline=False, value=(
            "`!mc [позиция]` — выйти на смену\n`!mcstats [@user]` — карьера\n`!mchelp` — эта справка"))
        await ctx.send(embed=e)


def setup(bot):
    bot.add_cog(McDonaldsCog(bot))
