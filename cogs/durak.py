"""
durak.py — «Дурак» в Discord: лобби с меню правил и ставкой, общий стол-сообщение и личная панель «Мои карты».

Правила и бот-игрок — в durak_engine.py, здесь только кнопки, ставки и порядок ходов:
• !дурак [опции] — открыть набор; опции словами: переводной, все, 24/36/52, бот, ставка 500, сразу;
• в наборе хозяин стола выбирает правила меню, остальные жмут «Вступить», «➕ Бот» — сыграть с ботом;
• на столе: «Мои карты» — ходы только разрешёнными картами (панель видна лишь тебе и обновляется сама);
• не ходишь AFK_SEC секунд — за тебя играет бот, пока не нажмёшь любую кнопку игры;
• ставка: каждый вносит одинаково, за ботов вносит банк; дурак теряет ставку, остальные делят банк.
"""
import asyncio
import re
import time
import discord
from discord.ext import commands
from discord.ui import View, Button, Select

import durak_engine as E
from durak_engine import Card, Durak, MoveError, Rules
from data import player_funds, save_funds
from cogs.economy import init_player, calculate_tax
from views import GREY, GREEN, BLUE, RED

DURAK_COLOR = discord.Color.from_rgb(46, 125, 50)
BOT_DELAY = 1.2          # пауза перед ходом бота, секунд — чтобы ходы было видно
AFK_SEC = 120            # столько ждём хода человека, потом за него играет бот
TICK = 5                 # как часто проверяем, не уснул ли кто, секунд
LOBBY_SEC = 600          # набор закрывается сам через 10 минут
PANEL_SEC = 14 * 60      # панель «Мои карты» можно обновлять 15 минут после нажатия — берём с запасом
STAKES = [0, 100, 500, 1000, 5000]
BOT_NAMES = ["Вася", "Гена", "Зина", "Люба", "Федя"]
MOVE_ICONS = {"attack": "⚔️", "defend": "🛡️", "transfer": "🔁"}

GAMES: dict = {}         # id канала → Lobby или Match (одна игра на канал)
SEATS: dict = {}         # id игрока → id канала (игрок — только в одной игре)

RULES_TEXT = (
    "**Цель** — избавиться от карт. Последний, у кого они остались, — **дурак**.\n"
    "**Ход:** атакующий кладёт карту, отбивающийся кроет её старшей той же масти или козырем. "
    "Подкидывать можно карты того же достоинства, что уже на столе: всего не больше 6 и не больше, "
    "чем карт у отбивающегося.\n"
    "**Бито** — всё покрыто и никто не подкидывает: следующим ходит отбившийся. **Беру** — карты со стола "
    "уходят отбивающемуся, и он пропускает ход. После кона все добирают до 6.\n"
    "**Переводной:** пока ничего не отбито, отбивающийся может положить карту того же достоинства — "
    "и отбиваться будет следующий.\n"
    "**Кто подкидывает:** «соседи» — атакующий и игрок после отбивающегося, «все» — любой.\n"
    "**Колода:** 24 (от девятки, до 4 игроков), 36 (от шестёрки), 52 (от двойки). Первым ходит тот, "
    "у кого младший козырь.\n"
    "**В Discord:** «🃏 Мои карты» — твоя рука и меню ходов (видишь только ты), «✋ Беру», «✅ Бито / Пас»."
)


# ── Опции словами ─────────────────────────────────────────────
NUMBER_WORDS = {"один": 1, "одним": 1, "одного": 1, "два": 2, "двух": 2, "двумя": 2, "три": 3,
                "трех": 3, "тремя": 3, "четыре": 4, "четырех": 4, "пять": 5, "пятью": 5}
FILLER = {"с", "со", "на", "в", "и", "по", "колода", "колодой", "карт", "карты", "игра", "сыграем", "давай",
          "ставка", "ставкой", "ставку", "дурак", "дурака", "durak", "x", "deck", "bet", "кто", "только",
          "подкидывают", "подкидывать", "против", "vs", "with", "без", "ставки"}
BOT_RE = re.compile(r"бот\w*|bots?")


def parse_money(token: str):
    t = token.lower().replace(",", ".")
    mult = 1
    if t[-1:] in ("k", "к"):
        mult, t = 1_000, t[:-1]
    elif t[-1:] in ("m", "м"):
        mult, t = 1_000_000, t[:-1]
    try:
        value = float(t)
    except ValueError:
        return None
    return int(value * mult) if value >= 0 else None


