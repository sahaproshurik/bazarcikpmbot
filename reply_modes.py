"""
reply_modes.py — режимы ответа ИИ, свои у каждого участника (reply_modes.json: {"guild_id": {"user_id": "admin"}}).

• standard — как обычно: на языке собеседника (русский, украинский, словацкий, английский);
• admin    — «язык админов»: тот же ответ латиницей-транслитом («tipo vot tak budu otvechat»). Переводит в
             латиницу сам бот, а не модель, — так транслит выходит ровным; голосом звучит обычная кириллица;
• yurchik  — «режим Юрчика»: в манере Юрчика — суржик, «типу», «бро», опечатки. Дообучать модели Groq нельзя,
             поэтому манеру задают примеры его сообщений из styles/yurchik.txt: они уходят в каждый запрос
             (так модель перенимает стиль с первого ответа). Датасет пополняется дописыванием строк в файл.
Нет записи — стандартный режим. Кто и как меняет режим — команда !режим в cogs/voice_ai.py.
"""
import os
import random
import re

from data import reply_modes, save_reply_modes

ROOT = os.path.dirname(os.path.abspath(__file__))
STYLE_FILE = os.path.join(ROOT, "styles", "yurchik.txt")
STYLE_SAMPLES = 40               # столько примеров Юрчика уходит в один запрос (весь файл, если меньше)
DEFAULT = "standard"
MODES = {                        # ключ → (эмодзи, название, что это)
    "standard": ("🗣️", "Стандартный", "как обычно — на языке собеседника: русский, украинский, словацкий, английский"),
    "admin":    ("🔤", "Язык админов", "транслит латиницей: «privet, tipo vot tak budu otvechat»"),
    "yurchik":  ("🤪", "Режим Юрчика", "в манере Юрчика: суржик, «типу», «бро», опечатки"),
}
# слова, по которым режим узнаётся в команде: «!режим юрчик», «!режим @Петя язык админов»
MODE_WORDS = {
    "standard": r"стандарт\w*|обычн\w*|норм\w*|звичайн\w*|standard\w*|normal\w*|default|štandard\w*|сброс\w*|reset",
    "admin":    r"админ\w*|адмін\w*|транслит\w*|трансліт\w*|латин\w*|admin\w*|translit\w*",
    "yurchik":  r"юрчик\w*|yurchik\w*|jurchik\w*|юрин\w*",
}
FILLER = r"режим\w*|язык\w*|мова|мовою|mode|на|в|для|как|у|мне|меня|мені|мене|me"

ADMIN_PROMPT = (
    "\n\nРЕЖИМ «ЯЗЫК АДМИНОВ» для этого собеседника: отвечай по-русски (или на его языке, если он пишет "
    "не по-русски), разговорно и коротко, как админ в чате. Пиши обычной кириллицей — бот сам переведёт ответ "
    "в латиницу-транслит.")
YURCHIK_PROMPT = (
    "\n\nРЕЖИМ «ЮРЧИК» для этого собеседника: отвечай в манере Юрчика с этого сервера — так, как он сам пишет. "
    "Ты не Юра и не говоришь от его имени: ты бот, который подражает его стилю письма. Его манера:\n"
    "— по-украински с суржиком: русские слова и формы вперемешку («щяс», «типу», «короче», «потом», «нада», "
    "«жостко», «чуєш», «бро», «братанчик»);\n"
    "— без заглавных и почти без знаков препинания, длинные сбивчивые фразы, повторы «типу»;\n"
    "— опечатки и пропущенные или переставленные буквы — по 2–4 на ответ, но чтобы смысл читался;\n"
    "— тон свой в доску, по-дружески, с лёгким матом, если собеседник сам так пишет.\n"
    "Пиши так всегда, даже если спрашивают по-русски, по-словацки или по-английски. По сути отвечай так же "
    "полезно и верно, как обычно, — меняется только манера. Не выдумывай факты о Юре и не рассказывай о нём "
    "личного. Все правила выше про опасные просьбы и личные данные действуют и тут.\n"
    "Примеры его сообщений — бери из них только манеру, не темы и не содержание:\n")

