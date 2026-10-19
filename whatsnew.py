"""
whatsnew.py — «чему новому ты научился»: что добавили в бота с прошлого рассказа.

Источник — история git (заголовок и описание коммитов). Если на хостинге нет git или папки .git,
берутся разделы CHANGES.md. Для каждого сервера запоминается, о чём уже рассказано (whatsnew_seen.json):
в следующий раз бот расскажет только о новом.
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
MAX_ITEMS = 8
TEXT_LIMIT = 300          # описание одного пункта, символов
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


def from_git(root: str = ROOT, limit: int = 60) -> Optional[list]:
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
    """Что рассказать: всё после уже рассказанного; впервые (или история переписана) — свежее за сутки."""
    ids = [it["id"] for it in items]
    if seen in ids:
        return items[:ids.index(seen)][:MAX_ITEMS]
    if not items:
        return []
    newest = items[0]["time"]
    if newest is None:
        return items[:3]
    return [it for it in items if it["time"] is not None and newest - it["time"] <= NIGHT_SEC][:MAX_ITEMS]


def embed_for(new: list, items: list) -> discord.Embed:
    if not new:
        e = discord.Embed(title=f"😴 {NOTHING}", color=discord.Color.light_grey())
        if items:
            e.description = f"Последнее, что добавили: **{items[0]['title']}**"
        return e
    e = discord.Embed(title=f"🍻 {INTRO}:", color=COLOR)
    for it in new:
        e.add_field(name=f"• {it['title']}"[:256], value=(it["text"] or "—")[:1024], inline=False)
    return e


def voice_text(snapshots) -> str:
    """Для голоса: вступление и только заголовки пунктов — описания длинные, их читают в чате."""
    for s in snapshots:
        for e in s.embeds:
            if e.title and (INTRO in e.title or NOTHING in e.title):
                head = INTRO if INTRO in e.title else NOTHING
                titles = [f.name.removeprefix("• ") for f in e.fields]
                if not titles:
                    return head + "."
                return head + ": " + "; ".join(titles) + "."
    return ""