def small_number(token: str):
    if token in NUMBER_WORDS:
        return NUMBER_WORDS[token]
    return int(token) if token.isdigit() and 1 <= int(token) <= 5 else None


def parse_options(text: str) -> dict:
    """«переводной все 52 с двумя ботами 500 сразу» → правила, ставка, число ботов, старт."""
    out = {"rules": Rules(), "stake": 0, "bots": 0, "start": False, "unknown": []}
    tokens = [t for t in re.split(r"[\s,;]+", (text or "").lower().replace("ё", "е")) if t]
    for i, t in enumerate(tokens):
        prev = tokens[i - 1] if i else ""
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if t.startswith(("перевод", "transfer")):
            out["rules"].mode = "transfer"
        elif t.startswith(("подкидн", "throw", "классич", "обычн")):
            out["rules"].mode = "throw"
        elif t.startswith(("сосед", "neighbo")):
            out["rules"].throwers = "neighbors"
        elif t in ("все", "всем", "всех", "любой", "любые", "all"):
            out["rules"].throwers = "all"
        elif t in ("24", "36", "52"):
            out["rules"].deck = int(t)
        elif t.startswith(("укороч", "коротк", "маленьк", "short")):
            out["rules"].deck = 24
        elif t.startswith(("полн", "больш", "full")):
            out["rules"].deck = 52
        elif BOT_RE.fullmatch(t):
            n = small_number(prev) or (small_number(nxt) if not BOT_RE.fullmatch(nxt) else None)
            out["bots"] = max(out["bots"], n or 1)
        elif t in ("сразу", "старт", "start", "go", "быстро"):
            out["start"] = True
        elif t in ("бесплатно", "free") or (t == "ставки" and prev == "без"):
            out["stake"] = 0
        elif small_number(t) and (BOT_RE.fullmatch(nxt) or BOT_RE.fullmatch(prev)):
            continue                                       # «2 бота» — число ботов, а не ставка
        elif parse_money(t) is not None:
            out["stake"] = parse_money(t)
        elif t not in FILLER and t not in NUMBER_WORDS:
            out["unknown"].append(t)
    return out


# ── Отрисовка ─────────────────────────────────────────────────
def cards_text(cards) -> str:
    return " ".join(f"`{c.label}`" for c in cards) or "—"


def hand_text(game: Durak, hand: list) -> str:
    """Рука по мастям, козыри в конце."""
    by_suit = {}
    for c in hand:
        by_suit.setdefault(c.suit, []).append(c)
    lines = []
    for s in sorted(by_suit, key=lambda s: (s == game.trump, E.SUITS.index(s))):
        mark = "  ← козыри" if s == game.trump else ""
        lines.append(" ".join(f"`{c.label}`" for c in sorted(by_suit[s])) + mark)
    return "\n".join(lines) or "карт нет"


def move_label(game: Durak, uid: int, kind: str, card: Card) -> str:
    if kind == "defend":
        target = game.table[game.check_defend(uid, card)][0]
        return f"{MOVE_ICONS[kind]} {card.label} — побить {target.label}"
    if kind == "transfer":
        return f"{MOVE_ICONS[kind]} {card.label} — перевести"
    return f"{MOVE_ICONS[kind]} {card.label} — {'подкинуть' if game.table else 'сходить'}"


def money(n: int) -> str:
    return f"{n:,} 💰"