TRANSLIT = {"а": "a", "б": "b", "в": "v", "г": "g", "ґ": "g", "д": "d", "е": "e", "ё": "e", "є": "ye",
            "ж": "zh", "з": "z", "и": "i", "і": "i", "ї": "yi", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n",
            "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch",
            "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya", "’": "", "ʼ": ""}


class Answer(str):
    """Ответ для чата; .speech — что сказать голосом (в «языке админов» — кириллица, транслит синтезатор не прочтёт)."""
    def __new__(cls, text: str, speech: str = None):
        obj = super().__new__(cls, text)
        obj.speech = speech if speech is not None else text
        return obj


def translit(text: str) -> str:
    """Кириллица → латиница, как пишут в чате: «Привет, типо так» → «Privet, tipo tak». Латиница не меняется."""
    out = []
    for ch in text:
        low = ch.lower()
        if low in TRANSLIT:
            lat = TRANSLIT[low]
            out.append(lat.capitalize() if ch != low and lat else lat)
        else:
            out.append(ch)
    return "".join(out)


# ── Режим участника ───────────────────────────────────────────
def mode_of(guild_id, user_id) -> str:
    users = reply_modes.get(str(guild_id), {})
    mode = users.get(str(user_id)) if isinstance(users, dict) else None
    return mode if mode in MODES else DEFAULT


def set_mode(guild_id, user_id, mode: str):
    """Стандартный режим не храним: нет записи — значит стандартный."""
    users = reply_modes.setdefault(str(guild_id), {})
    if mode == DEFAULT:
        users.pop(str(user_id), None)
        if not users:
            reply_modes.pop(str(guild_id), None)
    else:
        users[str(user_id)] = mode
    save_reply_modes()


def modes_on(guild_id) -> dict:
    """{user_id: режим} — только нестандартные."""
    users = reply_modes.get(str(guild_id), {})
    return {int(uid): m for uid, m in (users.items() if isinstance(users, dict) else ()) if m in MODES and uid.isdigit()}


def label(mode: str) -> str:
    emoji, name, _ = MODES[mode]
    return f"{emoji} {name}"


def parse_mode(text: str):
    """«@Петя язык админов» → ("admin", "@Петя"). Режим — последнее слово-режим во фразе; остальное — кто."""
    words = (text or "").split()
    found, at = None, None
    for i, w in enumerate(words):
        token = w.lower().strip(".,!?«»\"'")
        for mode, pattern in MODE_WORDS.items():
            if re.fullmatch(pattern, token):
                found, at = mode, i
    rest = words if found is None else words[:at] + words[at + 1:]
    rest = [w for w in rest if not re.fullmatch(FILLER, w.lower().strip(".,!?«»\"'"))]
    return found, " ".join(rest)


# ── Ответ ИИ в режиме ─────────────────────────────────────────
_style = {"mtime": None, "examples": []}


def style_examples() -> list:
    """Сообщения Юрчика из styles/yurchik.txt (перечитывается, если файл поменяли)."""
    try:
        mtime = os.path.getmtime(STYLE_FILE)
    except OSError:
        return []
    if mtime != _style["mtime"]:
        with open(STYLE_FILE, encoding="utf-8") as f:
            lines = [ln.rstrip() for ln in f if not ln.lstrip().startswith("#")]
        blocks = re.split(r"\n\s*\n", "\n".join(lines))
        _style["examples"] = [b.strip() for b in blocks if b.strip()]
        _style["mtime"] = mtime
    return _style["examples"]


def system_prompt(base: str, mode: str, rng=random) -> str:
    if mode == "admin":
        return base + ADMIN_PROMPT
    if mode == "yurchik":
        examples = style_examples()
        if len(examples) > STYLE_SAMPLES:
            examples = rng.sample(examples, STYLE_SAMPLES)
        return base + YURCHIK_PROMPT + "\n".join(f"«{e}»" for e in examples)
    return base


def present(mode: str, reply: str) -> Answer:
    if mode == "admin":
        return Answer(translit(reply), speech=reply)
    return Answer(reply)
