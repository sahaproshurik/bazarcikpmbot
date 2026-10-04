"""
cogs/spt_status.py — следит за статусом SPT-сервера и меняет статус бота.

Бот не принимает входящих подключений и ничего не слушает — он просто
раз в 30 секунд читает маленький текстовый файл (Gist на GitHub), в который
скрипт-лаунчер на ПК пишет "online"/"offline" при старте и остановке
SPT-сервера.

Нужна переменная окружения SPT_STATUS_GIST_URL — сырая (raw) ссылка на
gist-файл, вида:
https://gist.githubusercontent.com/ТВОЙ_НИК/GIST_ID/raw/status.txt
Добавь её в настройках хостинга (там же, где DISCORD_BOT_TOKEN).
"""

import os
import time
import discord
import aiohttp
from discord.ext import commands, tasks

SPT_STATUS_GIST_URL = os.getenv("SPT_STATUS_GIST_URL", "")


class SPTStatus(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.last_state = None
        self.check_spt_status.start()

    def cog_unload(self):
        self.check_spt_status.cancel()

    @tasks.loop(seconds=30)
    async def check_spt_status(self):
        if not SPT_STATUS_GIST_URL:
            print("[spt_status] SPT_STATUS_GIST_URL не задан, пропускаю проверку")
            return

        url = f"{SPT_STATUS_GIST_URL}?t={int(time.time())}"  # анти-кэш GitHub CDN
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    text = (await resp.text()).strip().lower()
        except Exception as e:
            print(f"[spt_status] Не удалось проверить статус: {e}")
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