# ── Набор игроков ─────────────────────────────────────────────
class Lobby(View):
    def __init__(self, cog, channel, host, opts: dict):
        super().__init__(timeout=LOBBY_SEC)
        self.cog, self.channel, self.host = cog, channel, host
        self.rules: Rules = opts["rules"]
        self.stake: int = opts["stake"]
        self.humans: list = [host]
        self.bots: int = min(opts["bots"], E.MAX_PLAYERS[self.rules.deck] - 1, len(BOT_NAMES))
        self.message = None
        self.closed = False
        self.note = "Не понял: " + ", ".join(opts["unknown"][:5]) if opts.get("unknown") else ""
        self.build()

    @property
    def seats(self) -> int:
        return len(self.humans) + self.bots

    def embed(self) -> discord.Embed:
        e = discord.Embed(title="🃏 Дурак — набор игроков", color=DURAK_COLOR)
        e.description = (f"**Правила:** {self.rules.describe()}\n"
                         f"**Ставка:** {money(self.stake) if self.stake else 'без ставки'}\n\n"
                         "Жми **Вступить**. Хозяин стола настраивает правила в меню и жмёт **Старт**.")
        names = [f"👑 {self.host.display_name}"] + [f"🙂 {m.display_name}" for m in self.humans if m != self.host]
        names += [f"🤖 Бот {BOT_NAMES[i]}" for i in range(self.bots)]
        e.add_field(name=f"Игроки — {self.seats}/{E.MAX_PLAYERS[self.rules.deck]}", value="\n".join(names))
        e.set_footer(text=self.note or "Как играть: !дурак правила")
        return e

    def build(self):
        self.clear_items()
        variant = Select(placeholder="Вариант", row=0, options=[
            discord.SelectOption(label=f"{E.MODES[m].capitalize()}, {E.THROWERS[t]}", value=f"{m}:{t}",
                                 emoji="🔁" if m == "transfer" else "⚔️",
                                 default=(m, t) == (self.rules.mode, self.rules.throwers))
            for m in E.MODES for t in E.THROWERS])
        variant.callback = self._variant
        deck = Select(placeholder="Колода", row=1, options=[
            discord.SelectOption(label=f"{n} карт", value=str(n), default=n == self.rules.deck,
                                 description={24: "от девятки, до 4 игроков", 36: "от шестёрки — классика",
                                              52: "полная, от двойки"}[n])
            for n in E.DECKS])
        deck.callback = self._deck
        stake = Select(placeholder="Ставка", row=2, options=[
            discord.SelectOption(label=money(s) if s else "Без ставки", value=str(s), default=s == self.stake)
            for s in sorted(set(STAKES + [self.stake]))][:25])
        stake.callback = self._stake
        for item in (variant, deck, stake):
            self.add_item(item)
        self._btn("Вступить", self._join, GREEN, 3, "🙋")
        self._btn("Выйти", self._leave, GREY, 3, "🚪")
        self._btn("Бот", self._add_bot, BLUE, 3, "➕")
        self._btn("Бот", self._remove_bot, GREY, 3, "➖", disabled=not self.bots)
        self._btn("Старт", self._start, GREEN, 4, "▶️", disabled=self.seats < 2)
        self._btn("Отмена", self._cancel, RED, 4, "✖️")

    def _btn(self, label, cb, style, row, emoji, disabled=False):
        b = Button(label=label, style=style, row=row, emoji=emoji, disabled=disabled)
        b.callback = cb
        self.add_item(b)

    async def redraw(self, interaction=None):
        self.build()
        if interaction is not None and not interaction.response.is_done():
            await interaction.response.edit_message(embed=self.embed(), view=self)
        elif self.message is not None:
            await self.message.edit(embed=self.embed(), view=self)

    async def _host_only(self, interaction) -> bool:
        if interaction.user.id != self.host.id:
            await interaction.response.send_message(
                f"Настраивает и запускает игру хозяин стола — {self.host.display_name}.", ephemeral=True)
            return False
        return True

    async def _variant(self, interaction):
        if await self._host_only(interaction):
            self.rules.mode, self.rules.throwers = interaction.data["values"][0].split(":")
            await self.redraw(interaction)

    async def _deck(self, interaction):
        if not await self._host_only(interaction):
            return
        n = int(interaction.data["values"][0])
        if self.seats > E.MAX_PLAYERS[n]:
            await interaction.response.send_message(f"В колоде {n} играют до {E.MAX_PLAYERS[n]} человек, "
                                                    f"а за столом {self.seats}.", ephemeral=True)
            return
        self.rules.deck = n
        await self.redraw(interaction)

    async def _stake(self, interaction):
        if not await self._host_only(interaction):
            return
        self.stake = int(interaction.data["values"][0])
        poor = [m.display_name for m in self.humans if player_funds.get(str(m.id), 0) < self.stake]
        self.note = f"Не хватает на ставку: {', '.join(poor)}" if poor else ""
        await self.redraw(interaction)

    async def _join(self, interaction):
        err = await self.cog.open_lobby(self.channel, interaction.user, None, redraw=False)
        if err:
            await interaction.response.send_message(f"❌ {err.capitalize()}.", ephemeral=True)
            return
        await self.redraw(interaction)

    def add(self, user) -> str:
        """Посадить за стол. Возвращает текст ошибки или None."""
        if any(m.id == user.id for m in self.humans):
            return "ты уже за столом"
        if self.seats >= E.MAX_PLAYERS[self.rules.deck]:
            return "за столом нет мест"
        if player_funds.get(str(user.id), 0) < self.stake:
            return f"на ставку {money(self.stake)} не хватает денег"
        self.humans.append(user)
        SEATS[user.id] = self.channel.id
        return None

    async def _leave(self, interaction):
        user = interaction.user
        if not any(m.id == user.id for m in self.humans):
            await interaction.response.send_message("Ты и так не за столом.", ephemeral=True)
            return
        self.humans = [m for m in self.humans if m.id != user.id]
        SEATS.pop(user.id, None)
        if not self.humans:
            await self.close(interaction, "🚪 Все вышли — набор закрыт.")
            return
        if user.id == self.host.id:
            self.host = self.humans[0]
            self.note = f"Хозяин стола теперь {self.host.display_name}"
        await self.redraw(interaction)

    async def _add_bot(self, interaction):
        if not await self._host_only(interaction):
            return
        if self.seats >= E.MAX_PLAYERS[self.rules.deck] or self.bots >= len(BOT_NAMES):
            await interaction.response.send_message("Мест нет.", ephemeral=True)
            return
        self.bots += 1
        await self.redraw(interaction)

    async def _remove_bot(self, interaction):
        if await self._host_only(interaction):
            self.bots = max(0, self.bots - 1)
            await self.redraw(interaction)

    async def _cancel(self, interaction):
        if await self._host_only(interaction):
            await self.close(interaction, "✖️ Набор отменён.")

    async def _start(self, interaction):
        if await self._host_only(interaction):
            await self.start(interaction)

    async def start(self, interaction=None):
        """Списывает ставки и превращает сообщение набора в игровой стол."""
        poor = [m for m in self.humans if player_funds.get(str(m.id), 0) < self.stake]
        if poor:
            for m in poor:
                SEATS.pop(m.id, None)
            self.humans = [m for m in self.humans if m not in poor]
            if not self.humans:
                await self.close(interaction, "✖️ Ни у кого не хватает на ставку — набор закрыт.")
                return
            if self.host in poor:
                self.host = self.humans[0]
            self.note = "Не хватило на ставку: " + ", ".join(m.display_name for m in poor)
            await self.redraw(interaction)
            return
        if self.seats < 2:
            if interaction is not None:
                await interaction.response.send_message("Нужно хотя бы двое — позови кого-нибудь или добавь бота.",
                                                        ephemeral=True)
            return
        self.closed = True
        self.stop()
        for m in self.humans:
            player_funds[str(m.id)] = player_funds.get(str(m.id), 0) - self.stake
        if self.stake:
            save_funds()
        match = Match(self.cog, self.channel, self.humans, self.bots, self.rules, self.stake)
        GAMES[self.channel.id] = match
        match.message = self.message
        await match.show(interaction)
        match.task = asyncio.create_task(match.run())
        print(f"[DURAK] партия: {self.rules.describe()}, людей {len(self.humans)}, ботов {self.bots}, "
              f"ставка {self.stake}")

    async def close(self, interaction, text: str):
        self.closed = True
        self.stop()
        for m in self.humans:
            SEATS.pop(m.id, None)
        if GAMES.get(self.channel.id) is self:
            GAMES.pop(self.channel.id, None)
        e = discord.Embed(title="🃏 Дурак", description=text, color=discord.Color.light_grey())
        try:
            if interaction is not None and not interaction.response.is_done():
                await interaction.response.edit_message(embed=e, view=None)
            elif self.message is not None:
                await self.message.edit(embed=e, view=None)
        except discord.HTTPException:
            pass

    async def on_timeout(self):
        if not self.closed:
            await self.close(None, "⌛ Набор закрыт — никто не нажал «Старт».")


