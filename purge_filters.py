"""
purge_filters.py — фильтры очистки чата для !clear: что удалять, разобранное из простого текста.

    !clear 50                               последние 50 сообщений
    !clear @Петя @Вася за 2ч                от этих людей за последние 2 часа
    !clear до 18.10 20:00 bots              от ботов, отправленные до 18 октября 20:00
    !clear после вчера 12:00 links          со ссылками начиная со вчерашнего полудня
    !clear за сегодня "казино"              за сегодня, в тексте есть «казино»

Все условия складываются (И), несколько участников — любой из них (ИЛИ). Ограничения, чтобы не грузить
сервер: удаляем не больше LIMIT сообщений, просматриваем не больше SCAN последних, только моложе MAX_AGE
(старше Discord удаляет лишь по одному и с лимитами), закреплённые не трогаем.
Время — по часовому поясу сервера (BOT_TIMEZONE, по умолчанию Европа/Братислава).
"""
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
import pytz
from utils import parse_duration

LIMIT   = 500                     # удалить за одну команду
SCAN    = 2000                    # просмотреть последних сообщений, если есть фильтры
MAX_AGE = timedelta(days=14)      # Discord удаляет пачкой только сообщения моложе 14 дней
TZ      = pytz.timezone(os.getenv("BOT_TIMEZONE", "Europe/Bratislava"))
LINK_MARKERS = ("http://", "https://", "discord.gg/")

KINDS = {   # слово → тип
    "bots": "bots", "bot": "bots", "боты": "bots", "ботов": "bots", "ботами": "bots", "боти": "bots", "boty": "bots",
    "humans": "humans", "people": "humans", "люди": "humans", "людей": "humans", "ľudia": "humans",
    "links": "links", "ссылки": "links", "ссылками": "links", "ссылок": "links", "посилання": "links", "odkazy": "links",
    "files": "files", "images": "files", "файлы": "files", "файлами": "files", "файлов": "files", "картинки": "files",
    "картинками": "files", "фото": "files", "файли": "files", "obrázky": "files", "súbory": "files",
}
KIND_LABEL = {"bots": "только боты", "humans": "только люди", "links": "со ссылками", "files": "с файлами"}
BEFORE_WORDS = {"до", "before", "pred"}
AFTER_WORDS  = {"после", "с", "со", "since", "after", "після", "з", "od", "po"}
PERIOD_WORDS = {"за", "last", "for", "za"}
SKIP_WORDS   = {"от", "from", "від", "сообщений", "сообщения", "сообщение", "повідомлень", "messages", "msgs",
                "správ", "последние", "последних", "останні", "posledné", "и", "and", "та", "a", "штук", "шт"}
TOKEN_RE = re.compile(r'"([^"]+)"|«([^»]+)»|<@!?(\d+)>|(\S+)')
DATE_RE  = re.compile(r"^(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?$|^(\d{4})-(\d{2})-(\d{2})(?:[Tt](\d{1,2}):(\d{2}))?$")
TIME_RE  = re.compile(r"^(\d{1,2}):(\d{2})$")
DAY_WORDS = {"сегодня": 0, "today": 0, "сьогодні": 0, "dnes": 0, "вчера": 1, "yesterday": 1, "вчора": 1, "včera": 1,
             "позавчера": 2}


