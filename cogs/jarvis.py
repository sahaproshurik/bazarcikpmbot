"""
jarvis.py — «Джарвис»: бот понимает голосовые просьбы и сам выполняет свои команды.

Каждая фраза к боту («Базарчик, …» в войсе или голосовым сообщением) сначала уходит в короткий
ИИ-разбор: это просьба что-то сделать или просто вопрос. Вопрос — обычный ответ ИИ, как раньше.
Просьба — одно из действий белого списка ACTIONS: бот вызывает настоящую команду от имени говорящего,
коротко говорит голосом, что получилось, и дублирует это в чат.

Безопасность:
• голосом выполняется только белый список; owner-команды (!reload, !backup, !botstatus) — никогда;
• права говорящего проверяются так же, как у текстовой команды (command.can_run), — и до вопроса
  о подтверждении, и прямо перед выполнением;
• модерация, переводы и крупные ставки — только после подтверждения: «да» голосом за CONFIRM_SEC
  секунд или кнопкой в чате; нажать её может только тот, кто дал команду.
Расшифровки нигде не сохраняются: в логи попадает только название действия.
"""
import asyncio
import json
import re
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional
import discord
from discord.ext import commands
from discord.ext.commands.view import StringView
import ai
from cogs.voice_ai import say, answer_embed, detect_lang, TTS_VOICES
from names import norm_name, all_aliases, find_member, name_score
from config import TTS_SETTINGS
from data import player_funds
from utils import parse_duration, fmt_duration, utcnow
from views import OwnedView, GREEN, RED

CONFIRM_SEC     = 15         # столько ждём «да» голосом или кнопкой (переводы, крупные ставки)
STRICT          = "strict"   # строгое подтверждение — кик, бан, очистка: полная фраза
STRICT_SEC      = 30         # окно на полную фразу; начинается, когда бот договорил вопрос и создал форму
STRICT_MIN_SEC  = 1.2        # в окне строгого подтверждения фразы короче — короткие «да» — даже не распознаём
BIG_BET_MIN     = 1000       # ставка от этой суммы и не меньше половины наличных — переспрашиваем
VOICE_FORBIDDEN = {"reload", "backup", "botstatus", "status"}   # owner-команды: голосом никогда
LANGS           = ("ru", "uk", "sk", "en")


# ── Фразы бота на языке говорящего ────────────────────────────
PHRASES = {
    "confirm":     {"ru": "{what}? Скажи «да» или нажми кнопку.", "uk": "{what}? Скажи «так» або натисни кнопку.",
                    "sk": "{what}? Povedz áno alebo stlač tlačidlo.", "en": "{what}? Say yes or press the button."},
    "confirm_strict": {"ru": "{what}? Чтобы подтвердить, скажи полностью: {phrase}.",
                       "uk": "{what}? Щоб підтвердити, скажи повністю: {phrase}.",
                       "sk": "{what}? Na potvrdenie povedz celé: {phrase}.",
                       "en": "{what}? To confirm, say in full: {phrase}."},
    "say_full":    {"ru": "Нужна полная фраза: «{phrase}».", "uk": "Потрібна повна фраза: «{phrase}».",
                    "sk": "Treba celú vetu: „{phrase}“.", "en": "I need the full phrase: “{phrase}”."},
    "yes_no":      {"ru": "Скажи «да» или «нет».", "uk": "Скажи «так» або «ні».",
                    "sk": "Povedz áno alebo nie.", "en": "Say yes or no."},
    "cancelled":   {"ru": "Отменил.", "uk": "Скасував.", "sk": "Zrušené.", "en": "Cancelled."},
    "no_rights":   {"ru": "У тебя нет прав на эту команду.", "uk": "У тебе немає прав на цю команду.",
                    "sk": "Na tento príkaz nemáš práva.", "en": "You don't have permission for that."},
    "forbidden":   {"ru": "Эту команду голосом не выполняю, только текстом.",
                    "uk": "Цю команду голосом не виконую, тільки текстом.",
                    "sk": "Tento príkaz hlasom nespustím, iba textom.", "en": "I don't run that command by voice."},
    "unsupported": {"ru": "Такого я пока не умею. Что могу голосом, смотри в !jarvis.",
                    "uk": "Такого я поки не вмію. Що можу голосом, дивись у !jarvis.",
                    "sk": "To zatiaľ neviem. Čo viem hlasom, nájdeš v !jarvis.",
                    "en": "I can't do that yet. See !jarvis for voice commands."},
    "bot_rights":  {"ru": "У меня не хватает прав на это, проверь роль бота.",
                    "uk": "У мене не вистачає прав на це, перевір роль бота.",
                    "sk": "Na to nemám práva, skontroluj rolu bota.", "en": "I lack the permissions for that."},
    "failed":      {"ru": "Не получилось выполнить команду.", "uk": "Не вдалося виконати команду.",
                    "sk": "Príkaz sa nepodarilo vykonať.", "en": "The command failed."},
    "done":        {"ru": "Готово.", "uk": "Готово.", "sk": "Hotovo.", "en": "Done."},
    "bye":         {"ru": "Выключаю прослушивание. Пока!", "uk": "Вимикаю прослуховування. Бувай!",
                    "sk": "Vypínam počúvanie. Ahoj!", "en": "Stopping listening. Bye!"},
    "not_found":   {"ru": "Не нашёл участника {name}.", "uk": "Не знайшов учасника {name}.",
                    "sk": "Nenašiel som člena {name}.", "en": "I couldn't find {name}."},
    "ambiguous":   {"ru": "Не понял, кого именно: {name}?", "uk": "Не зрозумів, кого саме: {name}?",
                    "sk": "Nerozumiem, koho presne: {name}?", "en": "Who exactly: {name}?"},
    "missing":     {"ru": "Не понял {what}. Повтори, пожалуйста.", "uk": "Не зрозумів {what}. Повтори, будь ласка.",
                    "sk": "Nerozumel som {what}. Zopakuj, prosím.", "en": "I didn't catch {what}. Please repeat."},
    "permanent":   {"ru": "навсегда", "uk": "назавжди", "sk": "natrvalo", "en": "permanently"},
    "for":         {"ru": "на {d}", "uk": "на {d}", "sk": "na {d}", "en": "for {d}"},
    "slow_on":     {"ru": "Включить медленный режим в чате, раз в {d}", "uk": "Увімкнути повільний режим у чаті, раз на {d}",
                    "sk": "Zapnúť pomalý režim v chate, raz za {d}", "en": "Turn on slow mode, one message every {d}"},
    "slow_off":    {"ru": "Выключить медленный режим в чате", "uk": "Вимкнути повільний режим у чаті",
                    "sk": "Vypnúť pomalý režim v chate", "en": "Turn off slow mode"},
    "bad_filter":  {"ru": "Не понял фильтр: {why}.", "uk": "Не зрозумів фільтр: {why}.",
                    "sk": "Nerozumiem filtru: {why}.", "en": "I didn't get the filter: {why}."},
}
# что именно не расслышали — по типу параметра
MISSING_WHAT = {
    "member":   {"ru": "кого именно", "uk": "кого саме", "sk": "koho presne", "en": "who exactly"},
    "amount":   {"ru": "какую сумму", "uk": "яку суму", "sk": "akú sumu", "en": "the amount"},
    "bet":      {"ru": "какую ставку", "uk": "яку ставку", "sk": "akú stávku", "en": "the bet"},
    "duration": {"ru": "на какой срок", "uk": "на який строк", "sk": "na ako dlho", "en": "for how long"},
    "delay":    {"ru": "какую задержку", "uk": "яку затримку", "sk": "aké oneskorenie", "en": "the delay"},
    "choice":   {"ru": "что выбрать", "uk": "що обрати", "sk": "čo vybrať", "en": "the choice"},
    "number":   {"ru": "какое число", "uk": "яке число", "sk": "aké číslo", "en": "the number"},
    "alias":    {"ru": "какое прозвище", "uk": "яке прізвисько", "sk": "akú prezývku", "en": "which nickname"},
}
# формы единиц после «на»: одна, 2–4, много
UNITS = {
    "d":   {"ru": ("день", "дня", "дней"), "uk": ("день", "дні", "днів"), "sk": ("deň", "dni", "dní"),
            "en": ("day", "days", "days")},
    "h":   {"ru": ("час", "часа", "часов"), "uk": ("годину", "години", "годин"), "sk": ("hodinu", "hodiny", "hodín"),
            "en": ("hour", "hours", "hours")},
    "m":   {"ru": ("минуту", "минуты", "минут"), "uk": ("хвилину", "хвилини", "хвилин"),
            "sk": ("minútu", "minúty", "minút"), "en": ("minute", "minutes", "minutes")},
    "s":   {"ru": ("секунду", "секунды", "секунд"), "uk": ("секунду", "секунди", "секунд"),
            "sk": ("sekundu", "sekundy", "sekúnd"), "en": ("second", "seconds", "seconds")},
    "msg": {"ru": ("сообщение", "сообщения", "сообщений"), "uk": ("повідомлення", "повідомлення", "повідомлень"),
            "sk": ("správu", "správy", "správ"), "en": ("message", "messages", "messages")},
}