# ── Партия ────────────────────────────────────────────────────
class Match:
    def __init__(self, cog, channel, humans: list, bots: int, rules: Rules, stake: int):
        self.cog, self.channel, self.stake = cog, channel, stake
        self.members = {m.id: m for m in humans}
        seats = [(m.id, m.display_name, False) for m in humans]
        seats += [(-(i + 1), f"Бот {BOT_NAMES[i]}", True) for i in range(bots)]
        self.game = Durak(seats, rules)
        self.pot = stake * len(seats)
        self.message = None
        self.task = None
        self.lock = asyncio.Lock()
        self.changed = asyncio.Event()
        self.auto: set = set()           # люди, за которых сейчас играет бот (AFK)
        self.panels: dict = {}           # id игрока → [interaction, подпись, время]
        self.last_move = time.monotonic()
        self.view = TableView(self)
        self.done = False

    # — кто ходит —
    def is_auto(self, p) -> bool:
        return p.bot or p.id in self.auto

    def blocking(self) -> list:
        """Люди, чьего хода ждёт стол."""
        return [p for p in self.game.players if not self.is_auto(p) and self.game.bot_move(p.id) is not None]

    def next_auto(self):
        """Ход бота (или бота за AFK-игрока), если стол сейчас ждёт его. Отбивающийся — первым."""
        g = self.game
        for i in [g.defender] + [i for i in range(len(g.players)) if i != g.defender]:
            p = g.players[i]
            if self.is_auto(p):
                mv = g.bot_move(p.id)
                if mv:
                    return p, mv
        return None

    async def run(self):
        try:
            while not self.game.finished:
                if self.next_auto():
                    await asyncio.sleep(BOT_DELAY)
                    async with self.lock:
                        nxt = self.next_auto()     # пока ждали, мог сходить человек
                        if nxt and not self.game.finished:
                            self.game.play(nxt[0].id, nxt[1])
                    await self.refresh()
                    continue
                try:
                    await asyncio.wait_for(self.changed.wait(), timeout=TICK)
                except asyncio.TimeoutError:
                    pass
                self.changed.clear()
                if time.monotonic() - self.last_move > AFK_SEC:
                    sleepy = self.blocking()
                    self.auto.update(p.id for p in sleepy)
                    if sleepy:
                        names = ", ".join(p.name for p in sleepy)
                        await self.say(f"💤 {names} не ходит {AFK_SEC // 60} мин — пока за него играет бот. "
                                       "Вернуться — любая кнопка игры.")
                    self.last_move = time.monotonic()
            await self.finish()
        except asyncio.CancelledError:
            raise
        except Exception as exc:                       # игра не должна молча зависнуть со ставками
            print(f"[DURAK] ошибка партии: {type(exc).__name__}: {exc}")
            await self.abort("⚠️ Ошибка в игре — ставки возвращены.")

    async def say(self, text: str):
        try:
            await self.channel.send(text, delete_after=30)
        except discord.HTTPException:
            pass

    async def human_move(self, user_id: int, move: tuple):
        """Ход человека. MoveError уходит наверх — его покажут игроку."""
        async with self.lock:
            self.game.play(user_id, move)
            self.auto.discard(user_id)
            self.last_move = time.monotonic()
        self.changed.set()

    def wake(self, user_id: int):
        """Любая кнопка игры — человек вернулся, бот за него больше не играет."""
        if user_id in self.auto:
            self.auto.discard(user_id)
            self.last_move = time.monotonic()
            self.changed.set()

    # — отрисовка —
    def embed(self) -> discord.Embed:
        g = self.game
        e = discord.Embed(title=f"🃏 Дурак · {g.rules.describe()}", color=DURAK_COLOR)
        trump = f"`{g.trump_card.label}`" if g.deck else f"**{g.trump}**"
        lines = [f"Козырь {trump} · в колоде **{len(g.deck)}** · бито **{g.discard}**", ""]
        if g.table:
            lines.append("**Стол:** " + "   ".join(
                f"`{a.label}`→`{d.label}`" if d else f"`{a.label}`→❔" for a, d in g.table))
        else:
            lines.append("**Стол пуст**")
        lines += ["", f"➡️ {g.waiting_for()}"]
        e.description = "\n".join(lines)
        rows = []
        for i, p in enumerate(g.players):
            role = "🏁" if p.out else "⚔️" if i == g.attacker else "🛡️" if i == g.defender else "▫️"
            tag = "🤖 " if p.bot else "💤 " if p.id in self.auto else ""
            rows.append(f"{role} {tag}{p.name} — {'вышел' if p.out else f'{len(p.hand)} 🂠'}")
        e.add_field(name="Игроки", value="\n".join(rows))
        if self.stake:
            e.add_field(name="Ставка", value=f"{money(self.stake)} с игрока\nбанк {money(self.pot)}")
        if g.log:
            e.set_footer(text=" · ".join(g.log[-4:]))
        return e

    async def show(self, interaction=None):
        try:
            if interaction is not None and not interaction.response.is_done():
                await interaction.response.edit_message(embed=self.embed(), view=self.view)
                self.message = interaction.message
            elif self.message is not None:
                await self.message.edit(embed=self.embed(), view=self.view)
            else:
                self.message = await self.channel.send(embed=self.embed(), view=self.view)
        except discord.HTTPException as exc:
            print(f"[DURAK] стол не обновлён: {exc}")

    async def refresh(self, skip: int = None):
        if self.done:
            return
        await self.show()
        for uid in list(self.panels):
            if uid != skip:
                await self.update_panel(uid)

    async def update_panel(self, uid: int):
        """Открытая панель «Мои карты» обновляется сама — пока жива её interaction (15 минут)."""
        entry = self.panels.get(uid)
        if not entry:
            return
        interaction, sig, since = entry
        if time.monotonic() - since > PANEL_SEC:
            self.panels.pop(uid, None)
            return
        embed, view, new_sig = panel(self, uid)
        if new_sig == sig:
            return
        try:
            await interaction.edit_original_response(embed=embed, view=view)
            entry[1] = new_sig
        except discord.HTTPException:
            self.panels.pop(uid, None)

    # — конец —
    def payouts(self) -> dict:
        """id человека → сколько зачислить ему (ставки уже списаны)."""
        g = self.game
        if not self.stake:
            return {}
        humans = [p for p in g.players if not p.bot]
        if g.loser is None:
            return {p.id: self.stake for p in humans}
        share = self.pot // (len(g.players) - 1)
        return {p.id: share - calculate_tax(share - self.stake) for p in humans if p is not g.loser}

    async def finish(self):
        if self.done:
            return
        self.done = True
        g = self.game
        pay = self.payouts()
        for uid, credit in pay.items():
            player_funds[str(uid)] = player_funds.get(str(uid), 0) + credit
        if pay:
            save_funds()
        self.release()
        if g.loser is None:
            verdict = "🤝 **Ничья** — последние вышли одновременно." + (" Ставки возвращены." if self.stake else "")
        else:
            verdict = f"🤡 **Дурак — {g.loser.name}!**"
        lines = [verdict]
        if g.order_out:
            lines.append("Вышли: " + ", ".join(f"{n}. {p.name}" for n, p in enumerate(g.order_out, 1)))
        if self.stake and g.loser is not None:
            for p in g.players:
                if not p.bot:
                    net = pay.get(p.id, 0) - self.stake
                    lines.append(f"{p.name}: {'+' if net > 0 else ''}{net:,} 💰")
        if g.loser is not None and g.loser.hand:
            lines.append(f"Карты дурака: {cards_text(g.loser.hand)}")
        color = discord.Color.gold() if g.loser is None or g.loser.bot else discord.Color.red()
        e = discord.Embed(title=f"🃏 Дурак · {g.rules.describe()}", description="\n".join(lines), color=color)
        view = RematchView(self)
        try:
            await self.message.edit(embed=e, view=view)
            view.message = self.message
        except (discord.HTTPException, AttributeError):
            pass
        for uid in list(self.panels):
            interaction = self.panels.pop(uid)[0]
            try:
                await interaction.edit_original_response(content="Партия окончена.", embed=None, view=None)
            except discord.HTTPException:
                pass
        print(f"[DURAK] конец партии: {'ничья' if g.loser is None else 'дурак — ' + ('бот' if g.loser.bot else 'человек')}")

    def release(self):
        self.view.stop()
        for uid in self.members:
            if SEATS.get(uid) == self.channel.id:
                SEATS.pop(uid, None)
        if GAMES.get(self.channel.id) is self:
            GAMES.pop(self.channel.id, None)

    def refund(self):
        if self.done:
            return
        self.done = True
        if self.stake:
            for uid in self.members:
                player_funds[str(uid)] = player_funds.get(str(uid), 0) + self.stake
            save_funds()
        self.release()

    async def abort(self, text: str):
        self.refund()
        try:
            await self.message.edit(embed=discord.Embed(title="🃏 Дурак", description=text,
                                                        color=discord.Color.light_grey()), view=None)
        except (discord.HTTPException, AttributeError):
            pass


