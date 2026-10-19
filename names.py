"""
names.py — как бот узнаёт людей по имени: нормализация имён и прозвища, привязанные к ID участника.

Прозвища хранятся по серверам в user_aliases.json: {"guild_id": {"user_id": ["Петя", "Петруха"]}}.
На одном сервере прозвище принадлежит одному человеку. Сравниваются имена без регистра, диакритики
и алфавита («Петруха» = «Petrukha»), а stem() убирает падежное окончание («Петруху» = «Петруха»).
Кто и как может менять прозвища — в cogs/aliases.py.
"""
import re
import unicodedata
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
    return user_aliases.get(str(guild_id), {})


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


def names_of(member) -> list:
    """Все имена участника: ник на сервере, имя аккаунта, глобальное имя и прозвища."""
    guild_id = getattr(getattr(member, "guild", None), "id", None)
    own = [member.display_name, member.name, getattr(member, "global_name", None) or ""]
    return [n for n in dict.fromkeys(own + (aliases_of(guild_id, member.id) if guild_id else [])) if n]
