"""
cogs/spt_status.py — следит за статусом SPT-сервера и меняет статус бота.

Бот не принимает входящих подключений и ничего не слушает — он просто
раз в 60 секунд спрашивает у GitHub API содержимое gist-файла, в который
скрипт-лаунчер на ПК пишет "online"/"offline" при старте и остановке
SPT-сервера. Используется именно API (api.github.com), а не "сырая"
raw-ссылка — у raw-ссылок гистов свой CDN-кэш, который может отдавать
устаревшее значение по несколько минут.

Нужна переменная окружения SPT_STATUS_GIST_ID — это просто ID твоего
gist'а (кусок из адреса https://gist.github.com/ТВОЙ_НИК/ВОТ_ЭТО_ID).
Добавь её в настройках хостинга (там же, где DISCORD_BOT_TOKEN).

Без токена чтение ограничено 60 запросами в час от GitHub — этого хватает
на проверку раз в 60 секунд. Если хочешь проверять чаще, добавь ещё одну
переменную окружения SPT_STATUS_GITHUB_TOKEN с тем же токеном, что
используется в скрипте на ПК (с правом "gist") — тогда лимит вырастет
до 5000 запросов в час, и можно смело опрашивать каждые 10-15 секунд.
"""

import os
import discord
import aiohttp
from discord.ext import commands, tasks

GIST_ID = os.getenv("SPT_STATUS_GIST_ID", "")
GIST_FILENAME = os.getenv("SPT_STATUS_GIST_FILENAME", "status.txt")
GITHUB_TOKEN = os.getenv("SPT_STATUS_GITHUB_TOKEN", "")  # опционально, для более частых проверок

# Без токена безопасный минимум — 60 секунд (лимит 60 запросов/час).
# С токеном лимит 5000/час, можно смело уменьшать это число.
CHECK_INTERVAL_SECONDS = 10 if GITHUB_TOKEN else 60


class SPTStatus(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_state = None
        self.check_spt_status.start()

    def cog_unload(self):
        self.check_spt_status.cancel()

    @tasks.loop(seconds=CHECK_INTERVAL_SECONDS)
    async def check_spt_status(self):
        if not GIST_ID:
            print("[spt_status] SPT_STATUS_GIST_ID не задан, пропускаю проверку")
            return

        url = f"https://api.github.com/gists/{GIST_ID}"
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        print(f"[spt_status] GitHub API ответил {resp.status}")
                        return
                    data = await resp.json()
        except Exception as e:
            print(f"[spt_status] Не удалось проверить статус: {e}")
            return

        try:
            text = data["files"][GIST_FILENAME]["content"].strip().lower()
        except (KeyError, TypeError):
            print(f"[spt_status] Не нашёл файл '{GIST_FILENAME}' в gist")
            return

        if text not in ("online", "offline") or text == self.last_state:
            return

        self.last_state = text
        if text == "online":
            await self.bot.change_presence(
                status=discord.Status.online,
                activity=discord.Game(name="🟢 SPT Server ONLINE"),
            )
        else:
            await self.bot.change_presence(
                status=discord.Status.idle,
                activity=discord.Game(name="🔴 SPT Server OFFLINE"),
            )
        print(f"[spt_status] Статус сервера обновлён: {text}")

    @check_spt_status.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()


def setup(bot):
    bot.add_cog(SPTStatus(bot))