def panel(match: Match, uid: int):
    """Личная панель: рука, что делать, меню разрешённых ходов. Возвращает (embed, view, подпись)."""
    g = match.game
    p, i = g.player(uid), g.index(uid)
    moves = [] if g.finished else g.moves(uid)
    kinds = {k for k, _ in moves}
    if p.out:
        status = "🏁 Ты вышел — ждём конца партии."
    elif i == g.defender and g.table and not g.taking:
        status = "🛡️ **Отбивайся**" + (" или переводи" if "transfer" in kinds else "") + " — или «Беру»."
    elif i == g.attacker and not g.table:
        status = "⚔️ **Твой ход** — выбери карту."
    elif "pass" in kinds:
        status = "➕ Можно подкинуть — или «Бито / Пас»." if "attack" in kinds else "Нечего подкинуть — жми «Бито / Пас»."
    else:
        status = f"⏳ {g.waiting_for()}"
    under = f" · под колодой `{g.trump_card.label}`" if g.deck else ""
    e = discord.Embed(title="🃏 Мои карты", color=DURAK_COLOR,
                      description=f"Козырь **{g.trump}**{under}\n\n{hand_text(g, p.hand)}\n\n{status}")
    sig = (tuple(p.hand), tuple(moves), status, len(g.table))
    return e, HandView(match, uid, moves), sig


