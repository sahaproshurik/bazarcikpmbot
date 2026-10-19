"""
durak_engine.py — правила «Дурака» без Discord: колода, ходы, проверка ходов, добор, конец игры, бот-игрок.

Варианты:
• режим — подкидной (throw) или переводной (transfer): пока ни одна карта не отбита, отбивающийся может
  перевести атаку, положив карту того же достоинства, — если у следующего игрока хватит карт отбиться;
• кто подкидывает — только соседи отбивающегося (neighbors) или все остальные (all);
• колода — 24 (от девятки), 36 (от шестёрки) или 52 (от двойки).

Классика: первым ходит тот, у кого младший козырь; на столе не больше 6 атакующих карт и не больше, чем
карт у отбивающегося; «бито», когда все, кто может подкидывать, спасовали; взявший пропускает ход; после
кона все добирают до 6 — атакующий первым, отбивавшийся последним; карты кончились у всех, кроме одного, —
он дурак. Если последние вышли одновременно — ничья.
"""
import random
from dataclasses import dataclass, field
from typing import Optional

SUITS = "♠♥♦♣"
RED_SUITS = "♥♦"
RANK_NAMES = {11: "В", 12: "Д", 13: "К", 14: "Т"}
DECKS = {24: range(9, 15), 36: range(6, 15), 52: range(2, 15)}
MAX_PLAYERS = {24: 4, 36: 6, 52: 6}
HAND = 6
MAX_ATTACK = 6
MODES = {"throw": "подкидной", "transfer": "переводной"}
THROWERS = {"neighbors": "подкидывают соседи", "all": "подкидывают все"}


@dataclass(frozen=True, order=True)
class Card:
    rank: int
    suit: str

    @property
    def label(self) -> str:
        return f"{RANK_NAMES.get(self.rank, str(self.rank))}{self.suit}"

    @property
    def code(self) -> str:
        return f"{self.rank}{self.suit}"

    @staticmethod
    def parse(code: str) -> "Card":
        return Card(int(code[:-1]), code[-1])


@dataclass
class Rules:
    mode: str = "throw"
    throwers: str = "neighbors"
    deck: int = 36

    def describe(self) -> str:
        return f"{MODES[self.mode]}, {THROWERS[self.throwers]}, колода {self.deck}"


@dataclass
class Player:
    id: int
    name: str
    bot: bool = False
    hand: list = field(default_factory=list)
    out: bool = False                       # вышел из игры (карты кончились, колода пуста)


class MoveError(Exception):
    """Ход не по правилам — текст можно показать игроку."""


