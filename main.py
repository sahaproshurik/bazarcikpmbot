import asyncio
import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

from cogs.help_cmd import MyHelpCommand

# ── Intents ──────────────────────────────────────────────────
intents = discord.Intents.default()
intents.members         = True
intents.message_content = True
intents.voice_states    = True
intents.guilds          = True

# ── Bot instance ─────────────────────────────────────────────
bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    case_insensitive=True,
    help_command=MyHelpCommand(),
)

# ── Cogs to load ─────────────────────────────────────────────
COGS = [
    "cogs.xp",
    "cogs.economy",
    "cogs.shop",
    "cogs.games",
    "cogs.work",
    "cogs.business",
    "cogs.loans",
    "cogs.moderation",
    "cogs.info",
    "cogs.fun",
    "cogs.petitions",
    "cogs.voice_ai",
    "cogs.mafia",
]

# ── Events ───────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ {bot.user.name}#{bot.user.discriminator} запущен!")
    print(f"   Серверов: {len(bot.guilds)}")

@bot.event
async def on_member_join(member):
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

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Недостаточно прав!", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(
            f"❌ Пропущен аргумент: `{error.param.name}`. Используй `!help {ctx.command}`",
            delete_after=10
        )
    elif isinstance(error, commands.BadArgument):
        await ctx.send(f"❌ Неверный аргумент! Используй `!help {ctx.command}`", delete_after=5)
    elif isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Cooldown! Попробуй через {error.retry_after:.0f}сек.", delete_after=5)
    else:
        print(f"[ERROR] Command '{ctx.command}': {error}")

# ── Entry point ──────────────────────────────────────────────
async def main():
    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                print(f"  ✅ Loaded {cog}")
            except Exception as e:
                print(f"  ❌ Failed to load {cog}: {e}")

        TOKEN = os.getenv("DISCORD_BOT_TOKEN")
        if not TOKEN:
            raise ValueError("DISCORD_BOT_TOKEN не найден в .env файле!")
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