# ── Кнопки стола и панели ─────────────────────────────────────
class TableView(View):
    def __init__(self, match: Match):
        super().__init__(timeout=None)
        self.match = match
        for label, emoji, style, cb in (("Мои карты", "🃏", BLUE, self._hand), ("Беру", "✋", RED, self._take),
                                        ("Бито / Пас", "✅", GREEN, self._pass),
                                        ("Сдаться", "🏳️", GREY, self._resign)):
            b = Button(label=label, emoji=emoji, style=style)
            b.callback = cb
            self.add_item(b)

    async def interaction_check(self, interaction) -> bool:
        if interaction.user.id not in self.match.members:
            await interaction.response.send_message("Ты не в этой партии — дождись следующей.", ephemeral=True)
            return False
        if self.match.done:
            await interaction.response.send_message("Партия уже окончена.", ephemeral=True)
            return False
        self.match.wake(interaction.user.id)
        return True

    async def _hand(self, interaction):
        m = self.match
        embed, view, sig = panel(m, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)
        m.panels[interaction.user.id] = [interaction, sig, time.monotonic()]

    async def _do(self, interaction, kind: str):
        try:
            await self.match.human_move(interaction.user.id, (kind, None))
        except MoveError as exc:
            await interaction.response.send_message(f"❌ {str(exc).capitalize()}", ephemeral=True)
            return
        await interaction.response.defer()
        await self.match.refresh()

    async def _take(self, interaction):
        await self._do(interaction, "take")

    async def _pass(self, interaction):
        await self._do(interaction, "pass")

    async def _resign(self, interaction):
        m = self.match
        view = View(timeout=30)
        b = Button(label="Да, сдаюсь", style=RED, emoji="🏳️")

        async def yes(i2):
            try:
                async with m.lock:
                    m.game.resign(i2.user.id)
            except MoveError as exc:
                await i2.response.edit_message(content=f"❌ {str(exc).capitalize()}", view=None)
                return
            m.changed.set()
            await i2.response.edit_message(content="🏳️ Ты сдался.", view=None)
        b.callback = yes
        view.add_item(b)
        text = "Сдаться? Ты станешь дураком" + (" и потеряешь ставку." if m.stake else ".")
        await interaction.response.send_message(text, view=view, ephemeral=True)


