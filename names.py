"""
names.py — как бот узнаёт людей по имени: нормализация имён и прозвища, привязанные к ID участника.

Прозвища хранятся по серверам в user_aliases.json: {"guild_id": {"user_id": ["Петя", "Петруха"]}}.
Образец с правилами — user_aliases.example.json; правленный руками файл проверяет check_aliases() при запуске.
На одном сервере прозвище принадлежит одному человеку. Сравниваются имена без регистра, диакритики
и алфавита («Петруха» = «Petrukha»), а stem() убирает падежное окончание («Петруху» = «Петруха»).
Кто и как может менять прозвища — в cogs/aliases.py.
"""
import difflib
import re
import unicodedata
from discord.ext import commands
from data import user_aliases, save_aliases

MAX_ALIASES = 15            # прозвищ на человека (администраторам лимит не мешает)
ALIAS_LEN   = (2, 32)

TRANSLIT = dict(zip("абвгґдеёєжзиіїйклмнопрстуфхцчшщъыьэюя",
                    ["a", "b", "v", "g", "g", "d", "e", "e", "e", "zh", "z", "i", "i", "i", "y", "k", "l", "m", "n",
                     "o", "p", "r", "s", "t", "u", "f", "h", "c", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))
SELF_WORDS = {"me", "я", "мне", "меня", "себя", "себе", "мене", "мені", "собі", "ja", "mňa", "mna", "mne", "seba",
              "myself", "self"}


def norm_name(text: str) -> str:
    """Имя без регистра, диакритики, эмодзи и алфавита: «Петя» и «Petya» сравниваются одинаково."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(TRANSLIT.get(c, c) for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-z0-9]", "", text)
    for a, b in (("kh", "h"), ("ts", "c"), ("j", "y"), ("w", "v"), ("ck", "k"), ("ph", "f"), ("x", "ks"), ("q", "k")):
        text = text.replace(a, b)
    return text


def stem(name: str) -> str:
    """Нормализованное имя без падежного окончания: «petruhu», «petruha» → «petruh»; «petyu» → «pety»."""
    return name[:-1] if len(name) > 4 and name[-1] in "aeiouy" else name


# ── Прозвища ──────────────────────────────────────────────────
def _guild(guild_id) -> dict:
    users = user_aliases.get(str(guild_id), {})
    return users if isinstance(users, dict) else {}      # «_комментарий» в файле — не сервер


def aliases_of(guild_id, user_id) -> list:
    return list(_guild(guild_id).get(str(user_id), []))


def all_aliases(guild_id) -> dict:
    """{user_id: [прозвища]} для сервера."""
    return {int(uid): list(names) for uid, names in _guild(guild_id).items() if names}


def same_alias(a: str, b: str) -> bool:
    """Одно и то же прозвище с точностью до регистра, алфавита и падежа: «Петруху» = «Петруха»."""
    x, y = norm_name(a), norm_name(b)
    return bool(x) and (x == y or stem(x) == stem(y))


def alias_owner(guild_id, alias: str):
    """ID того, у кого на сервере уже есть такое прозвище, или None. Сначала точное совпадение, потом с падежом."""
    for same in (lambda n: norm_name(n) == norm_name(alias), lambda n: same_alias(n, alias)):
        for uid, names in _guild(guild_id).items():
            if any(same(n) for n in names):
                return int(uid)
    return None


def stored_alias(guild_id, user_id, alias: str):
    """Прозвище в том виде, как оно сохранено («Петруху» → «Петруха»), или None."""
    return next((n for n in aliases_of(guild_id, user_id) if same_alias(n, alias)), None)


def add_alias(guild_id, user_id, alias: str):
    """Добавляет прозвище. Если оно было у другого — забирает и возвращает его ID (решают проверки в cogs/aliases.py)."""
    previous = alias_owner(guild_id, alias)
    if previous is not None and previous != int(user_id):
        remove_alias(guild_id, previous, alias, save=False)
    names = user_aliases.setdefault(str(guild_id), {}).setdefault(str(user_id), [])
    if not any(same_alias(n, alias) for n in names):
        names.append(alias)
    save_aliases()
    return previous if previous != int(user_id) else None


def remove_alias(guild_id, user_id, alias: str, save: bool = True) -> bool:
    names = user_aliases.get(str(guild_id), {}).get(str(user_id), [])
    keep = [n for n in names if not same_alias(n, alias)]
    if len(keep) == len(names):
        return False
    if keep:
        user_aliases[str(guild_id)][str(user_id)] = keep
    else:
        del user_aliases[str(guild_id)][str(user_id)]
    if save:
        save_aliases()
    return True


def clear_aliases(guild_id, user_id) -> int:
    names = user_aliases.get(str(guild_id), {}).pop(str(user_id), [])
    if names:
        save_aliases()
    return len(names)


def clean_alias(alias: str) -> str:
    """Прозвище без лишних пробелов и кавычек по краям."""
    return " ".join(str(alias or "").split()).strip("«»\"'`")


def alias_issue(alias: str):
    """Почему прозвище нельзя хранить (текст) или None. Те же правила, что у !alias, кроме лимита на число."""
    low, high = ALIAS_LEN
    if "<@" in alias or "@everyone" in alias or "@here" in alias:
        return "упоминание"
    if not low <= len(alias) <= high:
        return f"не {low}–{high} символов"
    if not norm_name(alias):
        return "нет букв и цифр"
    if alias.lower() in SELF_WORDS:
        return "слово «я/мне»"
    return None


def check_aliases(data: dict = None) -> list:
    """Проверка user_aliases.json при запуске — файл можно править руками (образец: user_aliases.example.json).
    Исправляет, что можно (одно прозвище строкой вместо списка, пробелы, повторы), остальное убирает.
    Ключи на «_» — комментарии, их не трогаем. Возвращает список замечаний; что-то исправили — сохраняет файл."""
    data = user_aliases if data is None else data
    notes = []
    for gid in list(data):
        if str(gid).startswith("_"):
            continue
        users = data[gid]
        if not str(gid).isdigit() or not isinstance(users, dict):
            notes.append(f"сервер «{gid}»: ключ — не ID сервера или внутри не {{ID участника: [прозвища]}} — убран")
            del data[gid]
            continue
        taken = {}                                   # нормализованное прозвище → чьё
        for uid in list(users):
            raw = users[uid]
            if not str(uid).isdigit():
                notes.append(f"сервер {gid}: «{uid}» — не ID участника — убран")
                del users[uid]
                continue
            if isinstance(raw, str):
                notes.append(f"сервер {gid}, участник {uid}: прозвище строкой — сделал списком")
                raw = [raw]
            if not isinstance(raw, list):
                notes.append(f"сервер {gid}, участник {uid}: вместо списка прозвищ {type(raw).__name__} — убран")
                del users[uid]
                continue
            keep = []
            for item in raw:
                alias = clean_alias(item) if isinstance(item, str) else ""
                why = alias_issue(alias) if alias else "пусто или не текст"
                if why is None and any(same_alias(alias, k) for k in keep):
                    why = "повтор"
                owner = next((taken[key] for key in (norm_name(alias), stem(norm_name(alias))) if key in taken), None)
                if why is None and owner is not None:
                    why = f"уже у участника {owner}"
                if why:
                    notes.append(f"сервер {gid}, участник {uid}: «{alias or item}» — {why} — убрано")
                    continue
                keep.append(alias)
                taken.setdefault(norm_name(alias), uid)
                taken.setdefault(stem(norm_name(alias)), uid)
            if not keep:
                del users[uid]                   # пустой список прозвищ хранить незачем
                if not raw:
                    notes.append(f"сервер {gid}, участник {uid}: пустой список — убран")
            elif keep != users[uid]:
                users[uid] = keep
                if not any(n.startswith(f"сервер {gid}, участник {uid}:") for n in notes):
                    notes.append(f"сервер {gid}, участник {uid}: убраны пробелы/кавычки по краям")
        if not users:
            del data[gid]
    if notes and data is user_aliases:
        save_aliases()
        print(f"[alias] user_aliases.json исправлен при запуске ({len(notes)}):")
        for n in notes:
            print(f"[alias]   {n}")
    return notes


def names_of(member) -> list:
    """Все имена участника: ник на сервере, имя аккаунта, глобальное имя и прозвища."""
    guild_id = getattr(getattr(member, "guild", None), "id", None)
    own = [member.display_name, member.name, getattr(member, "global_name", None) or ""]
    return [n for n in dict.fromkeys(own + (aliases_of(guild_id, member.id) if guild_id else [])) if n]


# ── Кто имелся в виду ─────────────────────────────────────────
def name_score(query: str, member) -> float:
    """Насколько нормализованное имя query похоже на участника (ник, имя, прозвища): 0…1."""
    best = 0.0
    for raw in names_of(member):
        name = norm_name(raw)
        if not name:
            continue
        if name == query:
            return 1.0
        if stem(name) == stem(query):
            best = max(best, 0.97)                  # «Петруху» → «Петруха»
        if len(query) >= 3 and (name.startswith(query) or query in name):
            best = max(best, 0.9)
        best = max(best, difflib.SequenceMatcher(None, query, name).ratio())
    return best


def find_member(guild, query, author, voice_members=()):
    """Участник по имени — как его написали или расслышал Whisper; сначала — те, кто в войсе.
    LookupError — никого похожего, ValueError — несколько похожих (в тексте — их имена)."""
    raw = str(query or "").strip().lstrip("@")
    if raw.lower() in SELF_WORDS:
        return author
    q = norm_name(raw)
    if not q:
        raise LookupError(raw)
    pool = {m.id: m for m in [*voice_members, *getattr(guild, "members", [])] if not getattr(m, "bot", False)}
    in_voice = {m.id for m in voice_members}
    for same in (lambda n: n == q, lambda n: stem(n) == stem(q)):   # точное имя/прозвище, потом с падежом
        hits = [m for m in pool.values() if any(same(norm_name(n)) for n in names_of(m))]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            raise ValueError(" или ".join(m.display_name for m in hits[:3]))
    scored = sorted(((name_score(q, m) + (0.05 if m.id in in_voice else 0), m) for m in pool.values()),
                    key=lambda x: x[0], reverse=True)
    if not scored or scored[0][0] < 0.75:
        raise LookupError(raw)
    close = [m for score, m in scored if score >= scored[0][0] - 0.08]
    if len(close) > 1:
        raise ValueError(" или ".join(m.display_name for m in close[:3]))
    return scored[0][1]


class AmbiguousMember(commands.BadArgument):
    """Под имя подходят несколько участников — текст ошибки можно показать как есть."""


class MemberRef(commands.Converter):
    """Участник для текстовых команд: упоминание, ID, ник — а ещё прозвище, падеж и транслит
    («!mute Петруха 10m», «!kick Васю»). allow_users — для !ban/!history: можно и того, кто не на сервере (по ID)."""

    def __init__(self, allow_users: bool = False):
        self.allow_users = allow_users

    async def convert(self, ctx, argument: str):
        if re.fullmatch(r"<@!?\d+>|\d{15,21}", argument.strip()):      # упоминание или ID — как в Discord
            try:
                return await commands.MemberConverter().convert(ctx, argument)
            except commands.MemberNotFound:
                if self.allow_users:
                    return await commands.UserConverter().convert(ctx, argument)
                raise
        try:                                   # имя — по кэшу участников, без лишних запросов к Discord
            return find_member(ctx.guild, argument, ctx.author)
        except ValueError as e:
            raise AmbiguousMember(f"Не понял, кого именно: {e}? Уточни упоминанием или прозвищем.")
        except LookupError:
            if self.allow_users:
                return await commands.UserConverter().convert(ctx, argument)
            raise commands.MemberNotFound(argument)


check_aliases()                 # при запуске: файл могли поправить руками
