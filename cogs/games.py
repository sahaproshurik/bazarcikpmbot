"""
games.py — казино BAZARCIK: слоты, рулетка, монетка, кубик и блэкджек.

Каждая игра — одно сообщение с анимацией и кнопками «Ещё раз / ×2 / ½ / Игры».
Ставка: число, 5k, 1.5m, all (ва-банк) или half (половина наличных). Без ставки — кнопки выбора ставки.
!игры — меню всех игр кнопками (казино и «Дурак»), команды писать не нужно.
Выигрыш: +10% с 🍀 Амулетом удачи, налог 18% с прибыли выше TAX_THRESHOLD — одинаково во всех играх.
"""
import asyncio
import random
from typing import Optional
import discord
from discord.ui import Modal, InputText
from discord.ext import commands
from data import (
    player_funds, player_inventory, casino_stats, REDS, TAX_THRESHOLD, card_values, suits,
    save_funds, save_casino,
)
from cogs.economy import init_player, calculate_tax
from views import OwnedView, GREY, GREEN, BLUE, RED

CASINO_COLOR = discord.Color.from_rgb(155, 89, 182)
WIN, LOSE, JACKPOT, PUSH = (discord.Color.green(), discord.Color.red(),
                            discord.Color.gold(), discord.Color.light_grey())
FRAME = 0.7          # пауза между кадрами анимации, секунд
CHARM_BONUS = 0.10   # 🍀 Амулет удачи

SLOT_SYMBOLS = ["🍒", "🍋", "🍉", "🍇", "🍊", "🍍", "💎", "7️⃣"]
DICE_FACES   = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
COIN = {"heads": ("Орёл", "🦅"), "tails": ("Решка", "🪙")}
COIN_ALIASES = {"о": "heads", "орел": "heads", "орёл": "heads", "o": "heads", "orel": "heads", "heads": "heads",
                "р": "tails", "решка": "tails", "p": "tails", "reshka": "tails", "tails": "tails"}
ROULETTE_BETS = {"red": ("Красное", "🔴", 2), "black": ("Чёрное", "⚫", 2), "green": ("Зеро", "🟢", 14)}
ROULETTE_ALIASES = {"red": "red", "красное": "red", "к": "red",
                    "black": "black", "черное": "black", "чёрное": "black", "ч": "black",
                    "green": "green", "зеро": "green", "zero": "green", "з": "green"}


# ── Ставки и расчёт ───────────────────────────────────────────
def parse_bet(argument: str, cash: int) -> int:
    """Ставка: 500, 5k, 1.5m, all/всё, half/половина. Не число — ValueError."""
    a = argument.lower().replace(" ", "").replace("_", "")
    if a in ("all", "allin", "всё", "все", "вабанк", "ва-банк"):
        return cash
    if a in ("half", "половина", "пол"):
        return cash // 2
    mult = 1
    if a[-1:] in ("k", "к"):
        mult, a = 1_000, a[:-1]
    elif a[-1:] in ("m", "м"):
        mult, a = 1_000_000, a[:-1]
    try:
        return int(float(a.replace(",", ".")) * mult)
    except OverflowError:
        raise ValueError(argument)


class Bet(commands.Converter):
    """Ставка: 500, 5k, 1.5m, all/всё, half/половина."""
    async def convert(self, ctx, argument: str) -> int:
        try:
            return parse_bet(argument, player_funds.get(str(ctx.author.id), 0))
        except ValueError:
            raise commands.BadArgument(f"Ставка `{argument}` — не число. Примеры: 500, 5k, all, half")


def balance(uid: str) -> int:
    return player_funds.get(uid, 0)


def bet_error(uid: str, bet: int):
    if bet <= 0:
        return "ставка должна быть больше нуля."
    if bet > balance(uid):
        return f"не хватает денег — на руках {balance(uid):,} 💰."
    return None


def has_charm(uid: str) -> bool:
    return player_inventory.get(uid, {}).get("lucky_charm", 0) > 0