class HandView(View):
    def __init__(self, match: Match, uid: int, moves: list):
        super().__init__(timeout=PANEL_SEC)
        self.match, self.uid = match, uid
        cards = [(k, c) for k, c in moves if c is not None]
        if cards:
            sel = Select(placeholder="Выбери карту", row=0, options=[
                discord.SelectOption(label=move_label(match.game, uid, k, c)[:100], value=f"{k}:{c.code}")
                for k, c in cards[:25]])
            sel.callback = self._card
            self.add_item(sel)
        kinds = {k for k, _ in moves}
        if "take" in kinds:
            self._btn("Беру", "✋", RED, self._take)
        if "pass" in kinds:
            self._btn("Бито / Пас", "✅", GREEN, self._pass)
        self._btn("Обновить", "🔄", GREY, self._show)

    def _btn(self, label, emoji, style, cb):
        b = Button(label=label, emoji=emoji, style=style, row=1)
        b.callback = cb
        self.add_item(b)

    async def interaction_check(self, interaction) -> bool:
        if self.match.done:
            await interaction.response.edit_message(content="Партия окончена.", embed=None, view=None)
            return False
        self.match.wake(self.uid)
        return True

    async def _card(self, interaction):
        kind, code = interaction.data["values"][0].split(":", 1)
        await self._do(interaction, (kind, Card.parse(code)))

    async def _take(self, interaction):
        await self._do(interaction, ("take", None))

    async def _pass(self, interaction):
        await self._do(interaction, ("pass", None))

    async def _do(self, interaction, move: tuple):
        m = self.match
        try:
            await m.human_move(self.uid, move)
        except MoveError as exc:
            embed, view, sig = panel(m, self.uid)
            embed.description += f"\n\n❌ {str(exc).capitalize()}"
            await interaction.response.edit_message(embed=embed, view=view)
            m.panels[self.uid] = [interaction, sig, time.monotonic()]
            return
        await self._show(interaction)
        await m.refresh(skip=self.uid)

    async def _show(self, interaction):
        m = self.match
        if m.done:
            await interaction.response.edit_message(content="Партия окончена.", embed=None, view=None)
            return
        embed, view, sig = panel(m, self.uid)
        await interaction.response.edit_message(embed=embed, view=view)
        m.panels[self.uid] = [interaction, sig, time.monotonic()]