@dataclass
class ClearSpec:
    limit: Optional[int] = None
    users: list = field(default_factory=list)       # ID — несколько: любой из них
    after: Optional[datetime] = None                # UTC
    before: Optional[datetime] = None               # UTC
    kinds: set = field(default_factory=set)
    texts: list = field(default_factory=list)
    clamped: bool = False                           # просили раньше, чем 14 дней назад, — граница поднята
    floor: bool = False                             # «после» не просили — это просто граница в 14 дней

    @property
    def filtered(self) -> bool:
        return bool(self.users or self.before or self.kinds or self.texts or (self.after and not self.floor))

    def match(self, m) -> bool:
        if getattr(m, "pinned", False):
            return False
        if self.users and m.author.id not in self.users:
            return False
        if "bots" in self.kinds and not m.author.bot or "humans" in self.kinds and m.author.bot:
            return False
        content = (m.content or "").lower()
        if "links" in self.kinds and not any(x in content for x in LINK_MARKERS):
            return False
        if "files" in self.kinds and not m.attachments:
            return False
        return all(t.lower() in content for t in self.texts)

    def describe(self, guild=None) -> str:
        """«не больше 50, от Petya, после 18.10 12:00, только боты» — для чата и подтверждения."""
        local = lambda dt: dt.astimezone(TZ).strftime("%d.%m %H:%M")    # noqa: E731
        if not self.filtered:
            return f"последние {self.limit}"
        parts = [f"не больше {self.limit}"] if self.limit < LIMIT else []
        if self.users:
            who = [getattr(guild.get_member(u), "display_name", None) if guild else None for u in self.users]
            parts.append("от " + ", ".join(w or f"ID {u}" for w, u in zip(who, self.users)))
        if self.after and not self.floor:
            parts.append(f"после {local(self.after)}" + (" (старше 14 дней не трогаю)" if self.clamped else ""))
        if self.before:
            parts.append(f"до {local(self.before)}")
        parts += [KIND_LABEL[k] for k in sorted(self.kinds)]
        parts += [f"с текстом «{t}»" for t in self.texts]
        return ", ".join(parts)


def _year(year: Optional[str], now: datetime) -> int:
    if not year:
        return now.year
    return int(year) + (2000 if len(year) == 2 else 0)


def _local(day, hour: int = 0, minute: int = 0) -> datetime:
    return TZ.localize(datetime(day.year, day.month, day.day, hour, minute)).astimezone(timezone.utc)


def _moment(tokens: list, i: int, now: datetime):
    """Дата/время начиная с tokens[i] → (UTC datetime, сколько токенов съели). Понимает 18.10, 18.10.2026,
    2026-10-18, 2026-10-18T20:00, 20:00, сегодня/вчера и их сочетания со временем."""
    tok = tokens[i].lower() if i < len(tokens) else ""
    day, used = None, 0
    try:
        if tok in DAY_WORDS:
            day, used = (now - timedelta(days=DAY_WORDS[tok])).date(), 1
        elif m := DATE_RE.match(tok):
            used = 1
            if m.group(1):
                day = datetime(_year(m.group(3), now), int(m.group(2)), int(m.group(1))).date()
                if not m.group(3) and day > now.date():
                    day = day.replace(year=day.year - 1)   # «до 25.12» в октябре — прошлый год
            else:
                day = datetime(int(m.group(4)), int(m.group(5)), int(m.group(6))).date()
                if m.group(7):
                    return _local(day, int(m.group(7)), int(m.group(8))), 1
    except ValueError:
        raise ValueError(f"нет такой даты «{tokens[i]}»")
    hour = minute = 0
    nxt = tokens[i + used].lower() if i + used < len(tokens) else ""
    if t := TIME_RE.match(nxt if used else tok):
        hour, minute = int(t.group(1)), int(t.group(2))
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError(f"нет такого времени «{t.group(0)}»")
        if not used:
            day = now.date()
            if (hour, minute) > (now.hour, now.minute):    # «после 23:00» в 10 утра — вчерашние 23:00
                day -= timedelta(days=1)
        used += 1
    if day is None:
        return None, 0
    return _local(day, hour, minute), used


def _tokens(query: str):
    """[(текст, это «цитата», ID из упоминания)] — запятые и точки с запятой по краям слов не мешают."""
    out = []
    for m in TOKEN_RE.finditer(query or ""):
        quoted = m.group(1) or m.group(2)
        out.append((quoted if quoted is not None else (m.group(3) or m.group(4).strip(",;")),
                    quoted is not None, m.group(3)))
    return [t for t in out if t[0]]


def _person(resolve, word: str):
    """ID участника по имени или прозвищу; None — это не имя. Несколько похожих — понятная ошибка."""
    try:
        return resolve(word)
    except LookupError:
        return None
    except ValueError as e:
        raise ValueError(f"«{word}» — не понял, кого именно: {e}")


