"""
diag.py — цифры для логов: сколько памяти и процессора тратит бот (и весь контейнер на хостинге).

Только стандартная библиотека. На Linux (хостинг) данные берутся из /proc и cgroup, на других системах
недоступные цифры просто не попадают в строку.
"""
import os
import time


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def rss_mib():
    """Память процесса бота (RSS), МиБ. None — система без /proc."""
    status = _read("/proc/self/status") or ""
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1]) / 1024
    return None


def container_mib():
    """Память всего контейнера (бот + ffmpeg + файловый кэш) и её лимит из cgroup, МиБ."""
    for cur, lim in (("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory.max"),
                     ("/sys/fs/cgroup/memory/memory.usage_in_bytes", "/sys/fs/cgroup/memory/memory.limit_in_bytes")):
        used = _read(cur)
        if used and used.isdigit():
            limit = _read(lim) or ""
            return int(used) / 2**20, (int(limit) / 2**20 if limit.isdigit() and int(limit) < 1 << 50 else None)
    return None, None


class CpuMeter:
    """Доля одного ядра, которую бот вместе с дочерними ffmpeg потратил с прошлого замера."""

    def __init__(self):
        self.wall, self.cpu = time.monotonic(), self._cpu()

    @staticmethod
    def _cpu() -> float:
        t = os.times()
        return t.user + t.system + t.children_user + t.children_system

    def percent(self) -> float:
        wall, cpu = time.monotonic(), self._cpu()
        share = (cpu - self.cpu) / max(wall - self.wall, 1e-6) * 100
        self.wall, self.cpu = wall, cpu
        return share


def report(cpu: CpuMeter = None) -> str:
    """«бот 160 МиБ, контейнер 190/256 МиБ, CPU 6% ядра» — то, что известно на этой системе."""
    parts = []
    rss = rss_mib()
    if rss is not None:
        parts.append(f"бот {rss:.0f} МиБ")
    used, limit = container_mib()
    if used is not None:
        parts.append(f"контейнер {used:.0f}" + (f"/{limit:.0f}" if limit else "") + " МиБ")
    if cpu is not None:
        parts.append(f"CPU {cpu.percent():.0f}% ядра")
    return ", ".join(parts) or "нет данных о памяти"
