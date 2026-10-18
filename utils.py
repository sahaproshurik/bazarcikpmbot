"""
utils.py — общие хелперы для cogs: длительности, безопасное удаление, журнал модерации.
"""
import asyncio
import re
from datetime import datetime, timedelta, timezone
import discord
from data import guild_config, mod_data, save_mod

_UNITS = {"s": 1, "с": 1, "m": 60, "м": 60, "h": 3600, "ч": 3600,
          "d": 86400, "д": 86400, "w": 604800, "н": 604800}
_DUR_RE = re.compile(r"(\d+)([a-zа-яё]*)")


def parse_duration(text: str, default_unit: str = "m"):
    """'10' → 10 минут (default_unit), '1h30m', '7d', '2н', '45сек' → timedelta. None — не распознано."""
    text = (text or "").strip().lower().replace(" ", "")
    total, pos = 0, 0
    for m in _DUR_RE.finditer(text):
        if m.start() != pos:
            return None
        unit = m.group(2)[:1] or default_unit
        if unit not in _UNITS:
            return None
        total += int(m.group(1)) * _UNITS[unit]
        pos = m.end()
    if not text or pos != len(text) or total <= 0:
        return None
    return timedelta(seconds=total)


def fmt_duration(td: timedelta) -> str:
    secs  = int(td.total_seconds())
    parts = []
    for name, size in (("д", 86400), ("ч", 3600), ("м", 60), ("с", 1)):
        if secs >= size:
            parts.append(f"{secs // size}{name}")
            secs %= size
    return " ".join(parts) or "0с"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def safe_delete(message: discord.Message):
    try:
        await message.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


def guild_cfg(guild_id) -> dict:
    """Настройки сервера (лог-канал, автомод, автороль, приветствие)."""
    return guild_config.setdefault(str(guild_id), {})


async def send_log(guild: discord.Guild, embed: discord.Embed):
    ch_id = guild_cfg(guild.id).get("log_channel")
    ch = guild.get_channel(ch_id) if ch_id else None
    if ch is None:
        return
    try:
        await ch.send(embed=embed)
    except (discord.Forbidden, discord.HTTPException):
        pass


ACTION_STYLE = {
    "warn":    ("⚠️ Предупреждение", discord.Color.orange()),
    "mute":    ("🔇 Тайм-аут",       discord.Color.dark_orange()),
    "unmute":  ("🔊 Снят тайм-аут",  discord.Color.green()),
    "kick":    ("👢 Кик",            discord.Color.red()),
    "ban":     ("🔨 Бан",            discord.Color.dark_red()),
    "unban":   ("✅ Разбан",         discord.Color.green()),
    "lock":    ("🔒 Канал закрыт",   discord.Color.dark_grey()),
    "unlock":  ("🔓 Канал открыт",   discord.Color.green()),
    "automod": ("🤖 Автомодерация",  discord.Color.purple()),
}


MAX_CASES = 2000            # храним последние кейсы, чтобы mod_data.json не рос бесконечно
_pending_save: set = set()  # отложенная запись журнала (держим ссылку на задачу)


async def _flush_mod_later():
    await asyncio.sleep(2)
    _pending_save.clear()
    save_mod()


def _schedule_mod_save():
    """Пачка кейсов (например, автомод во время рейда) пишется на диск одним разом."""
    if not _pending_save:
        _pending_save.add(asyncio.get_running_loop().create_task(_flush_mod_later()))


async def log_action(guild: discord.Guild, action: str, target, moderator, reason: str = "—",
                     duration: timedelta = None) -> int:
    """Записывает модерационное действие (кейс) и отправляет его в лог-канал. Возвращает номер кейса."""
    cases   = mod_data["cases"]
    case_id = mod_data.get("next_case") or max((c["id"] for c in cases), default=0) + 1
    mod_data["next_case"] = case_id + 1
    cases.append({
        "id":          case_id,
        "guild":       guild.id,
        "action":      action,
        "target":      getattr(target, "id", None),
        "target_name": str(target),
        "moderator":   getattr(moderator, "id", None),
        "reason":      reason,
        "duration":    int(duration.total_seconds()) if duration else None,
        "at":          utcnow().isoformat(),
    })
    del cases[:-MAX_CASES]
    _schedule_mod_save()
    title, color = ACTION_STYLE.get(action, (action, discord.Color.blurple()))
    e = discord.Embed(title=f"{title} • кейс #{case_id}", color=color, timestamp=utcnow())
    e.add_field(name="Цель", value=getattr(target, "mention", str(target)))
    e.add_field(name="Модератор", value=getattr(moderator, "mention", str(moderator)))
    if duration:
        e.add_field(name="Срок", value=fmt_duration(duration))
    e.add_field(name="Причина", value=reason or "—", inline=False)
    await send_log(guild, e)
    return case_id