class Durak:
    def __init__(self, players: list, rules: Rules = None, rng: random.Random = None):
        self.rules = rules or Rules()
        self.rng = rng or random.Random()
        if not 2 <= len(players) <= MAX_PLAYERS[self.rules.deck]:
            raise MoveError(f"в колоде {self.rules.deck} играют от 2 до {MAX_PLAYERS[self.rules.deck]} человек")
        self.players = [p if isinstance(p, Player) else Player(*p) for p in players]
        self.deck = [Card(r, s) for s in SUITS for r in DECKS[self.rules.deck]]
        self.rng.shuffle(self.deck)
        for _ in range(HAND):
            for p in self.players:
                p.hand.append(self.deck.pop())
        self.trump_card = self.deck[0] if self.deck else self.players[-1].hand[-1]   # нижняя карта колоды
        self.trump = self.trump_card.suit
        self.table: list = []               # [[атака, защита или None], ...]
        self.passed: set = set()
        self.taking = False
        self.finished = False
        self.loser: Optional[Player] = None
        self.order_out: list = []           # кто в каком порядке вышел
        self.log: list = []
        self.discard = 0
        self.attacker = self._first_attacker()
        self.defender = self._next_active(self.attacker)
        for p in self.players:
            self.sort(p)

    # ── Справки ───────────────────────────────────────────────
    def sort(self, p: Player):
        p.hand.sort(key=lambda c: (c.suit == self.trump, c.rank, c.suit))

    def player(self, pid: int) -> Player:
        for p in self.players:
            if p.id == pid:
                return p
        raise MoveError("ты не в этой игре")

    def index(self, pid: int) -> int:
        return self.players.index(self.player(pid))

    def active(self) -> list:
        return [i for i, p in enumerate(self.players) if not p.out]

    def _next_active(self, i: int) -> int:
        n = len(self.players)
        for step in range(1, n + 1):
            j = (i + step) % n
            if not self.players[j].out:
                return j
        return i

    def _first_attacker(self) -> int:
        best = None
        for i, p in enumerate(self.players):
            for c in p.hand:
                if c.suit == self.trump and (best is None or c.rank < best[1]):
                    best = (i, c.rank)
        return best[0] if best else self.rng.randrange(len(self.players))

    def beats(self, attack: Card, defense: Card) -> bool:
        if defense.suit == attack.suit:
            return defense.rank > attack.rank
        return defense.suit == self.trump and attack.suit != self.trump

    def open_attacks(self) -> list:
        return [i for i, (a, d) in enumerate(self.table) if d is None]

    def ranks_on_table(self) -> set:
        return {c.rank for pair in self.table for c in pair if c is not None}

    def throwers(self) -> list:
        """Кто сейчас может подкидывать (индексы)."""
        if self.finished:
            return []
        if self.rules.throwers == "all" or len(self.active()) <= 2:
            who = [i for i in self.active() if i != self.defender]
        else:
            who = list(dict.fromkeys([self.attacker, self._next_active(self.defender)]))
            who = [i for i in who if i != self.defender]
        return who

    def room(self) -> int:
        """Сколько ещё карт можно подкинуть: всего ≤ 6 и не больше, чем отбивающийся может покрыть."""
        defender = self.players[self.defender]
        return max(0, min(MAX_ATTACK - len(self.table), len(defender.hand) - len(self.open_attacks())))

    def can_transfer(self) -> bool:
        if self.rules.mode != "transfer" or not self.table or self.taking:
            return False
        if any(d is not None for _, d in self.table):
            return False
        nxt = self.players[self._next_active(self.defender)]
        return (len({a.rank for a, _ in self.table}) == 1 and len(self.table) < MAX_ATTACK
                and len(nxt.hand) >= len(self.table) + 1)

    def waiting_for(self) -> str:
        """Что сейчас ждём — для подписи на столе."""
        if self.finished:
            return "Игра окончена"
        att, dfd = self.players[self.attacker], self.players[self.defender]
        if not self.table:
            return f"{att.name} ходит под {dfd.name}"
        if self.taking:
            return f"{dfd.name} берёт — можно подкинуть вдогонку или «Пас»"
        if self.open_attacks():
            return f"{dfd.name} отбивается" + (" или переводит" if self.can_transfer() else "")
        return "Всё отбито — подкиньте или «Бито»"

    # ── Ходы ──────────────────────────────────────────────────
    def _changed(self):
        self.passed = set()

    # Проверки (check_*) только бросают MoveError — по ним панель игрока показывает разрешённые ходы.
    def check_attack(self, pid: int, card: Card):
        i, p = self.index(pid), self.player(pid)
        self._live(p)
        self._own(p, card)
        if i == self.defender:
            raise MoveError("ты отбиваешься — подкидывать нельзя")
        if not self.table:
            if i != self.attacker:
                raise MoveError(f"первым ходит {self.players[self.attacker].name}")
        else:
            if i not in self.throwers():
                raise MoveError("сейчас подкидывают только соседи отбивающегося")
            if card.rank not in self.ranks_on_table():
                raise MoveError("подкидывать можно только карты того же достоинства, что на столе")
        if self.room() <= 0:
            raise MoveError("больше подкидывать нельзя — на столе максимум")

    def attack(self, pid: int, card: Card):
        self.check_attack(pid, card)
        p = self.player(pid)
        p.hand.remove(card)
        self.table.append([card, None])
        self.log.append(f"{p.name}: {card.label}")
        self._changed()

    def check_defend(self, pid: int, card: Card, target: int = None) -> int:
        """Какую атаку покроет карта (индекс на столе)."""
        i, p = self.index(pid), self.player(pid)
        self._live(p)
        self._own(p, card)
        if i != self.defender:
            raise MoveError("отбивается не ты")
        if self.taking:
            raise MoveError("ты уже берёшь")
        targets = [t for t in self.open_attacks() if self.beats(self.table[t][0], card)]
        if target is not None:
            targets = [t for t in targets if t == target]
        if not targets:
            raise MoveError(f"{card.label} не бьёт ни одну карту на столе")
        # если карта бьёт несколько — кроем самую сильную, чтобы младшие остались под младшие карты
        return max(targets, key=lambda k: (self.table[k][0].suit == self.trump, self.table[k][0].rank))

    def defend(self, pid: int, card: Card, target: int = None):
        t = self.check_defend(pid, card, target)
        p = self.player(pid)
        p.hand.remove(card)
        self.table[t][1] = card
        self.log.append(f"{p.name}: {self.table[t][0].label} ← {card.label}")
        self._changed()
        self._maybe_end_bout()

    def check_transfer(self, pid: int, card: Card):
        i, p = self.index(pid), self.player(pid)
        self._live(p)
        self._own(p, card)
        if i != self.defender:
            raise MoveError("переводит только отбивающийся")
        if not self.can_transfer():
            raise MoveError("перевести нельзя: игра подкидная, что-то уже отбито или у следующего мало карт")
        if card.rank != self.table[0][0].rank:
            raise MoveError("переводят картой того же достоинства")

    def transfer(self, pid: int, card: Card):
        self.check_transfer(pid, card)
        p = self.player(pid)
        p.hand.remove(card)
        self.table.append([card, None])
        self.attacker, self.defender = self.defender, self._next_active(self.defender)
        self.log.append(f"{p.name} переводит {card.label} → {self.players[self.defender].name}")
        self._changed()

    def check_take(self, pid: int):
        self._live(self.player(pid))
        if self.index(pid) != self.defender:
            raise MoveError("берёт только отбивающийся")
        if not self.table:
            raise MoveError("на столе пусто")
        if not self.open_attacks():
            raise MoveError("всё уже отбито")
        if self.taking:
            raise MoveError("ты уже берёшь")

    def take(self, pid: int):
        self.check_take(pid)
        self.taking = True
        self.log.append(f"{self.players[self.defender].name} берёт")
        self._changed()
        self._maybe_end_bout()

    def check_pass(self, pid: int):
        i = self.index(pid)
        self._live(self.players[i])
        if i == self.defender:
            raise MoveError("отбивающийся не пасует — отбивайся или бери")
        if not self.table:
            raise MoveError("сначала нужно сходить")
        if i not in self.throwers():
            raise MoveError("ты сейчас не подкидываешь")
        if not self.taking and self.open_attacks():
            raise MoveError("ещё не всё отбито")
        if i in self.passed:
            raise MoveError("ты уже спасовал")

    def pass_(self, pid: int):
        self.check_pass(pid)
        self.passed.add(self.index(pid))
        self._maybe_end_bout()

    def resign(self, pid: int):
        """Сдался — сразу дурак, игра заканчивается."""
        self._live(self.player(pid))
        self.loser = self.player(pid)
        self.finished = True
        self.log.append(f"{self.loser.name} сдаётся")

    def moves(self, pid: int) -> list:
        """Все ходы, разрешённые игроку сейчас: [(вид, карта или None)], карты — в порядке руки."""
        out = []
        p = self.player(pid)
        for kind, check in (("transfer", self.check_transfer), ("defend", self.check_defend),
                            ("attack", self.check_attack)):
            for c in p.hand:
                try:
                    check(pid, c)
                    out.append((kind, c))
                except MoveError:
                    pass
        for kind, check in (("take", self.check_take), ("pass", self.check_pass)):
            try:
                check(pid)
                out.append((kind, None))
            except MoveError:
                pass
        return out

    def _live(self, p: Player):
        if self.finished:
            raise MoveError("игра окончена")
        if p.out:
            raise MoveError("ты уже вышел из игры")

    @staticmethod
    def _own(p: Player, card: Card):
        if card not in p.hand:
            raise MoveError(f"у тебя нет {card.label}")

    # ── Конец кона и добор ────────────────────────────────────
    def _maybe_end_bout(self):
        if not self.table or (not self.taking and self.open_attacks()):
            return
        waiting = [i for i in self.throwers() if i not in self.passed and self.players[i].hand and self.room() > 0]
        if not waiting:
            self._end_bout()

    def _end_bout(self):
        defender = self.players[self.defender]
        cards = [c for pair in self.table for c in pair if c is not None]
        if self.taking:
            defender.hand.extend(cards)
            self.sort(defender)
            next_attacker = self._next_active(self.defender)
        else:
            self.discard += len(cards)
            self.log.append("Бито")
            next_attacker = self.defender
        self.table, self.taking = [], False
        self._changed()
        self._draw()
        self._mark_out()
        if self.finished:
            return
        if self.players[next_attacker].out:
            next_attacker = self._next_active(next_attacker)
        self.attacker = next_attacker
        self.defender = self._next_active(self.attacker)

    def _draw(self):
        order, i = [self.attacker], self.attacker
        for _ in range(len(self.players)):
            i = (i + 1) % len(self.players)
            if i not in order and i != self.defender:
                order.append(i)
        order.append(self.defender)
        for i in order:
            p = self.players[i]
            while len(p.hand) < HAND and self.deck:
                p.hand.append(self.deck.pop())
            self.sort(p)

    def _mark_out(self):
        if self.deck:
            return
        for p in self.players:
            if not p.out and not p.hand:
                p.out = True
                self.order_out.append(p)
        left = [p for p in self.players if not p.out]
        if len(left) <= 1:
            self.finished = True
            self.loser = left[0] if left else None

    # ── Бот-игрок ─────────────────────────────────────────────
    def _value(self, c: Card) -> tuple:
        return (c.suit == self.trump, c.rank)

    def bot_move(self, pid: int) -> Optional[tuple]:
        """Ход бота: ('attack'|'defend'|'transfer'|'take'|'pass', карта) или None — бот сейчас не ходит."""
        if self.finished:
            return None
        i, p = self.index(pid), self.player(pid)
        if p.out:
            return None
        if i == self.defender and self.table and not self.taking:
            if not self.open_attacks():
                return None
            if self.can_transfer():
                same = [c for c in p.hand if c.rank == self.table[0][0].rank and c.suit != self.trump]
                if same:
                    return ("transfer", min(same, key=self._value))
            spare = list(p.hand)
            plan = []
            for t in sorted(self.open_attacks(), key=lambda k: self._value(self.table[k][0]), reverse=True):
                options = [c for c in spare if self.beats(self.table[t][0], c)]
                if not options:
                    return ("take", None)
                best = min(options, key=self._value)
                plan.append(best)
                spare.remove(best)
            return ("defend", plan[0])
        if not self.table:
            if i != self.attacker:
                return None
            plain = [c for c in p.hand if c.suit != self.trump] or p.hand
            return ("attack", min(plain, key=self._value))
        if i in self.throwers() and i not in self.passed and (self.taking or not self.open_attacks()):
            if self.room() > 0:
                ranks = self.ranks_on_table()
                fits = [c for c in p.hand if c.rank in ranks and (c.suit != self.trump or not self.deck)]
                if fits:
                    return ("attack", min(fits, key=self._value))
            return ("pass", None)
        return None

    def play(self, pid: int, move: tuple):
        kind, card = move
        if kind == "attack":
            self.attack(pid, card)
        elif kind == "defend":
            self.defend(pid, card)
        elif kind == "transfer":
            self.transfer(pid, card)
        elif kind == "take":
            self.take(pid)
        elif kind == "pass":
            self.pass_(pid)
