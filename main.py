"""
main.py — точка входа бота BAZARCIK_PM.

Бот создаётся внутри asyncio-цикла (на Python 3.14+ создание вне цикла падает),
загружает модули из cogs/ и централизованно обрабатывает ошибки команд.
"""
import asyncio
import logging
import os
import sys
import time
import traceback
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()   # до импорта cogs: config.py и ai.py читают переменные окружения при импорте

from cogs.help_cmd import MyHelpCommand  # noqa: E402
from names import AmbiguousMember         # noqa: E402
from utils import safe_delete             # noqa: E402

# ── Cogs to load ─────────────────────────────────────────────
COGS = [
    "cogs.xp",
    "cogs.economy",
    "cogs.shop",
    "cogs.games",
    "cogs.durak",
    "cogs.work",
    "cogs.mcdonalds",
    "cogs.business",
    "cogs.loans",
    "cogs.moderation",
    "cogs.admin",
    "cogs.info",
    "cogs.fun",
    "cogs.petitions",
    "cogs.voice_ai",
    "cogs.voice_listen",
    "cogs.aliases",
    "cogs.jarvis",
    # "cogs.mafia" — отключена, код оставлен в cogs/mafia.py
    "cogs.spt_status",
]


class BazarcikBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members         = True
        intents.message_content = True
        intents.voice_states    = True
        intents.guilds          = True
        super().__init__(command_prefix="!", intents=intents, case_insensitive=True,
                         help_command=MyHelpCommand())
        self.start_time  = time.time()
        self.failed_cogs: dict = {}   # модуль → ошибка загрузки (видно в !botstatus)
        self.before_invoke(self._hide_command)

    async def _hide_command(self, ctx):
        # Бот убирает сообщение с командой из чата — одно место вместо delete() в каждой команде.
        # В ЛС удалять чужие сообщения нельзя, поэтому там пропускаем.
        if ctx.guild is not None:
            await safe_delete(ctx.message)

    def load_cogs(self):
        for cog in COGS:
            try:
                self.load_extension(cog)
                print(f"  ✅ Loaded {cog}")
            except Exception as e:
                self.failed_cogs[cog] = repr(e)
                print(f"  ❌ Failed to load {cog}: {e!r}")
                traceback.print_exception(e)

    # ── Events ───────────────────────────────────────────────
    async def on_ready(self):
        print(f"✅ {self.user} запущен! Серверов: {len(self.guilds)}, модулей: {len(self.cogs)}")
        if self.failed_cogs:
            print(f"⚠️ Не загрузились: {', '.join(self.failed_cogs)}")

    async def on_member_join(self, member):
        try:
            with open("help.txt", "r", encoding="utf-8") as f:
                help_text = f.read()
        except FileNotFoundError:
            help_text = "Добро пожаловать! Используй !help для списка команд."
        try:
            await member.send(
                f"👋 Привет, **{member.name}**! Добро пожаловать на **{member.guild.name}**!\n\n{help_text}"
            )
        except discord.Forbidden:
            pass

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return
        if ctx.command and ctx.command.has_error_handler():
            return
        original = getattr(error, "original", error)

        if isinstance(error, commands.MissingPermissions):
            text = "❌ Недостаточно прав!"
        elif isinstance(error, commands.NotOwner):
            text = "❌ Только для владельца бота."
        elif isinstance(error, commands.NoPrivateMessage):
            text = "❌ Эта команда работает только на сервере."
        elif isinstance(error, (commands.BotMissingPermissions, commands.BotMissingRole)) \
                or isinstance(original, discord.Forbidden):
            text = "❌ У бота не хватает прав для этого действия — проверь роль бота в настройках сервера."
        elif isinstance(error, commands.MissingRequiredArgument):
            text = f"❌ Пропущен аргумент: `{error.param.name}`. Используй `!help {ctx.command}`"
        elif isinstance(error, (commands.MemberNotFound, commands.UserNotFound)):
            text = f"❌ Участник «{discord.utils.escape_markdown(error.argument)}» не найден — проверь ник или прозвище (`!alias`)."
        elif isinstance(error, AmbiguousMember):
            text = f"❌ {error}"
        elif isinstance(error, (commands.BadArgument, commands.BadUnionArgument)):
            text = f"❌ Неверный аргумент! Используй `!help {ctx.command}`"
        elif isinstance(error, commands.CommandOnCooldown):
            text = f"⏳ Cooldown! Попробуй через {error.retry_after:.0f}сек."
        elif isinstance(error, commands.CheckFailure):
            text = "❌ Эта команда тебе недоступна."
        elif isinstance(original, discord.NotFound):
            return   # сообщение уже удалено и т.п. — не ошибка для пользователя
        else:
            print(f"[ERROR] Command '{ctx.command}': {original!r}")
            traceback.print_exception(original)
            text = "⚠️ Что-то пошло не так. Ошибка записана в лог."
        try:
            await ctx.send(text, delete_after=10)
        except discord.HTTPException:
            pass


class StampedOutput:
    """Время в начале каждой строки print() — так логи бота ([listen], [wake], [jarvis]…) легко
    сопоставлять со строками py-cord, у которых время уже есть."""

    def __init__(self, stream):
        self.stream, self.fresh = stream, True

    def write(self, text: str):
        out = []
        for part in text.splitlines(keepends=True):
            if self.fresh:
                out.append(time.strftime("%Y-%m-%d %H:%M:%S "))
            out.append(part)
            self.fresh = part.endswith("\n")
        return self.stream.write("".join(out))

    def __getattr__(self, name):
        return getattr(self.stream, name)


# ── Entry point ──────────────────────────────────────────────
async def main():
    token = os.getenv("DISCORD_BOT_TOKEN")
    if not token:
        raise SystemExit("DISCORD_BOT_TOKEN не найден в .env / настройках хостинга!")
    bot = BazarcikBot()
    async with bot:
        bot.load_cogs()
        await bot.start(token)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # py-cord раз в секунду пишет INFO о служебных RTCP-пакетах голоса — за этим шумом не видно логов бота
    logging.getLogger("discord.voice.receive.reader").setLevel(logging.WARNING)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)   # строки бота сразу видны и не отстают от логов py-cord
    sys.stdout = StampedOutput(sys.stdout)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