class RematchView(View):
    def __init__(self, match: Match):
        super().__init__(timeout=300)
        self.match = match
        self.message = None
        b = Button(label="Ещё партия", emoji="🔁", style=GREEN)
        b.callback = self._again
        self.add_item(b)

    async def _again(self, interaction):
        m = self.match
        r = m.game.rules
        opts = {"rules": Rules(r.mode, r.throwers, r.deck), "stake": m.stake,
                "bots": sum(1 for p in m.game.players if p.bot)}
        err = await m.cog.open_lobby(interaction.channel, interaction.user, opts)
        if err:
            await interaction.response.send_message(f"❌ {err.capitalize()}.", ephemeral=True)
            return
        self.stop()
        await interaction.response.edit_message(view=None)

    async def on_timeout(self):
        try:
            await self.message.edit(view=None)
        except (discord.HTTPException, AttributeError):
            pass


# ── Cog ───────────────────────────────────────────────────────
class DurakCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def cog_unload(self):
        """Перезагрузка модуля или выключение — незаконченные партии возвращают ставки."""
        for game in list(GAMES.values()):
            if isinstance(game, Match):
                if game.task:
                    game.task.cancel()
                game.refund()
            else:
                game.closed = True
                game.stop()
        GAMES.clear()
        SEATS.clear()

    async def open_lobby(self, channel, user, opts, start: bool = False, redraw: bool = True):
        """Новый набор в канале или вход в уже открытый (opts тогда не нужны). Возвращает текст ошибки или None.
        channel может быть записывающей обёрткой Джарвиса: в неё уходит только первое сообщение, игра живёт
        в настоящем канале."""
        sender, channel = channel, getattr(channel, "_channel", channel)
        current = GAMES.get(channel.id)
        if isinstance(current, Match):
            return "в этом канале уже идёт партия — дождись конца"
        if user.id in SEATS:
            if SEATS[user.id] == channel.id:
                return "ты уже за столом"
            return "ты уже играешь в другом канале"
        await init_player(self.bot, user.id)
        if isinstance(current, Lobby):
            err = current.add(user)
            if not err and redraw:
                await current.redraw()
            return err
        if opts is None:
            return "набор уже закрыт"
        cash = player_funds.get(str(user.id), 0)
        if cash < opts["stake"]:
            return f"на ставку {money(opts['stake'])} не хватает денег — на руках {money(cash)}"
        lobby = Lobby(self, channel, user, opts)
        GAMES[channel.id] = lobby
        SEATS[user.id] = channel.id
        if start and lobby.seats < 2:
            lobby.bots = 1
            lobby.build()
        lobby.message = await sender.send(embed=lobby.embed(), view=lobby)
        lobby.message = getattr(lobby.message, "_message", lobby.message)
        if start:
            await lobby.start()
        return None

    @commands.command(name="durak", aliases=["дурак"], brief="Дурак: подкидной или переводной, 24/36/52 карты",
                      help="`!дурак` — открыть набор: правила и ставку выбирают в меню, игроки жмут «Вступить».\n"
                           "Опции словами (любые, в любом порядке): `переводной` / `подкидной`, `соседи` / `все` "
                           "(кто подкидывает), `24` / `36` / `52` (колода), `бот` или `2 бота`, ставка `500`, "
                           "`сразу` — начать без ожидания.\n"
                           "Пример: `!дурак переводной все 52 бот 500 сразу`\n"
                           "`!дурак правила` — как играть.")
    async def durak(self, ctx, *, options: str = ""):
        if re.search(r"(^|\s)(правила|rules|как)(\s|$)", options.lower()):
            await ctx.send(embed=discord.Embed(title="🃏 Как играть в дурака", description=RULES_TEXT,
                                               color=DURAK_COLOR))
            return
        opts = parse_options(options)
        err = await self.open_lobby(ctx.channel, ctx.author, opts, start=opts["start"])
        if err:
            await ctx.send(f"❌ {ctx.author.mention}, {err}.", delete_after=8)


def setup(bot):
    bot.add_cog(DurakCog(bot))