def parse_clear(query: str, now: datetime = None, resolve=None) -> ClearSpec:
    """Текст фильтров → ClearSpec. ValueError — с понятным текстом, что не так.
    resolve(слово) → ID участника: так понимаются имена и прозвища («от Петрухи»). Он бросает LookupError,
    если никого похожего нет, и ValueError с именами, если похожих несколько."""
    now_utc = now or datetime.now(timezone.utc)
    now = now_utc.astimezone(TZ)
    items = _tokens(query)
    tokens = [t for t, _, _ in items]
    spec, i = ClearSpec(), 0
    while i < len(tokens):
        tok, quoted, mention = items[i]
        low = tok.lower()
        if quoted:
            spec.texts.append(tok)
        elif mention or (low.isdigit() and len(low) >= 17):
            spec.users.append(int(mention or low))
        elif low in SKIP_WORDS:
            pass
        elif low in KINDS:
            spec.kinds.add(KINDS[low])
        elif low in BEFORE_WORDS | AFTER_WORDS:
            moment, used = _moment(tokens, i + 1, now)
            if moment is None:
                if low in ("с", "со", "з"):                # «с файлами», «со ссылками»
                    i += 1
                    continue
                raise ValueError(f"после «{tok}» нужна дата или время: 18.10, 18.10 20:00, 20:00, вчера")
            if low in BEFORE_WORDS:
                spec.before = min(spec.before or moment, moment)
            else:
                spec.after = max(spec.after or moment, moment)
            i += used
        elif low in PERIOD_WORDS or parse_duration(low, "") is not None:
            j = i + 1 if low in PERIOD_WORDS else i
            while j < len(tokens) and tokens[j].lower() in SKIP_WORDS:
                j += 1
            nxt = tokens[j].lower() if j < len(tokens) else ""
            if nxt in DAY_WORDS:                              # «за сегодня», «за вчера»
                start, _ = _moment(tokens, j, now)
                spec.after = max(spec.after or start, start)
                if DAY_WORDS[nxt]:
                    end = start + timedelta(days=1)
                    spec.before = min(spec.before or end, end)
                i = j + 1
                continue
            text, used = nxt, 1
            if nxt.isdigit() and j + 1 < len(tokens) and not tokens[j + 1][:1].isdigit():
                text, used = nxt + tokens[j + 1].lower(), 2   # «за 2 часа»
            period = parse_duration(text, "")
            if period is None:
                raise ValueError(f"не понял срок «{' '.join(tokens[j:j + used]) or tok}» — пример: за 2ч, за 30m, за 1d")
            start = now_utc - period
            spec.after = max(spec.after or start, start)
            i = j + used
            continue
        elif low.isdigit():
            if spec.limit is not None:
                raise ValueError(f"два числа: {spec.limit} и {low} — сколько удалить?")
            spec.limit = int(low)
        elif resolve is not None and (uid := _person(resolve, tok)) is not None:
            spec.users.append(uid)
        else:
            raise ValueError(f"не понял «{tok}». Фильтры: число, @участник, за 2ч, до/после 18.10 20:00, "
                             "bots, humans, links, files, \"текст\"")
        i += 1
    return validate(spec, now_utc)


def validate(spec: ClearSpec, now_utc: datetime) -> ClearSpec:
    if spec.limit is None and not spec.filtered:
        raise ValueError("укажи, сколько удалить, или фильтр: `!clear 50`, `!clear @user за 2ч`")
    if spec.limit is not None and not 1 <= spec.limit <= LIMIT:
        raise ValueError(f"удалить можно от 1 до {LIMIT} сообщений за раз")
    if spec.limit is None:
        spec.limit = LIMIT
    oldest = now_utc - MAX_AGE + timedelta(minutes=5)
    if spec.before and spec.before <= oldest:
        raise ValueError("Discord даёт удалять пачкой только сообщения моложе 14 дней — граница «до» слишком давно")
    if spec.after is None:
        spec.after, spec.floor = oldest, True
    elif spec.after < oldest:
        spec.after, spec.clamped = oldest, True
    if spec.before and spec.after >= spec.before:
        raise ValueError("граница «после» позже границы «до» — под фильтр ничего не попадёт")
    if "bots" in spec.kinds and "humans" in spec.kinds:
        raise ValueError("bots и humans вместе — это все сообщения, выбери что-то одно")
    return spec
