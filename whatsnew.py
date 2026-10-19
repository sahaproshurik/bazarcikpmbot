"""
whatsnew.py — «чему новому ты научился»: что добавили в бота с прошлого рассказа.

Источник — история git (заголовок и описание коммитов). Если на хостинге нет git или папки .git,
берутся разделы CHANGES.md. Для каждого сервера запоминается, о чём уже рассказано (whatsnew_seen.json):
в следующий раз бот расскажет только о новом. Каждое изменение — отдельным сообщением, по порядку, все сразу
(если задать MAX_ITEMS — не больше стольких за раз, остальное — на следующий вопрос, с того же места).
"""
import os
import re
import subprocess
from typing import Optional

import discord

ROOT = os.path.dirname(os.path.abspath(__file__))
INTRO = "За ночь мы с алкашом добавили такие приколюхи"
NOTHING = "Пока ничего нового — алкаш ещё спит"
NIGHT_SEC = 24 * 3600     # первый рассказ: всё, что добавили за последние сутки работы
MAX_ITEMS = None         # без лимита: каждое новое изменение — отдельным сообщением. Число — столько за раз,
                         # остальное — на следующий вопрос («и ещё N»)
HISTORY = 200            # сколько последних коммитов читаем: глубже — уже не «новое»
TEXT_LIMIT = 900         # описание одного изменения, символов
ITEM_MARK = "🆕 "         # так начинается заголовок сообщения с изменением
COLOR = discord.Color.from_rgb(230, 126, 34)
TRAILER_RE = re.compile(r"^(Co-Authored-By|Signed-off-by|🤖 Generated)", re.I)


def clean(text: str) -> str:
    """Описание пункта в одну строку: без служебных строк, Markdown и лишних пробелов, не длиннее TEXT_LIMIT."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip() and not TRAILER_RE.match(ln.strip())]
    flat = " ".join(lines)
    flat = re.sub(r"\*\*|__|`", "", flat)
    flat = re.sub(r"\s+", " ", flat).strip()
    if len(flat) > TEXT_LIMIT:
        cut = flat[:TEXT_LIMIT].rsplit(" ", 1)[0].rstrip(",;:—- ")
        flat = cut + "…"
    return flat


def from_git(root: str = ROOT, limit: int = HISTORY) -> Optional[list]:
    """Коммиты новые → старые: [{id, title, text, time}]. None — git недоступен."""
    if not os.path.exists(os.path.join(root, ".git")):
        return None
    try:
        out = subprocess.run(["git", "-C", root, "log", f"-n{limit}", "--no-merges",
                              "--format=%H%x1f%ct%x1f%s%x1f%b%x1e"],
                             capture_output=True, timeout=5, check=True).stdout.decode("utf-8", "replace")
    except (OSError, subprocess.SubprocessError):
        return None
    items = []
    for rec in out.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) < 4 or not parts[0]:
            continue
        sha, ts, title, body = parts[0].strip(), parts[1], parts[2].strip(), parts[3]
        items.append({"id": sha, "title": title, "text": clean(body), "time": int(ts)})
    return items or None


def from_changes(root: str = ROOT) -> list:
    """Разделы CHANGES.md «## N. Заголовок» новые → старые; описание — первый абзац раздела."""
    try:
        with open(os.path.join(root, "CHANGES.md"), encoding="utf-8") as f:
            src = f.read()
    except OSError:
        return []
    items = []
    for m in re.finditer(r"^## (\d+)\.\s*(.+?)\s*$(.*?)(?=^## |\Z)", src, re.M | re.S):
        num, title, body = m.group(1), m.group(2), m.group(3)
        para = next((p for p in re.split(r"\n\s*\n", body) if p.strip()), "")
        items.append({"id": f"changes:{num}", "title": title.replace("`", ""), "text": clean(para), "time": None})
    items.sort(key=lambda it: int(it["id"].split(":")[1]), reverse=True)
    return items


def history(root: str = ROOT) -> list:
    return from_git(root) or from_changes(root)