def player_stats(uid: str) -> dict:
    st = casino_stats.setdefault(uid, {})
    for key in ("games", "wins", "wagered", "net", "biggest"):
        st.setdefault(key, 0)
    return st


def settle(uid: str, bet: int, payout: int) -> dict:
    """Ставка уже списана; payout — сколько вернуть игроку вместе со ставкой."""
    profit = payout - bet
    bonus  = int(profit * CHARM_BONUS) if profit > 0 and has_charm(uid) else 0
    tax    = calculate_tax(profit + bonus) if profit > 0 else 0
    credit = payout + bonus - tax
    player_funds[uid] = balance(uid) + credit
    net = credit - bet
    st = player_stats(uid)
    st["games"]   += 1
    st["wagered"] += bet
    st["net"]     += net
    if net > 0:
        st["wins"]   += 1
        st["biggest"] = max(st["biggest"], net)
    save_funds()
    save_casino()
    return {"bet": bet, "net": net, "bonus": bonus, "tax": tax}


# ── Отрисовка ─────────────────────────────────────────────────
def table_embed(title: str, user, text: str, color=CASINO_COLOR) -> discord.Embed:
    e = discord.Embed(title=title, description=text, color=color)
    e.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    return e


def result_embed(title: str, user, board: str, verdict: str, res: dict, color) -> discord.Embed:
    e = table_embed(title, user, f"{board}\n\n{verdict}", color)
    net = res["net"]
    e.add_field(name="Ставка", value=f"{res['bet']:,} 💰")
    e.add_field(name="Итог", value=f"{'+' if net > 0 else ''}{net:,} 💰")
    e.add_field(name="Баланс", value=f"{balance(str(user.id)):,} 💰")
    extras = []
    if res["bonus"]:
        extras.append(f"🍀 Амулет удачи: +{res['bonus']:,}")
    if res["tax"]:
        extras.append(f"🧾 Налог с выигрыша: −{res['tax']:,}")
    e.set_footer(text=" • ".join(extras) or "!casino — правила и статистика")
    return e


class Table:
    """Одно сообщение казино: первый кадр — ответ на команду или кнопку, дальше — правки."""

    def __init__(self, channel, user, message=None, interaction=None):
        self.channel, self.user, self.message, self.interaction = channel, user, message, interaction
        self.uid = str(user.id)

    @classmethod
    def from_interaction(cls, interaction: discord.Interaction, user) -> "Table":
        return cls(interaction.channel, user, interaction.message, interaction)

    async def show(self, embed: discord.Embed, view=None):
        if self.interaction is not None and not self.interaction.response.is_done():
            await self.interaction.response.edit_message(content=None, embed=embed, view=view)
            self.message = self.interaction.message
        elif self.message is not None:
            await self.message.edit(content=None, embed=embed, view=view)
        else:
            self.message = await self.channel.send(embed=embed, view=view)
        if view is not None:
            view.message = self.message

    async def begin(self, bet: int) -> bool:
        """Проверяет и списывает ставку. Ошибку показывает прямо в сообщении игры."""
        err = bet_error(self.uid, bet)
        if err:
            await self.show(table_embed("❌ Ставка не принята", self.user, f"{self.user.mention}, {err}", LOSE))
            return False
        player_funds[self.uid] -= bet
        save_funds()
        return True