def tr(key: str, lang: str, **kw) -> str:
    texts = PHRASES[key]
    return texts.get(lang, texts["ru"]).format(**kw)


def plural(n: int, unit: str, lang: str) -> str:
    one, few, many = UNITS[unit].get(lang, UNITS[unit]["ru"])
    if lang in ("ru", "uk"):
        form = one if n % 10 == 1 and n % 100 != 11 else few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many
    elif lang == "sk":
        form = one if n == 1 else few if 2 <= n <= 4 else many
    else:
        form = one if n == 1 else many
    return f"{n} {form}"


def spoken_duration(td: timedelta, lang: str) -> str:
    """10 минут, 1 час 30 минут — для озвучки (не больше двух единиц)."""
    secs, parts = int(td.total_seconds()), []
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if secs >= size and len(parts) < 2:
            parts.append(plural(secs // size, unit, lang))
            secs %= size
    return " ".join(parts) or plural(0, "s", lang)


# ── Белый список действий ─────────────────────────────────────
@dataclass
class P:
    """Параметр действия. kind: member, amount, bet, duration, delay, choice, number, text."""
    name: str
    kind: str
    required: bool = True
    kw: Optional[str] = None            # передаётся в команду именованным аргументом
    choices: tuple = ()
    default: Optional[str] = None       # для duration: срок, который команда возьмёт сама


@dataclass
class Action:
    key: str                            # имя действия для ИИ
    command: str                        # настоящая команда бота
    hint: str                           # когда выбирать (для ИИ)
    example: str                        # пример фразы для !jarvis
    group: str
    params: tuple = ()
    confirm: object = False             # True или функция (ctx, значения) → нужно ли подтверждение
    ask: dict = field(default_factory=dict)   # вопрос-подтверждение по языкам
    hierarchy: bool = False             # заранее проверить иерархию ролей (как в moderation)
    build: object = None                # (значения, сервер) → (args, kwargs, описание) — свой вызов команды
    full: dict = field(default_factory=dict)  # для STRICT: фраза, которую надо сказать целиком, по языкам


def clear_call(values: dict, guild):
    """Фильтры очистки от ИИ → строка для !clear. Проверяем её тем же разбором, что и команда:
    непонятный фильтр всплывёт до подтверждения, а не после."""
    from purge_filters import parse_clear
    parts = [str(values["amount"])] if values.get("amount") else []
    if values.get("member") is not None:
        parts.append(f"<@{values['member'].id}>")
    for key, word in (("period", "за"), ("after", "после"), ("before", "до")):
        if values.get(key):
            parts.append(f"{word} " + re.sub(rf"^(?:{word}|с|since|after|before|last)\s+", "", values[key], flags=re.I))
    if values.get("kind"):
        parts.append(values["kind"])
    if values.get("contains"):
        parts.append('"' + values["contains"].replace('"', "'") + '"')
    query = " ".join(parts)
    return [], {"query": query}, parse_clear(query).describe(guild)


def big_bet(ctx, values) -> bool:
    bet, cash = values["bet"], player_funds.get(str(ctx.author.id), 0)
    return BIG_BET_MIN <= bet <= cash and bet * 2 >= cash


BET_ASK = {"ru": "Ставка {bet}, это половина твоих наличных или больше. Играем",
           "uk": "Ставка {bet}, це половина твоєї готівки або більше. Граємо",
           "sk": "Stávka {bet} je polovica tvojej hotovosti alebo viac. Hráme",
           "en": "A bet of {bet} is half your cash or more. Play"}
MEMBER_OPT = P("member", "member", required=False)
REASON = P("reason", "text", required=False, kw="reason")
ECO, INFO, CASINO, WORK, FUN, VOICE, MOD = ("💰 Экономика", "👤 Профиль и сервер", "🎰 Казино",
                                           "💼 Работа и заработок", "🎭 Развлечения", "🎙️ Голос и ИИ",
                                           "🛡️ Модерация")
STATIONS = ("зал", "касса", "фри", "выдача", "сборка", "макавто", "гриль")
NAMES = "🏷️ Прозвища"
ALIAS = P("alias", "text", kw="alias")

ACTIONS = [
    Action("balance", "money", "свой баланс, сколько у меня денег", "сколько у меня денег", ECO),
    Action("daily", "daily", "забрать ежедневный бонус", "забери мой ежедневный бонус", ECO),
    Action("deposit", "deposit", "положить деньги в банк", "положи тысячу в банк", ECO, (P("amount", "amount"),)),
    Action("withdraw", "withdraw", "снять деньги из банка", "сними пятьсот из банка", ECO, (P("amount", "amount"),)),
    Action("pay", "pay", "перевести деньги участнику", "переведи Пете тысячу", ECO,
           (P("member", "member"), P("amount", "amount")), confirm=True,
           ask={"ru": "Перевести {amount} игроку {member}", "uk": "Переказати {amount} гравцю {member}",
                "sk": "Poslať {amount} hráčovi {member}", "en": "Send {amount} to {member}"}),
    Action("top", "top", "топ богатейших игроков", "кто самый богатый", ECO),
    Action("toplevel", "toplevel", "топ игроков по уровню", "покажи топ по уровню", ECO),
    Action("loan", "checkloan", "статус своего кредита", "что с моим кредитом", ECO),

    Action("profile", "profile", "профиль игрока: уровень, деньги, варны", "покажи профиль Юры", INFO, (MEMBER_OPT,)),
    Action("level", "level", "уровень и опыт", "какой у меня уровень", INFO, (MEMBER_OPT,)),
    Action("userinfo", "userinfo", "информация об участнике: роли, когда зашёл", "кто такой Петя", INFO, (MEMBER_OPT,)),
    Action("serverinfo", "serverinfo", "информация о сервере", "расскажи про сервер", INFO),
    Action("inventory", "inventory", "инвентарь", "что у меня в инвентаре", INFO, (MEMBER_OPT,)),
    Action("warns", "warns", "посмотреть предупреждения", "сколько варнов у Пети", INFO, (MEMBER_OPT,)),

    Action("casino", "casino", "правила казино и статистика игр", "моя статистика в казино", CASINO, (MEMBER_OPT,)),
    Action("slots", "spin", "сыграть в слоты", "крутани слоты на сотку", CASINO,
           (P("bet", "bet"),), confirm=big_bet, ask=BET_ASK),
    Action("flip", "flip", "монетка на деньги, side: heads (орёл) или tails (решка)", "ставлю двести на орла", CASINO,
           (P("bet", "bet"), P("side", "choice", required=False, choices=("heads", "tails"))),
           confirm=big_bet, ask=BET_ASK),
    Action("dice", "dice", "кубик на деньги, number: 1–6", "кубик на пятьсот, ставлю на шесть", CASINO,
           (P("bet", "bet"), P("number", "number", required=False)), confirm=big_bet, ask=BET_ASK),
    Action("roulette", "roulette", "рулетка, choice: red, black, green или число 0–36", "рулетка, тысяча на красное",
           CASINO, (P("bet", "bet"), P("choice", "choice", required=False,
                                       choices=("red", "black", "green", *map(str, range(37))))),
           confirm=big_bet, ask=BET_ASK),
    Action("blackjack", "bj", "блэкджек", "сыграем в блэкджек на тысячу", CASINO,
           (P("bet", "bet"),), confirm=big_bet, ask=BET_ASK),

    Action("warehouse", "gb", "смена на складе GymBeam, job: pick (пикинг) или pack (упаковка)",
           "начни смену на складе", WORK, (P("job", "choice", required=False, choices=("pick", "pack")),)),
    Action("mcdonalds", "mc", "смена в McDonald's, position: " + ", ".join(STATIONS), "выйди на смену в макдак",
           WORK, (P("position", "choice", required=False, kw="position", choices=STATIONS),)),
    Action("fish", "fish", "порыбачить", "пойдём на рыбалку", WORK),
    Action("crime", "crime", "пойти на преступление ради денег", "давай ограбим банк", WORK),
    Action("rob", "rob", "ограбить участника", "ограбь Петю", WORK, (P("member", "member"),), confirm=True,
           ask={"ru": "Ограбить {member}", "uk": "Пограбувати {member}", "sk": "Okradnúť {member}", "en": "Rob {member}"}),

    Action("joke", "joke", "шутка из коллекции бота", "расскажи шутку", FUN),
    Action("predict", "predict", "предсказание", "что меня ждёт", FUN),
    Action("coinflip", "coinflip", "подбросить монетку без ставки", "подбрось монетку", FUN),

    Action("join_voice", "listen", "зайти в войс к говорящему и слушать обращения «Базарчик»: зайди к нам, "
           "приходи в войс, послушай нас", "зайди к нам в войс", VOICE),
    Action("stop_listening", "stoplisten", "перестать слушать войс, уйти из войса", "хватит слушать", VOICE),
    Action("voice", "aivoice", "сменить голос озвучки, voice: male или female", "говори мужским голосом", VOICE,
           (P("voice", "choice", kw="voice_name", choices=("male", "female")),)),
    Action("forget", "aiclear", "очистить память разговора ИИ", "забудь наш разговор", VOICE),

    Action("alias_add", "alias add", "запомнить прозвище участника: «запомни, что Петруха — это Петя», «зови меня "
           "Сашка»; member — кому (не назван — себе), alias — новое прозвище", "запомни, что Петруха — это Петя",
           NAMES, (MEMBER_OPT, ALIAS)),
    Action("alias_remove", "alias remove", "забыть прозвище: «забудь, что я Сашка», «убери прозвище Петруха»; "
           "member — у кого (можно не называть), alias — какое прозвище", "убери прозвище Петруха",
           NAMES, (MEMBER_OPT, ALIAS)),
    Action("alias_show", "alias", "показать прозвища: свои («какие у меня прозвища») или участника («как ещё "
           "зовут Петю»)", "какие у меня прозвища", NAMES, (P("member", "member", required=False, kw="member"),)),
    Action("alias_list", "alias list", "показать все прозвища на сервере", "покажи все прозвища", NAMES),

    # Мут, варн, медленный режим и замок чата — обратимы, выполняются сразу (права и иерархия — как у команды).
    Action("mute", "mute", "тайм-аут (мут) участнику", "замуть Петю на 10 минут", MOD,
           (P("member", "member"), P("duration", "duration", required=False, default="10m"), REASON), hierarchy=True),
    Action("unmute", "unmute", "снять тайм-аут", "размуть Петю", MOD, (P("member", "member"), REASON)),
    Action("warn", "warn", "выдать предупреждение", "выдай Пете варн за спам", MOD, (P("member", "member"), REASON)),
    Action("slowmode", "slowmode", "медленный режим чата, delay: срок или off", "включи медленный режим 30 секунд", MOD,
           (P("delay", "delay"),)),
    Action("lock", "lock", "закрыть этот чат для сообщений", "закрой чат", MOD, (REASON,)),
    Action("unlock", "unlock", "открыть этот чат", "открой чат", MOD),
    # Кик, бан и очистка необратимы — строгое подтверждение: полная фраза («подтверждаю, забань Petya»).
    Action("kick", "kick", "выгнать с сервера", "кикни Петю", MOD, (P("member", "member"), REASON), confirm=STRICT,
           hierarchy=True,
           ask={"ru": "Выгнать {member} с сервера", "uk": "Вигнати {member} з сервера",
                "sk": "Vyhodiť {member} zo servera", "en": "Kick {member} from the server"},
           full={"ru": "подтверждаю, кикни {member}", "uk": "підтверджую, кікни {member}",
                 "sk": "potvrdzujem, vyhoď {member}", "en": "confirm, kick {member}"}),
    Action("ban", "ban", "забанить; без срока — навсегда", "забань Петю на неделю", MOD,
           (P("member", "member"), P("duration", "duration", required=False), REASON), confirm=STRICT, hierarchy=True,
           ask={"ru": "Забанить {member} {duration}", "uk": "Забанити {member} {duration}",
                "sk": "Zabanovať {member} {duration}", "en": "Ban {member} {duration}"},
           full={"ru": "подтверждаю, забань {member}", "uk": "підтверджую, забань {member}",
                 "sk": "potvrdzujem, zabanuj {member}", "en": "confirm, ban {member}"}),
    Action("clear", "clear", "удалить сообщения в этом чате; фильтры можно сочетать: amount — сколько (до 500), "
           "member — чьи, period — за какой срок (2h, 30m, 1d, сегодня, вчера), after / before — с какого / до какого "
           "момента (18.10 20:00, 12:00, вчера), kind — bots, humans, links или files, contains — текст в сообщении",
           "удали сообщения Пети за последний час", MOD,
           (P("amount", "amount", required=False), MEMBER_OPT, P("period", "raw", required=False),
            P("after", "raw", required=False), P("before", "raw", required=False),
            P("kind", "choice", required=False, choices=("bots", "humans", "links", "files")),
            P("contains", "text", required=False)), confirm=STRICT, build=lambda values, guild: clear_call(values, guild),
           ask={"ru": "Удалить сообщения: {filters}", "uk": "Видалити повідомлення: {filters}",
                "sk": "Vymazať správy: {filters}", "en": "Delete messages: {filters}"},
           full={"ru": "подтверждаю, удали сообщения", "uk": "підтверджую, видали повідомлення",
                 "sk": "potvrdzujem, vymaž správy", "en": "confirm, delete the messages"}),
]
ACTIONS_BY_KEY = {a.key: a for a in ACTIONS}


def owner_only(command: commands.Command) -> bool:
    """Owner-команды голосом не выполняются никогда — даже если их по ошибке добавят в ACTIONS."""
    return command.name in VOICE_FORBIDDEN or any(
        "is_owner" in getattr(check, "__qualname__", "") for check in command.checks)


# ── Разбор фразы ──────────────────────────────────────────────
def _catalog() -> str:
    lines = []
    for a in ACTIONS:
        params = ", ".join(p.name + ("" if p.required else "?") for p in a.params)
        lines.append(f"{a.key}({params}) — {a.hint}")
    return "\n".join(lines)


PARSE_PROMPT = (
    "Ты — модуль разбора команд Discord-бота BazarčikPM. Тебе дают фразу, сказанную боту в войсе или "
    "написанную ему в чате (обращение «Базарчик» или @упоминание уже убрано), на русском, украинском, словацком "
    "или английском; распознавание речи могло ошибиться в словах и именах. Реши, просит ли человек бота "
    "ВЫПОЛНИТЬ действие из списка "
    "или просто говорит и спрашивает.\n\n"
    "Ответь строго одним JSON-объектом, без пояснений и Markdown:\n"
    '{"action": "<ключ из списка | chat | forbidden | unsupported>", "args": {…}, "lang": "ru|uk|sk|en"}\n\n'
    "chat — вопрос, разговор, подкол, просьба рассказать, объяснить или посоветовать: всё, что не просьба "
    "выполнить действие. Сомневаешься — выбирай chat.\n"
    "forbidden — просят то, что голосом нельзя: перезагрузить модули, бэкап, статус бота, выдать или забрать "
    "деньги как админ, объявления, настройки сервера.\n"
    "unsupported — явно просят бота что-то сделать на сервере, но такого действия нет в списке.\n"
    "lang — язык фразы.\n"
    "args — только параметры выбранного действия; параметр, которого нет во фразе, не добавляй:\n"
    "member — имя участника; если похоже на кого-то из списка участников или на прозвище из списка прозвищ, "
    "напиши основное имя участника точно как в списке; сам говорящий — \"me\".\n"
    "alias — прозвище ровно как его назвали, в именительном падеже («Петруху» → \"Петруха\").\n"
    "amount — целое число (тысяча = 1000, «пять кусков» = 5000). bet — целое число, \"all\" (ва-банк) "
    "или \"half\" (половина).\n"
    "duration и delay — срок: 30s, 10m, 2h, 7d; «навсегда» = \"perm\"; delay \"off\" — выключить.\n"
    "reason — причина, если назвали. Остальные параметры — значения из описания действия.\n\n"
    "Действия:\n" + _catalog())


@dataclass
class Intent:
    action: str
    args: dict
    lang: str


def extract_json(text: str) -> Optional[dict]:
    """Первый JSON-объект в ответе ИИ — даже если вокруг него текст или ```-обёртка."""
    decoder, start = json.JSONDecoder(), (text or "").find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text[start:])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        start = text.find("{", start + 1)
    return None


def args_note(args: dict) -> str:
    """Параметры разбора для логов: member=Petya, duration=10m; причина — свободный текст — только длиной."""
    return ", ".join(f"{k}=…{len(str(v))} симв." if k == "reason" else f"{k}={v}" for k, v in args.items()) or "—"


def to_intent(raw: str, question: str) -> Intent:
    obj = extract_json(raw) or {}
    action = str(obj.get("action") or "chat").strip().lower()
    args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
    lang = str(obj.get("lang") or "").lower()
    return Intent(action, args, lang if lang in LANGS else detect_lang(question))


# ── Голосовое «да» / «нет» ────────────────────────────────────
YES_WORDS = {"да", "ага", "угу", "конечно", "подтверждаю", "давай", "делай", "выполняй", "го", "ок", "окей", "так",
             "звісно", "підтверджую", "роби", "áno", "ano", "jasné", "jasne", "potvrdzujem", "rob",
             "yes", "yeah", "yep", "sure", "confirm", "ok", "okay", "do"}
NO_WORDS = {"нет", "не", "неа", "отмена", "отмени", "стоп", "ні", "скасуй", "скасувати", "nie", "zruš", "zrus",
            "no", "nope", "cancel", "stop"}


FILLER_WORDS = {"ну", "а", "э", "ээ", "эм", "ой", "слушай", "базарчик"}
CONFIRM_STEMS = ("podtverzhd", "pidtverdzh", "potvrdz", "confirm")          # подтверждаю / підтверджую / potvrdzujem
VERB_STEMS = {"ban": ("ban",), "kick": ("kik", "kick", "vygn", "vign", "vyhod"),
              "clear": ("udal", "vidal", "ochist", "vymaz", "delet", "clear")}


def yes_no(text: str) -> Optional[bool]:
    """True — «да», False — «нет», None — непонятно. Отказ сильнее: «да нет» — это нет. «Ну да» — да."""
    words = re.findall(r"\w+", (text or "").lower())[:5]
    if any(w in NO_WORDS for w in words):
        return False
    words = [w for w in words if w not in FILLER_WORDS]
    if words and words[0] in YES_WORDS:
        return True
    return None


def strict_answer(text: str, p) -> Optional[bool]:
    """Строгое подтверждение (кик, бан, очистка): True — сказали целиком «подтверждаю, забань Petya»,
    False — отказ, None — неполно (короткое «да», без имени, без действия)."""
    raw = re.findall(r"\w+", (text or "").lower())
    if any(w in NO_WORDS for w in raw[:4]):
        return False
    words = [w for w in (norm_name(w) for w in raw) if w]
    if not any(w.startswith(CONFIRM_STEMS) for w in words):
        return None
    if not any(stem in w for w in words for stem in VERB_STEMS.get(p.action.key, ())):
        return None
    member = p.values.get("member")
    if member is not None and "{member}" in "".join(p.action.full.values()):   # у очистки участник — фильтр, не цель
        candidates = words + [a + b for a, b in zip(words, words[1:])]     # «Петя Иванов» — два слова
        if not any(name_score(w, member) >= 0.8 for w in candidates):
            return None
    return True


# ── Поиск участника — names.py (ник, имя аккаунта, прозвища из !alias, падеж, транслит) ──
class NotUnderstood(Exception):
    """Не хватает или не разобран параметр: текст сразу можно сказать человеку."""


def parse_amount(value) -> Optional[int]:
    text = str(value if value is not None else "").lower().replace(" ", "").replace(",", ".")
    mult = 1
    if text[-1:] in ("k", "к"):
        mult, text = 1_000, text[:-1]
    elif text[-1:] in ("m", "м"):
        mult, text = 1_000_000, text[:-1]
    try:
        amount = int(float(text) * mult)
    except (ValueError, OverflowError):
        return None
    return amount if amount > 0 else None


# ── Контекст команды, вызванной голосом ───────────────────────
class Snapshot:
    """Что сейчас показывает сообщение команды: текст, embed'ы и есть ли кнопки."""
    def __init__(self, content=None, embeds=(), view=None):
        self.content, self.embeds, self.has_view = content, list(embeds), view is not None

    def update(self, kw: dict):
        if "content" in kw:
            self.content = kw["content"]
        if "embed" in kw:
            self.embeds = [kw["embed"]] if kw["embed"] is not None else []
        if "embeds" in kw:
            self.embeds = list(kw["embeds"] or [])
        if "view" in kw:
            self.has_view = kw["view"] is not None


class RecordedMessage:
    """Сообщение команды: правки (анимация казино) тоже запоминаются — озвучиваем итог, а не первый кадр."""
    def __init__(self, message, snapshot: Snapshot):
        self._message, self._snapshot = message, snapshot

    def __getattr__(self, name):
        return getattr(self._message, name)

    async def edit(self, *args, **kw):
        if args:
            kw["content"] = args[0]
        self._snapshot.update(kw)
        return await self._message.edit(**kw)


class RecordingChannel:
    """Канал, который запоминает всё, что в него отправила команда, — из этого собирается голосовой итог."""
    def __init__(self, channel):
        self._channel = getattr(channel, "_channel", channel)   # без матрёшки из обёрток
        self.sent: list = []
        self.closed = False                # команда отработала — дальше ничего не копим (сессии !listen живут долго)

    def __getattr__(self, name):
        return getattr(self._channel, name)

    def __eq__(self, other):
        return self._channel == getattr(other, "_channel", other)

    def __hash__(self):
        return hash(self._channel)

    async def send(self, content=None, **kw):
        message = await self._channel.send(content, **kw)
        if self.closed or message is None:
            return message
        snapshot = Snapshot(content, [kw["embed"]] if kw.get("embed") else kw.get("embeds") or (), kw.get("view"))
        self.sent.append(snapshot)
        return RecordedMessage(message, snapshot)


class VoiceMessage:
    """Заменитель discord.Message: команды берут из него автора, сервер и канал."""
    def __init__(self, bot, author, channel):
        self._state = bot._connection
        self.author, self.channel, self.guild = author, channel, channel.guild
        self.id, self.content, self.created_at = 0, "", utcnow()
        self.mentions, self.role_mentions, self.channel_mentions, self.attachments = [], [], [], []
        self.reference = None

    async def delete(self, *args, **kw):
        pass

    async def add_reaction(self, *args, **kw):
        pass


class VoiceContext(commands.Context):
    """Контекст «как будто человек набрал команду в этом чате»: ответы команды идут в чат и в запись."""
    async def send(self, content=None, **kw):
        return await self.channel.send(content, **kw)

    async def reply(self, content=None, **kw):
        kw.pop("mention_author", None)
        return await self.send(content, **kw)


def make_context(bot, user, channel, command) -> VoiceContext:
    message = VoiceMessage(bot, user, RecordingChannel(channel))
    return VoiceContext(message=message, bot=bot, view=StringView(""), prefix="!",
                        command=command, invoked_with=command.name)


# ── Итог команды для озвучки ──────────────────────────────────
MENTION_RE = re.compile(r"<(@!?|@&|#)(\d+)>")


def plain_text(snapshots, guild) -> str:
    """Сообщения команды → простой текст: без Markdown, эмодзи и <@упоминаний>."""
    parts = []
    for s in snapshots:
        if s.content:
            parts.append(str(s.content))
        for e in s.embeds:
            parts += [x for x in (e.title, e.description) if x]
            parts += [f"{f.name}: {f.value}" for f in e.fields]
        if s.has_view:
            parts.append("(в сообщении есть кнопки)")

    def mention(m):
        kind, oid = m.group(1), int(m.group(2))
        obj = guild.get_channel(oid) if kind == "#" else guild.get_role(oid) if kind == "@&" else guild.get_member(oid)
        return getattr(obj, "display_name", None) or getattr(obj, "name", None) or "участник"

    text = MENTION_RE.sub(mention, "\n".join(parts))
    text = re.sub(r"<a?:\w+:\d+>|<t:\d+(?::\w)?>|https?://\S+", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"[*_`~|#>]+", "", text)
    text = "".join(c for c in text if unicodedata.category(c) != "So" and c not in "\ufe0f\u200d\u20e3")
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*", "\n", text)).strip()


SUMMARY_PROMPT = (
    "Ты — голосовой помощник BazarčikPM Bot. По просьбе человека ты только что выполнил команду бота. "
    "Перескажи её результат одной-двумя короткими фразами, как живой человек в войсе, на языке «{lang}» "
    "(ru — русский, uk — украинский, sk — словацкий, en — английский). О себе — в первом лице, к человеку — "
    "на ты. Только факты из результата, ничего не выдумывай; если команда отказала — скажи почему. "
    "Числа пиши цифрами, без Markdown, эмодзи и скобок.")


# ── Ожидающее подтверждение ───────────────────────────────────
@dataclass
class Pending:
    user: object
    channel: object
    vc: object
    action: Action
    values: dict
    shown: str                          # команда как в чате: !mute @Petya 10м
    question: str
    source: str
    lang: str
    message: object = None
    view: object = None
    done: bool = False
    trace: str = ""                     # та же команда для логов — свободный текст только длиной
    created: float = field(default_factory=time.monotonic)
    answers: int = 0                    # сколько непонятных ответов было, пока ждали «да»
    ready: bool = True                  # False — бот ещё договаривает вопрос, отвечать рано
    window: int = CONFIRM_SEC
    deadline: float = 0.0

    @property
    def age(self) -> float:
        return time.monotonic() - self.created

    @property
    def strict(self) -> bool:
        return self.action.confirm == STRICT

    @property
    def phrase(self) -> str:
        """Что сказать целиком для строгого подтверждения: «подтверждаю, забань Petya»."""
        full = self.action.full
        return (full.get(self.lang) or full.get("ru", "")).format(**self.values["_spoken"])

    @property
    def what(self) -> str:
        """Вопрос-подтверждение на языке говорящего: «Дать тайм-аут Petya на 10 минут»."""
        return (self.action.ask.get(self.lang) or self.action.ask["ru"]).format(**self.values["_spoken"])


class ConfirmView(OwnedView):
    deny_text = "Подтвердить может только тот, кто дал команду."

    def __init__(self, cog, pending: Pending):
        super().__init__(pending.user, timeout=pending.window)
        self.cog, self.pending = cog, pending
        self.btn("Подтверждаю" if pending.strict else "Да, выполнить", self.on_yes, GREEN, emoji="✅")
        self.btn("Отмена", self.on_no, RED, emoji="✖️")

    async def on_yes(self, interaction):
        await self.cog.resolve(self.pending, True, interaction)

    async def on_no(self, interaction):
        await self.cog.resolve(self.pending, False, interaction)

    async def on_timeout(self):
        await self.cog.expire(self.pending)


def confirm_embed(p: Pending, status: str = None) -> discord.Embed:
    title = "🔐 Подтверди полной фразой" if p.strict else "🔐 Подтверди команду"
    e = discord.Embed(title=title, color=discord.Color.red() if p.strict else discord.Color.orange(),
                      description=f"{p.what}?\n`{p.shown}`")
    e.set_author(name=f"{p.user.display_name}: {p.question}"[:256], icon_url=p.user.display_avatar.url)
    if status:
        e.add_field(name="Итог", value=status, inline=False)
        e.color = discord.Color.dark_grey()
    elif p.strict:
        e.add_field(name="Чтобы подтвердить, скажи или напиши (@бот …) целиком", value=f"«{p.phrase}»", inline=False)
        e.set_footer(text=f"Короткое «да» не подходит • {p.window} сек • только {p.user.display_name}")
    else:
        e.set_footer(text=f"Ответь «да» голосом или в чат, или нажми кнопку • {p.window} сек • "
                          f"только {p.user.display_name}")
    return e


class JarvisCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pending: dict = {}                    # (guild_id, user_id) → Pending
        self.busy: set = set()                     # кому сейчас отвечаем в чате — второй запрос не запускаем
        self._locks = defaultdict(asyncio.Lock)

    # ── Вход из voice_listen ──────────────────────────────────
    async def handle(self, channel, user, question: str, vc=None, source: str = "") -> bool:
        """True — фраза была командой (и уже обработана), False — пусть отвечает обычный ИИ."""
        pending = self.pending.get((channel.guild.id, user.id))
        if pending is not None and not pending.done:
            if not pending.ready:
                print(f"[jarvis] {user.display_name}: фраза пришла, пока бот задаёт вопрос, — пропускаю")
                return True
            answer = strict_answer(question, pending) if pending.strict else yes_no(question)
            if answer is None:
                pending.answers += 1
                print(f"[jarvis] {user.display_name}: ответ на подтверждение "
                      f"{'неполный' if pending.strict else 'непонятен'} (слов: {len(question.split())}, "
                      f"{pending.answers}-й, прошло {pending.age:.0f} из {pending.window} с)"
                      + (" — подсказываю" if pending.answers == 1 else " — молча жду дальше"))
                if pending.answers == 1:            # подсказываем один раз, дальше не тратим голос и запросы
                    hint = (tr("say_full", pending.lang, phrase=pending.phrase) if pending.strict
                            else tr("yes_no", pending.lang))
                    await self.tell(channel, user, question, vc, source, hint, remember=False)
                self.await_answer(pending)
            else:
                await self.resolve(pending, answer)
            return True
        started = time.monotonic()
        try:
            intent = await self.parse(channel.guild, user, question, vc)
        except ai.AIError as e:
            print(f"[jarvis] {user.display_name}: разбор фразы не удался ({e}) — отвечает обычный ИИ")
            return False
        took = time.monotonic() - started
        if intent.action == "chat":
            print(f"[jarvis] {user.display_name} → обычный вопрос [{intent.lang}], разбор {took:.1f} с")
            return False
        print(f"[jarvis] {user.display_name} → {intent.action} ({args_note(intent.args)}) [{intent.lang}], "
              f"разбор {took:.1f} с")
        try:
            await self.execute(channel, user, question, vc, source, intent)
        except Exception as e:
            print(f"[jarvis] Ошибка голосовой команды {intent.action}: {e!r}")
            await self.tell(channel, user, question, vc, source, tr("failed", intent.lang))
        return True

    async def parse(self, guild, user, question: str, vc) -> Intent:
        voice_names = [m.display_name for m in self.voice_members(vc)][:25]
        context = ""
        voice_cog = self.bot.get_cog("VoiceAICog")
        if voice_cog is not None:
            recent = voice_cog.recent(guild.id, 4)
            if recent:
                context = "Последние реплики (для контекста):\n" + "\n".join(
                    f"{m['role']}: {m['content'][:200]}" for m in recent) + "\n"
        known = []                                  # прозвища из !alias — чтобы «замуть Петруху» нашёл Petya
        for uid, found in list(all_aliases(guild.id).items())[:40]:
            member = guild.get_member(uid)
            if member is not None:
                known.append(f"{member.display_name} — {', '.join(found[:6])}")
        prompt = (f"{context}Говорит: {user.display_name}\n"
                  f"Участники в войсе: {', '.join(voice_names) or '—'}\n"
                  + (f"Прозвища участников: {'; '.join(known)}\n" if known else "")
                  + f"Фраза: {question}")
        raw = await ai.ask(PARSE_PROMPT, prompt, max_tokens=400, temperature=0)
        if extract_json(raw) is None:
            print(f"[jarvis] {user.display_name}: разбор вернул не JSON ({len(raw)} симв.) — считаю обычным вопросом")
        return to_intent(raw, question)

    @staticmethod
    def voice_members(vc) -> list:
        channel = getattr(vc, "channel", None) if vc is not None else None
        return [m for m in getattr(channel, "members", []) if not m.bot]

    # ── Выполнение ────────────────────────────────────────────
    async def execute(self, channel, user, question, vc, source, intent: Intent):
        lang = intent.lang

        async def refuse(why: str, text: str):
            print(f"[jarvis] {user.display_name}: {intent.action} не выполнено — {why}")
            await self.tell(channel, user, question, vc, source, text)
        if intent.action == "forbidden" or intent.action in VOICE_FORBIDDEN:
            return await refuse("голосом запрещено", tr("forbidden", lang))
        action = ACTIONS_BY_KEY.get(intent.action)
        command = self.command_for(action, channel.guild)
        if command is None:
            return await refuse("нет в белом списке или модуль не загружен", tr("unsupported", lang))
        if owner_only(command):
            return await refuse(f"!{command.qualified_name} — owner-команда", tr("forbidden", lang))
        ctx = make_context(self.bot, user, channel, command)
        if (denied := await self.check_rights(ctx, command, lang)) is not None:
            return await refuse(f"проверка прав !{command.qualified_name} не пройдена", denied)
        try:
            values = await self.convert(ctx, action, intent.args, lang, vc)
        except NotUnderstood as e:
            return await refuse(f"не разобраны параметры ({args_note(intent.args)})", str(e))
        if action.hierarchy:
            from cogs.moderation import hierarchy_error
            if err := hierarchy_error(ctx, values["member"]):
                return await refuse(f"иерархия ролей: {err}", err)
        pending = Pending(user, channel, vc, action, values, self.shown(command, action, values),
                          question, source, lang, trace=self.shown(command, action, values, redact=True))
        needs = action.confirm(ctx, values) if callable(action.confirm) else action.confirm
        if needs:
            return await self.ask_confirm(pending)
        await self.run(pending)

    def command_for(self, action: Optional[Action], guild):
        if action is None:
            return None
        name = action.command
        listen = self.bot.get_cog("VoiceListenCog")
        if action.key == "stop_listening" and not (listen is not None and listen.is_listening(guild.id)):
            name = "leave"                         # не слушаем, а просто сидим в войсе — выходим
        return self.bot.get_command(name)

    @staticmethod
    async def check_rights(ctx, command, lang) -> Optional[str]:
        """Те же проверки, что у текстовой команды: права на сервере, cog_check, глобальные проверки."""
        try:
            if await command.can_run(ctx):
                return None
            print(f"[jarvis] {ctx.author.display_name}: !{command.qualified_name} — проверка вернула «нельзя»")
        except commands.NotOwner:
            print(f"[jarvis] {ctx.author.display_name}: !{command.qualified_name} — только для владельца бота")
            return tr("forbidden", lang)
        except (commands.BotMissingPermissions, commands.BotMissingRole) as e:
            print(f"[jarvis] {ctx.author.display_name}: !{command.qualified_name} — у бота не хватает прав: {e}")
            return tr("bot_rights", lang)
        except commands.CommandError as e:
            print(f"[jarvis] {ctx.author.display_name}: !{command.qualified_name} — {type(e).__name__}: {e}")
        return tr("no_rights", lang)

    async def convert(self, ctx, action: Action, args: dict, lang: str, vc) -> dict:
        """Аргументы от ИИ → значения для команды. ИИ не доверяем: всё проверяется заново."""
        values, spoken = {}, {}
        for p in action.params:
            raw = args.get(p.name)
            if raw is None or str(raw).strip().lower() in ("", "null", "none"):
                raw = p.default
            what = MISSING_WHAT.get(p.name) or MISSING_WHAT.get(p.kind) or MISSING_WHAT["choice"]
            missing = NotUnderstood(tr("missing", lang, what=what[lang]))
            if raw is None:
                if p.required:
                    raise missing
                values[p.name] = None
                spoken[p.name] = tr("permanent", lang) if p.kind == "duration" else ""
                continue
            text = str(raw).strip()
            if p.kind == "member":
                try:
                    member = find_member(ctx.guild, text, ctx.author, self.voice_members(vc))
                except LookupError:
                    raise NotUnderstood(tr("not_found", lang, name=text))
                except ValueError as e:
                    raise NotUnderstood(tr("ambiguous", lang, name=str(e)))
                values[p.name], spoken[p.name] = member, member.display_name
            elif p.kind == "amount":
                amount = parse_amount(text)
                if amount is None:
                    raise missing
                values[p.name] = amount
                spoken[p.name] = plural(amount, "msg", lang) if action.key == "clear" else str(amount)
            elif p.kind == "bet":
                from cogs.games import Bet
                try:
                    bet = await Bet().convert(ctx, text)
                except commands.BadArgument:
                    raise missing
                values[p.name], spoken[p.name] = bet, str(bet)
            elif p.kind == "duration":
                if text.lower() in ("perm", "permanent", "forever", "навсегда", "0"):
                    values[p.name], spoken[p.name] = None, tr("permanent", lang)
                    continue
                td = parse_duration(text, "m")
                if td is None:
                    raise missing
                values[p.name], spoken[p.name] = td, tr("for", lang, d=spoken_duration(td, lang))
            elif p.kind == "delay":
                if text.lower() in ("off", "0", "выкл"):
                    values[p.name], spoken[p.name] = timedelta(0), tr("slow_off", lang)
                    continue
                td = parse_duration(text, "s")
                if td is None or td.total_seconds() > 21600:
                    raise missing
                values[p.name], spoken[p.name] = td, tr("slow_on", lang, d=spoken_duration(td, lang))
            elif p.kind == "number":
                try:
                    number = int(float(text))
                except ValueError:
                    raise missing
                if not 1 <= number <= 6:
                    raise missing
                values[p.name], spoken[p.name] = number, str(number)
            elif p.kind == "choice":
                if text.lower() not in p.choices:
                    raise missing
                values[p.name] = spoken[p.name] = text.lower()
            else:
                values[p.name] = spoken[p.name] = text[:200]
        if action.build is not None:                # своя сборка вызова — и её проверка до подтверждения
            try:
                values["_call"] = action.build(values, ctx.guild)
            except ValueError as e:
                raise NotUnderstood(tr("bad_filter", lang, why=e))
            spoken["filters"] = values["_call"][2]
        values["_spoken"] = spoken
        return values

    @staticmethod
    def call_args(action: Action, values: dict):
        """Значения → аргументы настоящей команды — в том же виде, что набрал бы человек."""
        if "_call" in values:
            return values["_call"][0], values["_call"][1]
        args, kwargs = [], {}
        for p in action.params:
            v = values.get(p.name)
            if isinstance(v, timedelta):
                v = f"{int(v.total_seconds())}s" if v else "off"
            elif p.name == "side" and v:
                v = "о" if v == "heads" else "р"
            elif p.name == "voice" and v:
                lang = next((code for code, pair in TTS_VOICES.items() if TTS_SETTINGS["voice"] in pair), "ru")
                v = TTS_VOICES[lang][1 if v == "male" else 0]
            if p.kw:
                if v is not None:
                    kwargs[p.kw] = v
            else:
                args.append(v)
        if action.group == MOD and any(p.kw == "reason" for p in action.params):
            kwargs.setdefault("reason", "Голосовая команда")
        return args, kwargs

    @staticmethod
    def shown(command, action: Action, values: dict, redact: bool = False) -> str:
        """Команда как в чате: !mute @Petya 10м «за спам». redact — для логов: свободный текст только длиной."""
        parts = [f"!{command.qualified_name}"]
        for p in action.params:
            v = values.get(p.name)
            if v is None:
                continue
            if isinstance(v, timedelta):
                parts.append(fmt_duration(v) if v else "off")
            elif hasattr(v, "display_name"):
                parts.append(f"@{v.display_name}")
            elif p.kind == "text":
                parts.append(f"«…{len(v)} симв.»" if redact else f"«{v}»")
            else:
                parts.append(str(v))
        return " ".join(parts)

    async def run(self, p: Pending):
        """Выполняет команду от имени говорящего и озвучивает итог. Права проверяются ещё раз."""
        reply = lambda text, **kw: self.tell(p.channel, p.user, p.question, p.vc, p.source, text, **kw)  # noqa: E731
        command = self.command_for(p.action, p.channel.guild)
        if command is None or owner_only(command):
            print(f"[jarvis] {p.user.display_name}: {p.trace} не выполнено — команды нет или она owner-only")
            return await reply(tr("unsupported", p.lang))
        ctx = make_context(self.bot, p.user, p.channel, command)
        if (denied := await self.check_rights(ctx, command, p.lang)) is not None:
            print(f"[jarvis] {p.user.display_name}: {p.trace} не выполнено — права пропали перед выполнением")
            return await reply(denied)
        args, kwargs = self.call_args(p.action, p.values)
        bye = p.action.key == "stop_listening" and self.speaking(p.vc)
        if bye:                                    # прощаемся до выхода: после него голоса уже не будет
            await self.speak(p.vc, tr("bye", p.lang))
            await self.wait_playback(p.vc)
        failure, started = None, time.monotonic()
        try:
            await ctx.invoke(command, *args, **kwargs)
        except discord.Forbidden as e:
            print(f"[jarvis] {p.user.display_name}: {p.trace} — Discord не дал прав боту: {e}")
            failure = tr("bot_rights", p.lang)
        except Exception as e:
            print(f"[jarvis] {p.user.display_name}: {p.trace} — команда упала: {e!r}")
            failure = tr("failed", p.lang)
        ctx.channel.closed = True
        print(f"[jarvis] {p.user.display_name}: {p.trace} — {'ошибка' if failure else 'выполнено'} за "
              f"{time.monotonic() - started:.1f} с, сообщений в чат {len(ctx.channel.sent)}")
        footer = f"!{command.qualified_name}"
        if failure:
            return await reply(failure, footer=footer)
        if bye:
            return await reply(tr("bye", p.lang), footer=footer, speak_text=None)
        if not self.speaking(p.vc):
            if ctx.channel.sent:            # команда сама всё показала в чате — не дублируем её итог
                return self.remember(p, f"Выполнил {p.shown}")
            return await reply(f"✅ Выполнил `{p.shown}`", footer=footer, speak_text=None)
        await reply(await self.summarize(p, plain_text(ctx.channel.sent, p.channel.guild)), footer=footer)

    async def summarize(self, p: Pending, result: str) -> str:
        if not result:
            return tr("done", p.lang)
        prompt = (f"Просьба [{p.user.display_name}]: {p.question}\nКоманда: {p.shown}\n"
                  f"Результат в чате:\n{result[:1500]}")
        started = time.monotonic()
        try:
            text = await ai.ask(SUMMARY_PROMPT.format(lang=p.lang), prompt, max_tokens=300, temperature=0.4)
        except ai.AIError as e:
            print(f"[jarvis] {p.user.display_name}: пересказ итога не удался ({e}) — озвучиваю результат как есть")
            return result[:300]
        print(f"[jarvis] {p.user.display_name}: пересказ итога за {time.monotonic() - started:.1f} с, "
              f"{len(text)} символов")
        return text

    def remember(self, p: Pending, text: str):
        voice_cog = self.bot.get_cog("VoiceAICog")
        if voice_cog is not None:
            voice_cog.remember(p.channel.guild.id, p.user.display_name, p.question, text)

    # ── Подтверждение ─────────────────────────────────────────
    async def ask_confirm(self, p: Pending):
        """Сначала бот полностью озвучивает вопрос, потом создаёт форму в чате — и только с этого момента
        идёт окно на ответ (CONFIRM_SEC, для кика/бана/очистки — STRICT_SEC и полная фраза)."""
        key = (p.channel.guild.id, p.user.id)
        old = self.pending.get(key)
        if old is not None and self.take(old):
            print(f"[jarvis] {old.user.display_name}: {old.trace} — заменено новой командой через {old.age:.0f} с")
            await self.close_confirm(old, "✖️ Заменено новой командой")
        p.window, p.ready = (STRICT_SEC if p.strict else CONFIRM_SEC), False
        self.pending[key] = p
        if self.speaking(p.vc):
            started = time.monotonic()
            prompt = (tr("confirm_strict", p.lang, what=p.what, phrase=p.phrase) if p.strict
                      else tr("confirm", p.lang, what=p.what))
            await self.speak(p.vc, prompt)
            await self.wait_playback(p.vc, limit=40)
            print(f"[jarvis] {p.user.display_name}: вопрос о подтверждении договорён за {time.monotonic() - started:.1f} с")
        if p.done:                                 # пока бот говорил, команду заменили новой
            return
        p.view = ConfirmView(self, p)
        p.message = await p.channel.send(embed=confirm_embed(p), view=p.view)
        p.created = time.monotonic()
        p.deadline, p.ready = p.created + p.window, True
        self.await_answer(p)
        print(f"[jarvis] {p.user.display_name}: жду подтверждения {p.trace} ({p.window} с"
              + (", нужна полная фраза)" if p.strict else ")"))

    def session(self, guild):
        listen = self.bot.get_cog("VoiceListenCog")
        return getattr(listen, "sessions", {}).get(guild.id) if listen is not None else None

    def await_answer(self, p: Pending):
        """Ответ автора в войсе дойдёт до бота без «Базарчик» — но только до конца окна. В строгом окне
        короткие фразы (обычное «да») даже не распознаются: так меньше лишних запросов к Whisper."""
        session = self.session(p.channel.guild)
        if session is not None:
            session.followup[p.user.id] = p.deadline
            if p.strict:
                session.min_phrase[p.user.id] = STRICT_MIN_SEC

    def close_answer(self, p: Pending):
        """Подтверждение решено или истекло — следующая фраза снова нужна с «Базарчик»."""
        session = self.session(p.channel.guild)
        if session is not None:
            session.followup.pop(p.user.id, None)
            session.min_phrase.pop(p.user.id, None)

    def take(self, p: Pending) -> bool:
        """Подтверждение срабатывает один раз: голос, кнопка и тайм-аут не выполнят команду дважды."""
        if p.done:
            return False
        p.done = True
        key = (p.channel.guild.id, p.user.id)
        if self.pending.get(key) is p:
            del self.pending[key]
        if p.view is not None:
            p.view.stop()
        self.close_answer(p)
        return True

    async def resolve(self, p: Pending, yes: bool, interaction=None):
        if not self.take(p):
            if interaction is not None and not interaction.response.is_done():
                await interaction.response.send_message("Уже решено.", ephemeral=True)
            return
        how = ("кнопкой" if interaction is not None else "голосом" if p.source.startswith(("🎙", "🎤"))
               else "в чате")
        status = f"✅ Подтверждено {how}" if yes else f"✖️ Отменено {how}"
        print(f"[jarvis] {p.user.display_name}: {p.trace} — {'подтверждено' if yes else 'отменено'} {how} "
              f"через {p.age:.1f} с, непонятных ответов {p.answers}")
        if interaction is None:                    # голос: мы уже внутри очереди ответов войса
            await self.close_confirm(p, status)
            return await self.finish(p, yes)
        await interaction.response.edit_message(embed=confirm_embed(p, status), view=None)
        async with self.lock(p.channel.guild.id):
            await self.finish(p, yes)

    async def finish(self, p: Pending, yes: bool):
        if yes:
            await self.run(p)
        else:
            await self.speak(p.vc, tr("cancelled", p.lang))

    async def expire(self, p: Pending):
        if self.take(p):
            print(f"[jarvis] {p.user.display_name}: {p.trace} — подтверждение истекло через {p.age:.0f} с, "
                  f"непонятных ответов {p.answers}")
            await self.close_confirm(p, f"⌛ Не подтвердили за {p.window} сек — отменено")

    @staticmethod
    async def close_confirm(p: Pending, status: str):
        if p.message is None:
            return
        try:
            await p.message.edit(embed=confirm_embed(p, status), view=None)
        except discord.HTTPException:
            pass

    def lock(self, guild_id: int) -> asyncio.Lock:
        """Общая очередь с ответами прослушивания: бот не говорит две фразы одновременно."""
        listen = self.bot.get_cog("VoiceListenCog")
        return listen.locks[guild_id] if listen is not None else self._locks[guild_id]

    # ── Ответ голосом и в чат ─────────────────────────────────
    @staticmethod
    def speaking(vc) -> bool:
        return vc is not None and vc.is_connected()

    async def speak(self, vc, text: Optional[str]):
        if not text or not self.speaking(vc):
            return
        try:
            await say(vc, text)
        except Exception as e:
            print(f"[jarvis] Озвучка не удалась: {e!r}")

    @staticmethod
    async def wait_playback(vc, limit: float = 8):
        for _ in range(int(limit / 0.25)):
            if not JarvisCog.speaking(vc) or not vc.is_playing():
                return
            await asyncio.sleep(0.25)

    async def tell(self, channel, user, question, vc, source, text, footer: str = "", speak_text=..., remember=True):
        """Ответ Джарвиса: embed в чат и та же фраза голосом (speak_text=None — без голоса)."""
        embed = answer_embed(user, question, text)
        embed.set_footer(text=" • ".join(x for x in (source, "🤖 Джарвис", footer) if x))
        try:
            await channel.send(embed=embed)
        except discord.HTTPException as e:
            print(f"[jarvis] Не удалось написать в чат: {e!r}")
        await self.speak(vc, text if speak_text is ... else speak_text)
        voice_cog = self.bot.get_cog("VoiceAICog")
        if remember and voice_cog is not None:
            voice_cog.remember(channel.guild.id, user.display_name, question, text)

    # ── Обращение в чате: @BazarčikPM … ───────────────────────
    def addressed(self, message) -> Optional[str]:
        """Текст обращения без упоминания; None — сообщение не боту. Обращение — это упоминание бота
        или его роли (её часто выбирают из подсказки Discord) и ответ на сообщение бота с пингом."""
        me = self.bot.user
        if me is None:
            return None
        roles = [r for r in getattr(message, "role_mentions", []) if getattr(r.tags, "bot_id", None) == me.id]
        if not any(m.id == me.id for m in message.mentions) and not roles:
            return None
        text = re.sub(rf"<@!?{me.id}>", " ", message.content or "")
        for role in roles:
            text = text.replace(f"<@&{role.id}>", " ")
        return " ".join(text.split())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """В чате к боту обращаются только упоминанием: «@BazarčikPM сколько у меня денег»,
        «@BazarčikPM зайди к нам в войс». Что это — команда или вопрос, решает Джарвис."""
        if message.author.bot or message.guild is None or message.flags.is_voice_message:
            return
        prefix = self.bot.command_prefix if isinstance(self.bot.command_prefix, str) else "!"
        if (message.content or "").lstrip().startswith(prefix):
            return                                 # обычная команда — её обработает бот
        question = self.addressed(message)
        if question is not None:
            await self.text_request(message.channel, message.author, question)

    async def text_request(self, channel, user, question: str, source: str = "💬 чат"):
        """Обращение в чате → тот же путь, что у войса: Джарвис, а если это вопрос — ответ ИИ.
        Если бот сидит в войсе вместе с автором, ответ ещё и озвучивается."""
        me = self.bot.user
        if not question:
            await channel.send(f"{user.mention}, да? Напиши после упоминания вопрос или просьбу: "
                               f"`@{me.display_name} сколько у меня денег`, `@{me.display_name} зайди к нам в войс`. "
                               "Что я умею — `!jarvis`.", delete_after=20)
            return
        key = (channel.guild.id, user.id)
        if key in self.busy:
            print(f"[jarvis] {user.display_name}: обращение в чате пропущено — ещё отвечаю на прошлое")
            return
        self.busy.add(key)
        try:
            vc, voice = channel.guild.voice_client, getattr(user, "voice", None)
            together = (vc is not None and vc.is_connected() and voice is not None and voice.channel == vc.channel)
            print(f"[jarvis] {user.display_name}: обращение в чате (слов: {len(question.split())})"
                  + (", бот в войсе с автором — ответ ещё и голосом" if together else ""))
            hint = f"@{me.display_name} … — чтобы спросить"
            listen = self.bot.get_cog("VoiceListenCog")
            async with channel.typing():
                if listen is not None:
                    await listen.reply(channel, user, question, vc if together else None, source, hint)
                elif not await self.handle(channel, user, question, None, source):
                    await self.plain_answer(channel, user, question, source, hint)
        finally:
            self.busy.discard(key)

    async def plain_answer(self, channel, user, question, source, hint):
        """Обычный ответ ИИ, если модуль прослушивания не загрузился (нет голосовых зависимостей)."""
        voice_cog = self.bot.get_cog("VoiceAICog")
        if voice_cog is None:
            return
        try:
            text = await voice_cog.answer(channel.guild.id, user.display_name, question)
        except ai.AIError as e:
            await channel.send(f"❌ {e}", delete_after=15)
            return
        embed = answer_embed(user, question, text)
        embed.set_footer(text=f"{source} • {hint}")
        await channel.send(embed=embed)

    # ── !jarvis ───────────────────────────────────────────────
    @commands.command(name="jarvis", aliases=["джарвис"], brief="Что бот умеет по просьбе: голосом или через @")
    async def jarvis(self, ctx):
        me = self.bot.user.display_name if self.bot.user else "BazarčikPM"
        e = discord.Embed(title="🤖 Джарвис: команды словами", color=discord.Color.teal(), description=(
            f"Напиши в чат **@{me} …** или скажи в войсе (`!listen`) / голосовым сообщением **«Базарчик, …»** — "
            "бот сам поймёт: выполнить команду от твоего имени или ответить на вопрос.\n"
            f"🔐 — после «да» (голосом, `@{me} да` или кнопкой, {CONFIRM_SEC} сек).\n"
            f"🔐🔐 — кик, бан, очистка: бот договаривает вопрос, создаёт форму, и {STRICT_SEC} сек ждёт полную "
            "фразу вроде «подтверждаю, забань Petya» (короткое «да» не подходит) или кнопку.\n"
            "Мут, варн, медленный режим и замок чата — сразу. Права те же, что у текстовых команд; "
            "owner-команды (`!reload`, `!backup`, `!botstatus`) так не выполняются."))
        groups: dict = {}
        for a in ACTIONS:
            mark = (" 🔐🔐" if a.confirm == STRICT else " 🔐" if a.confirm is True else " 🔐 крупная" if a.confirm
                    else "")
            groups.setdefault(a.group, []).append(f"«{a.example}» → `!{a.command}`{mark}")
        for name, lines in groups.items():
            e.add_field(name=name, value="\n".join(lines)[:1024], inline=False)
        await ctx.send(embed=e)


def setup(bot):
    bot.add_cog(JarvisCog(bot))