def pick_new(items: list, seen: Optional[str]) -> list:
    """Что рассказать (новые → старые): всё после уже рассказанного; впервые (или история переписана) —
    добавленное за сутки работы."""
    ids = [it["id"] for it in items]
    if seen in ids:
        return items[:ids.index(seen)]
    if not items:
        return []
    newest = items[0]["time"]
    if newest is None:
        return items[:3]
    return [it for it in items if it["time"] is not None and newest - it["time"] <= NIGHT_SEC]


def batch(new: list) -> tuple:
    """Порция для одного ответа: по порядку, от раннего к позднему, не больше MAX_ITEMS; и сколько осталось.
    Рассказанным считается последнее показанное — остаток бот расскажет в следующий раз."""
    ordered = list(reversed(new))
    if not MAX_ITEMS:
        return ordered, 0
    return ordered[:MAX_ITEMS], max(0, len(ordered) - MAX_ITEMS)


def source_note(shown: list, items: list) -> str:
    """Откуда прочитано — для подписи ответа: история git (какие коммиты) или CHANGES.md (какие разделы)."""
    if not items:
        return "Не нашёл ни истории git, ни CHANGES.md — рассказывать не из чего"
    shown = shown or items[:1]
    if not items[0]["id"].startswith("changes:"):
        first, last = shown[0]["id"][:7], shown[-1]["id"][:7]
        span = first if first == last else f"{first}…{last}"
        return f"📜 Прочитал из истории git: {'коммит' if first == last else 'коммиты'} {span}"
    nums = [it["id"].split(":")[1] for it in shown]
    span = nums[0] if len(nums) == 1 else f"{nums[0]}–{nums[-1]}"
    return f"📄 Прочитал из CHANGES.md, {'раздел' if len(nums) == 1 else 'разделы'} {span} (git на сервере недоступен)"


def more_note(rest: int) -> str:
    return f"И ещё {rest} — спроси ещё раз, расскажу дальше" if rest else ""


def embeds_for(shown: list, items: list, rest: int = 0) -> list:
    """Сообщения ответа: вступление и по одному сообщению на каждое изменение; нового нет — одно сообщение.
    Подпись — откуда прочитано и сколько осталось — у последнего."""
    if not shown:
        e = discord.Embed(title=f"😴 {NOTHING}", color=discord.Color.light_grey())
        if items:
            e.description = f"Последнее, что добавили: **{items[0]['title']}**"
        e.set_footer(text=source_note(shown, items))
        return [e]
    count = f"{len(shown)} {plural(len(shown))}" + (f" из {len(shown) + rest}" if rest else "")
    out = [discord.Embed(title=f"🍻 {INTRO}:", description=f"{count} — по одному сообщению ниже 👇", color=COLOR)]
    for n, it in enumerate(shown, 1):
        e = discord.Embed(title=f"{ITEM_MARK}{it['title']}"[:256], description=(it["text"] or "—")[:4096], color=COLOR)
        e.set_author(name=f"{n}/{len(shown)}")
        out.append(e)
    out[-1].set_footer(text=" • ".join(x for x in (source_note(shown, items), more_note(rest)) if x))
    return out


def plural(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "изменение"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "изменения"
    return "изменений"


def voice_text(snapshots) -> str:
    """Для голоса: вступление и только заголовки пунктов — описания длинные, их читают в чате."""
    embeds = [e for s in snapshots for e in s.embeds]
    titles = [e.title.removeprefix(ITEM_MARK) for e in embeds if e.title and e.title.startswith(ITEM_MARK)]
    rest = next((m.group(1) for e in embeds if e.footer and e.footer.text
                 for m in [re.search(r"И ещё (\d+)", e.footer.text)] if m), None)
    for e in embeds:
        if e.title and NOTHING in e.title:
            return NOTHING + "."
        if e.title and INTRO in e.title:
            text = INTRO + (": " + "; ".join(titles) if titles else "") + "."
            return text + (f" И ещё {rest} — спроси ещё раз." if rest else "")
    return ""