class ReplayView(OwnedView):
    """Кнопки после игры: повторить с той же, двойной или половинной ставкой."""

    def __init__(self, user, bet: int, replay):
        super().__init__(user, timeout=120)
        self.replay, self.used = replay, False
        self.btn(f"Ещё раз · {bet:,}", self._again(bet), GREEN, emoji="🔁")
        self.btn(f"×2 · {bet * 2:,}", self._again(bet * 2), BLUE, emoji="⏫")
        if bet >= 2:
            self.btn(f"½ · {bet // 2:,}", self._again(bet // 2), GREY, emoji="⏬")
        self.btn("Игры", self._hub, GREY, emoji="🎮")

    async def _hub(self, interaction: discord.Interaction):
        if self.used:
            await interaction.response.defer()
            return
        self.used = True
        self.stop()
        await show_hub(Table.from_interaction(interaction, self.user))

    def _again(self, bet: int):
        async def cb(interaction: discord.Interaction):
            err = bet_error(self.uid, bet)
            if err:
                await interaction.response.send_message(f"❌ {err.capitalize()}", ephemeral=True)
                return
            if self.used:                      # второй клик по той же кнопке
                await interaction.response.defer()
                return
            self.used = True
            self.stop()
            await self.replay(bet, interaction)
        return cb

    async def on_timeout(self):
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class ChoiceView(OwnedView):
    """Выбор кнопками, если игрок не указал его в команде (орёл/решка, число, цвет)."""

    def __init__(self, user, options: list, on_pick):
        super().__init__(user, timeout=60)
        self.on_pick, self.used = on_pick, False
        for label, emoji, value, style, row in options:
            self.btn(label, self._pick(value), style, row=row, emoji=emoji)

    def _pick(self, value):
        async def cb(interaction: discord.Interaction):
            if self.used:
                await interaction.response.defer()
                return
            self.used = True
            self.stop()
            await self.on_pick(value, interaction)
        return cb

    async def on_timeout(self):
        if self.message is not None and not self.used:
            try:
                await self.message.edit(content="⌛ Время на выбор вышло — ставка не списана.",
                                        embed=None, view=None)
            except discord.HTTPException:
                pass


class BetModal(Modal):
    def __init__(self, picker: "BetPicker"):
        super().__init__(title="Своя ставка")
        self.picker = picker
        self.add_item(InputText(label="Ставка", placeholder="например 2500, 10k, all, half", max_length=20))

    async def callback(self, interaction: discord.Interaction):
        try:
            bet = parse_bet(self.children[0].value or "", balance(self.picker.uid))
        except ValueError:
            await interaction.response.send_message("❌ Не понял ставку. Примеры: 2500, 10k, all, half",
                                                    ephemeral=True)
            return
        await self.picker.pick(bet, interaction)


class BetPicker(OwnedView):
    """Ставка кнопками: 100 / 500 / 1k / 5k / ½ / ва-банк / своя."""

    def __init__(self, user, on_bet):
        super().__init__(user, timeout=90)
        self.on_bet, self.used = on_bet, False
        cash = balance(self.uid)
        for amount in (100, 500, 1_000, 5_000):
            self.btn(f"{amount:,}", self._fixed(amount), GREEN, row=0, emoji="💰", disabled=amount > cash)
        self.btn(f"½ · {cash // 2:,}", self._fixed(cash // 2), BLUE, row=1, emoji="⏬", disabled=cash < 2)
        self.btn(f"Ва-банк · {cash:,}", self._fixed(cash), RED, row=1, emoji="🔥", disabled=cash <= 0)
        self.btn("Своя", self._custom, GREY, row=1, emoji="✏️", disabled=cash <= 0)

    def _fixed(self, bet: int):
        async def cb(interaction: discord.Interaction):
            await self.pick(bet, interaction)
        return cb

    async def _custom(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BetModal(self))

    async def pick(self, bet: int, interaction: discord.Interaction):
        if self.used:
            await interaction.response.defer()
            return
        self.used = True
        self.stop()
        await self.on_bet(bet, interaction)

    async def on_timeout(self):
        if self.message is not None and not self.used:
            try:
                await self.message.edit(content="⌛ Ставку так и не выбрали.", embed=None, view=None)
            except discord.HTTPException:
                pass


def replay_with(user, game, *args):
    """Колбэк для ReplayView: та же игра с новой ставкой в том же сообщении."""
    async def replay(bet, interaction):
        await game(Table.from_interaction(interaction, user), bet, *args)
    return replay


# ── Слоты ─────────────────────────────────────────────────────
def slot_board(reels: list) -> str:
    return f"## ┃ {' ┃ '.join(reels)} ┃"


async def play_slots(table: Table, bet: int):
    if not await table.begin(bet):
        return
    reels = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
    for stopped in range(3):           # барабаны останавливаются по одному
        frame = reels[:stopped] + [random.choice(SLOT_SYMBOLS) for _ in range(3 - stopped)]
        await table.show(table_embed("🎰 Слоты", table.user, f"{slot_board(frame)}\n\n🌀 Крутим…"))
        await asyncio.sleep(FRAME)
    unique = len(set(reels))
    if unique == 1:
        payout, verdict, color = bet * 5, "💎 **ДЖЕКПОТ!** Три в ряд — ×5", JACKPOT
    elif unique == 2:
        payout, verdict, color = bet * 2, "✨ Два одинаковых — ×2", WIN
    else:
        payout, verdict, color = 0, "😞 Мимо — совпадений нет.", LOSE
    res = settle(table.uid, bet, payout)
    await table.show(result_embed("🎰 Слоты", table.user, slot_board(reels), verdict, res, color),
                     ReplayView(table.user, bet, replay_with(table.user, play_slots)))


# ── Монетка ───────────────────────────────────────────────────
async def play_flip(table: Table, bet: int, side: str):
    if not await table.begin(bet):
        return
    name, emoji = COIN[side]
    await table.show(table_embed("🪙 Монетка", table.user, f"Ставка на **{name}** {emoji}\n\n🪙 Монетка в воздухе…"))
    await asyncio.sleep(FRAME * 1.5)
    result = random.choice(list(COIN))
    rname, remoji = COIN[result]
    board = f"Ставка на **{name}** {emoji}\n## Выпало: {rname} {remoji}"
    won = result == side
    res = settle(table.uid, bet, bet * 2 if won else 0)
    verdict = "🏆 Угадал — ×2!" if won else "😞 Не угадал."
    await table.show(result_embed("🪙 Монетка", table.user, board, verdict, res, WIN if won else LOSE),
                     ReplayView(table.user, bet, replay_with(table.user, play_flip, side)))


# ── Кубик ─────────────────────────────────────────────────────
async def play_dice(table: Table, bet: int, number: int):
    if not await table.begin(bet):
        return
    for _ in range(2):
        face = DICE_FACES[random.randint(1, 6)]
        await table.show(table_embed("🎲 Кубик", table.user, f"Загадано: **{number}**\n## {face}\n\n🎲 Катится…"))
        await asyncio.sleep(FRAME)
    roll = random.randint(1, 6)
    won = roll == number
    res = settle(table.uid, bet, bet * 5 if won else 0)
    board = f"Загадано: **{number}**\n## {DICE_FACES[roll]} — выпало {roll}"
    verdict = "🎯 **Угадал!** ×5" if won else "😞 Не угадал."
    await table.show(result_embed("🎲 Кубик", table.user, board, verdict, res, JACKPOT if won else LOSE),
                     ReplayView(table.user, bet, replay_with(table.user, play_dice, number)))


# ── Рулетка ───────────────────────────────────────────────────
def pocket(number: int):
    color = "green" if number == 0 else ("red" if number in REDS else "black")
    return color, ROULETTE_BETS[color][1]


def roulette_label(choice: str) -> str:
    if choice in ROULETTE_BETS:
        name, emoji, mult = ROULETTE_BETS[choice]
        return f"{emoji} {name} (×{mult})"
    return f"число {choice} (×35)"


async def play_roulette(table: Table, bet: int, choice: str):
    if not await table.begin(bet):
        return
    for _ in range(3):                 # колесо замедляется
        n = random.randint(0, 36)
        await table.show(table_embed("🎡 Рулетка", table.user,
                                     f"Ставка: **{roulette_label(choice)}**\n## {pocket(n)[1]} {n}\n\n🎡 Шарик катится…"))
        await asyncio.sleep(FRAME)
    number = random.randint(0, 36)
    color, emoji = pocket(number)
    if choice in ROULETTE_BETS:
        payout = bet * ROULETTE_BETS[choice][2] if choice == color else 0
    else:
        payout = bet * 35 if int(choice) == number else 0
    board = f"Ставка: **{roulette_label(choice)}**\n## {emoji} {number}"
    verdict = "🏆 Выигрыш!" if payout else "😞 Проигрыш."
    res = settle(table.uid, bet, payout)
    color_embed = JACKPOT if payout >= bet * 14 else WIN if payout else LOSE
    await table.show(result_embed("🎡 Рулетка", table.user, board, verdict, res, color_embed),
                     ReplayView(table.user, bet, replay_with(table.user, play_roulette, choice)))


# ── Блэкджек ──────────────────────────────────────────────────
def create_deck():
    deck = [(c, s) for s in suits for c in card_values]
    random.shuffle(deck)
    return deck


def calculate_hand(hand):
    total = sum(card_values[c] for c, _ in hand)
    aces  = sum(1 for c, _ in hand if c == "A")
    while total > 21 and aces:
        total -= 10; aces -= 1
    return total


def cards(hand) -> str:
    return " ".join(f"`{c}{suits[s]}`" for c, s in hand)


class BlackjackView(OwnedView):
    def __init__(self, table: Table, bet: int):
        super().__init__(table.user, timeout=60)
        self.table, self.bet, self.base_bet = table, bet, bet
        self.deck = create_deck()
        self.ph = [self.deck.pop(), self.deck.pop()]
        self.dh = [self.deck.pop(), self.deck.pop()]
        self.finished = False

    def board(self, reveal: bool) -> str:
        if reveal:
            dealer = f"{cards(self.dh)} — **{calculate_hand(self.dh)}**"
        else:
            dealer = f"{cards(self.dh[:1])} `🂠` — **?**"
        return (f"🤵 **Дилер:** {dealer}\n"
                f"🧑 **{self.user.display_name}:** {cards(self.ph)} — **{calculate_hand(self.ph)}**")

    def build(self):
        self.clear_items()
        self.btn("Ещё карту", self._hit, GREEN, emoji="🃏")
        self.btn("Хватит", self._stand, RED, emoji="✋")
        can_double = len(self.ph) == 2 and balance(self.uid) >= self.bet
        self.btn(f"Удвоить · {self.bet:,}", self._double, BLUE, emoji="💰", disabled=not can_double)

    async def render_turn(self):
        self.build()
        await self.table.show(table_embed("🃏 Блэкджек", self.user,
                                          f"{self.board(False)}\n\nСтавка **{self.bet:,}** 💰 • твой ход!"), self)

    async def start(self):
        if not await self.table.begin(self.bet):
            return
        if calculate_hand(self.ph) == 21 or calculate_hand(self.dh) == 21:
            await self.finish()
        else:
            await self.render_turn()

    async def _hit(self, interaction: discord.Interaction):
        self.table.interaction = interaction
        self.ph.append(self.deck.pop())
        if calculate_hand(self.ph) >= 21:
            await self.finish()
        else:
            await self.render_turn()

    async def _stand(self, interaction: discord.Interaction):
        self.table.interaction = interaction
        await self.finish()

    async def _double(self, interaction: discord.Interaction):
        if len(self.ph) != 2 or balance(self.uid) < self.bet:
            await interaction.response.send_message("❌ Удвоить уже нельзя.", ephemeral=True)
            return
        self.table.interaction = interaction
        player_funds[self.uid] -= self.bet
        save_funds()
        self.bet *= 2
        self.ph.append(self.deck.pop())
        await self.finish()

    async def finish(self):
        if self.finished:
            return
        self.finished = True
        self.stop()
        pt, dt = calculate_hand(self.ph), calculate_hand(self.dh)
        p_nat = len(self.ph) == 2 and pt == 21
        d_nat = len(self.dh) == 2 and dt == 21
        if p_nat and d_nat:
            payout, verdict, color = self.bet, "🤝 У обоих блэкджек — ничья.", PUSH
        elif p_nat:
            payout, verdict, color = self.bet * 3, "🎉 **БЛЭКДЖЕК!** ×3", JACKPOT
        elif d_nat:
            payout, verdict, color = 0, "🤵 У дилера блэкджек.", LOSE
        elif pt > 21:
            payout, verdict, color = 0, f"💥 Перебор — {pt}.", LOSE
        else:
            while calculate_hand(self.dh) < 17:
                self.dh.append(self.deck.pop())
            dt = calculate_hand(self.dh)
            if dt > 21 or pt > dt:
                extra = " Дилер перебрал." if dt > 21 else ""
                payout, verdict, color = self.bet * 2, f"🏆 Победа — ×2!{extra}", WIN
            elif pt < dt:
                payout, verdict, color = 0, "😞 У дилера больше.", LOSE
            else:
                payout, verdict, color = self.bet, "🤝 Ничья — ставка возвращена.", PUSH
        res = settle(self.uid, self.bet, payout)
        replay = ReplayView(self.user, self.base_bet, replay_with(self.user, play_blackjack))
        try:
            await self.table.show(result_embed("🃏 Блэкджек", self.user, self.board(True), verdict, res, color),
                                  replay)
        except discord.HTTPException:
            pass

    async def on_timeout(self):
        if not self.finished:          # время вышло — автоматически «хватит»
            self.table.interaction = None
            await self.finish()


async def play_blackjack(table: Table, bet: int):
    await BlackjackView(table, bet).start()


# ── Запуск без команд: ставка и выбор — кнопками ──────────────
def flip_options():
    return [(name, emoji, side, BLUE, None) for side, (name, emoji) in COIN.items()]


def dice_options():
    return [(str(n), DICE_FACES[n], n, BLUE, (n - 1) // 3) for n in range(1, 7)]


def roulette_options():
    return [(f"{name} ×{mult}", emoji, key, GREEN if key == "green" else GREY, None)
            for key, (name, emoji, mult) in ROULETTE_BETS.items()]


# ключ → (название, игра, кнопки выбора или None, вопрос выбора)
CASINO_GAMES = {
    "spin":     ("🎰 Слоты", play_slots, None, ""),
    "flip":     ("🪙 Монетка", play_flip, flip_options, "орёл или решка?"),
    "dice":     ("🎲 Кубик", play_dice, dice_options, "какое число выпадет?"),
    "roulette": ("🎡 Рулетка", play_roulette, roulette_options, "на что ставишь? На число: `!roulette 500 17`"),
    "bj":       ("🃏 Блэкджек", play_blackjack, None, ""),
}


async def launch(table: Table, key: str, bet: int = None, choice=None):
    """Игра казино в сообщении table: нет ставки — кнопки ставок, нет выбора — кнопки выбора."""
    title, game, options, question = CASINO_GAMES[key]
    user = table.user

    async def with_bet(b, interaction):
        await launch(Table.from_interaction(interaction, user), key, b, choice)

    if bet is None:
        await table.show(table_embed(title, user, f"Какая ставка? На руках **{balance(table.uid):,}** 💰"),
                         BetPicker(user, with_bet))
        return
    err = bet_error(table.uid, bet)
    if err:
        await table.show(table_embed(title, user, f"❌ {user.mention}, {err}\nВыбери другую ставку:", LOSE),
                         BetPicker(user, with_bet))
        return
    if options is not None and choice is None:
        async def chose(value, interaction):
            await game(Table.from_interaction(interaction, user), bet, value)
        await table.show(table_embed(title, user, f"Ставка **{bet:,}** 💰 — {question}"),
                         ChoiceView(user, options(), chose))
        return
    if options is None:
        await game(table, bet)
    else:
        await game(table, bet, choice)


class HubView(OwnedView):
    """!игры — все игры кнопками."""
    deny_text = "Это не твоё меню — открой своё: `!игры`"

    def __init__(self, user):
        super().__init__(user, timeout=180)
        self.used = False
        for n, (key, (title, *_)) in enumerate(CASINO_GAMES.items()):
            emoji, name = title.split(" ", 1)
            self.btn(name, self._casino(key), BLUE, row=n // 3, emoji=emoji)
        self.btn("Дурак", self._durak, GREEN, row=1, emoji="🂡")

    def _casino(self, key: str):
        async def cb(interaction: discord.Interaction):
            if self.used:
                await interaction.response.defer()
                return
            self.used = True
            self.stop()
            await launch(Table.from_interaction(interaction, self.user), key)
        return cb

    async def _durak(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("DurakCog")
        if cog is None:
            await interaction.response.send_message("Дурак сейчас недоступен.", ephemeral=True)
            return
        from cogs.durak import parse_options
        err = await cog.open_lobby(interaction.channel, self.user, parse_options(""))
        if err:
            await interaction.response.send_message(f"❌ {err.capitalize()}.", ephemeral=True)
            return
        self.used = True
        self.stop()
        await interaction.response.edit_message(
            embed=table_embed("🎮 Игры", self.user, "🂡 Открыт набор в «Дурака» — сообщение ниже."), view=None)

    async def on_timeout(self):
        if self.message is not None and not self.used:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


def hub_embed(user) -> discord.Embed:
    e = table_embed("🎮 Игры", user, "Выбери игру — ставку и остальное спрошу кнопками.\n"
                                     f"На руках: **{balance(str(user.id)):,}** 💰")
    e.add_field(name="Казино", inline=False, value=(
        "🎰 Слоты — три в ряд ×5, пара ×2\n🪙 Монетка — ×2\n🎲 Кубик — ×5\n"
        "🎡 Рулетка — цвет ×2, зеро ×14\n🃏 Блэкджек — ×2, блэкджек ×3"))
    e.add_field(name="С друзьями", inline=False, value=(
        "🂡 Дурак — подкидной или переводной, 24/36/52 карты, можно с ботом"))
    e.set_footer(text="Можно и словами: «Базарчик, давай в дурака», «@бот сыграем в слоты»")
    return e


async def show_hub(table: Table):
    await table.show(hub_embed(table.user), HubView(table.user))


# ── Cog ───────────────────────────────────────────────────────
class GamesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def play(self, ctx, key: str, bet=None, choice=None):
        await init_player(self.bot, ctx)
        await launch(Table(ctx.channel, ctx.author), key, bet, choice)

    @commands.command(name="games", aliases=["игры", "game", "игра"], brief="Все игры кнопками",
                      help="`!игры` — меню игр: слоты, монетка, кубик, рулетка, блэкджек, дурак. "
                           "Ставку и выбор бот спросит кнопками.")
    async def games_hub(self, ctx):
        await init_player(self.bot, ctx)
        await show_hub(Table(ctx.channel, ctx.author))

    @commands.command(name="casino", aliases=["казино"], brief="Казино: игры, выплаты и твоя статистика")
    async def casino(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        uid = str(member.id)
        e = discord.Embed(title="🎰 Казино BAZARCIK", color=CASINO_COLOR,
                          description="Ставка: число, `5k`, `1.5m`, `all` (ва-банк) или `half` (половина). "
                                      "Без ставки бот предложит кнопки, а `!игры` — меню всех игр.\n"
                                      "После игры — кнопки **🔁 Ещё раз**, **⏫ ×2**, **⏬ ½** и **🎮 Игры**.")
        e.add_field(name="Игры", inline=False, value=(
            "`!spin [ставка]` — слоты: три в ряд ×5, пара ×2\n"
            "`!roulette [ставка] [red|black|green|0-36]` — ×2 / ×14 / ×35\n"
            "`!flip [ставка] [о|р]` — монетка ×2\n"
            "`!dice [ставка] [1-6]` — кубик ×5\n"
            "`!bj [ставка]` — блэкджек: победа ×2, блэкджек ×3, можно удвоить\n"
            "`!дурак` — карты с друзьями или ботом"))
        e.add_field(name="Правила", inline=False, value=(
            f"🍀 Амулет удачи (`!buy lucky_charm`): +10% к выигрышу — "
            f"{'**есть** ✅' if has_charm(uid) else 'нет'}\n"
            f"🧾 Налог 18% с прибыли выше {TAX_THRESHOLD:,} 💰"))
        st = player_stats(uid) if uid in casino_stats else None
        if st and st["games"]:
            e.add_field(name=f"Статистика {member.display_name}", inline=False, value=(
                f"Игр: **{st['games']}** • побед: **{st['wins']}** ({round(100 * st['wins'] / st['games'])}%)\n"
                f"Поставлено: **{st['wagered']:,}** 💰 • итог: **{'+' if st['net'] > 0 else ''}{st['net']:,}** 💰\n"
                f"Крупнейший выигрыш: **{st['biggest']:,}** 💰"))
        e.set_thumbnail(url=member.display_avatar.url)
        await ctx.send(embed=e)

    @commands.command(name="spin", aliases=["слоты"], brief="Слоты",
                      help="`!spin [ставка]` — три барабана. Три в ряд — ×5, два одинаковых — ×2.\n"
                           "Ставка: число, 5k, all, half; без неё — кнопки. Правила и статистика: `!casino`")
    async def spin(self, ctx, bet: Optional[Bet] = None):
        await self.play(ctx, "spin", bet)

    @commands.command(name="flip", aliases=["монетка"], brief="Монетка: орёл или решка",
                      help="`!flip [ставка] [о|р]` — угадал сторону: ×2. Чего не указал — бот спросит кнопками.")
    async def flip(self, ctx, bet: Optional[Bet] = None, choice: str = None):
        side = None
        if choice is not None:
            side = COIN_ALIASES.get(choice.strip().lower())
            if side is None:
                await ctx.send("❌ Выбери **о** (орёл) или **р** (решка).", delete_after=6)
                return
        await self.play(ctx, "flip", bet, side)

    @commands.command(name="dice", aliases=["кубик"], brief="Кубик: угадай число",
                      help="`!dice [ставка] [1-6]` — угадал число: ×5. Чего не указал — бот спросит кнопками.")
    async def dice_game(self, ctx, bet: Optional[Bet] = None, number: int = None):
        if number is not None and not 1 <= number <= 6:
            await ctx.send("❌ Число от 1 до 6!", delete_after=6)
            return
        await self.play(ctx, "dice", bet, number)

    @commands.command(name="roulette", aliases=["рулетка"], brief="Рулетка",
                      help="`!roulette [ставка] [red|black|green|0-36]` — цвет ×2, зеро ×14, число ×35.\n"
                           "Чего не указал — бот спросит кнопками.")
    async def roulette(self, ctx, bet: Optional[Bet] = None, choice: str = None):
        key = None
        if choice is not None:
            ch = choice.strip().lower()
            key = ROULETTE_ALIASES.get(ch) or (ch if ch.isdigit() and 0 <= int(ch) <= 36 else None)
            if key is None:
                await ctx.send("❌ Выбор: red / black / green / число 0-36", delete_after=6)
                return
        await self.play(ctx, "roulette", bet, key)

    @commands.command(name="bj", aliases=["блэкджек", "blackjack"], brief="Блэкджек",
                      help="`!bj [ставка]` — набери больше дилера, но не больше 21.\n"
                           "Кнопки: 🃏 ещё карту, ✋ хватит, 💰 удвоить (одна карта и двойная ставка).\n"
                           "Победа ×2, блэкджек с раздачи ×3, ничья — ставка возвращается.")
    async def blackjack(self, ctx, bet: Optional[Bet] = None):
        await self.play(ctx, "bj", bet)

def setup(bot):
    bot.add_cog(GamesCog(bot))
