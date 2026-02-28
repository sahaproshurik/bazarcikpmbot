import nextcord
from nextcord.ext import commands, tasks
from nextcord.ui import View, Button
from nextcord import Interaction
import asyncio
import random
import json
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import time
import pytz
import re

# ============================================================
#  BOT SETUP
# ============================================================
intents = nextcord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, case_insensitive=True)

# ============================================================
#  UNIVERSAL JSON HELPERS
# ============================================================
def load_json(path, default=None):
    if default is None:
        default = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default if not isinstance(default, type) else default()

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ============================================================
#  DATA FILES & GLOBAL STATE
# ============================================================
DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)

FUNDS_FILE      = f"{DATA_DIR}/player_funds.json"
LOANS_FILE      = f"{DATA_DIR}/player_loans.json"
BUSINESS_FILE   = f"{DATA_DIR}/player_businesses.json"
PRIEMER_FILE    = f"{DATA_DIR}/priemer_data.json"
ORDERS_FILE     = f"{DATA_DIR}/orders_completed.json"
XP_FILE         = f"{DATA_DIR}/player_xp.json"
INVENTORY_FILE  = f"{DATA_DIR}/player_inventory.json"
DAILY_FILE      = f"{DATA_DIR}/player_daily.json"
BANK_FILE       = f"{DATA_DIR}/player_bank.json"
SERVER_EFF_FILE = f"{DATA_DIR}/server_effects.json"
WARNS_FILE      = f"{DATA_DIR}/player_warns.json"

player_funds      = load_json(FUNDS_FILE)
player_loans      = load_json(LOANS_FILE)
player_businesses = load_json(BUSINESS_FILE)
priemer_data      = load_json(PRIEMER_FILE)
player_xp         = load_json(XP_FILE)
player_inventory  = load_json(INVENTORY_FILE)
player_daily      = load_json(DAILY_FILE)
player_bank       = load_json(BANK_FILE)
server_effects    = load_json(SERVER_EFF_FILE)
player_warns      = load_json(WARNS_FILE)
USER_ORDERS_COMPLETED = load_json(ORDERS_FILE)

def save_funds():       save_json(FUNDS_FILE, player_funds)
def save_loans():       save_json(LOANS_FILE, player_loans)
def save_businesses():  save_json(BUSINESS_FILE, player_businesses)
def save_priemer():     save_json(PRIEMER_FILE, priemer_data)
def save_xp():          save_json(XP_FILE, player_xp)
def save_inventory():   save_json(INVENTORY_FILE, player_inventory)
def save_daily():       save_json(DAILY_FILE, player_daily)
def save_bank():        save_json(BANK_FILE, player_bank)
def save_server_eff():  save_json(SERVER_EFF_FILE, server_effects)
def save_warns():       save_json(WARNS_FILE, player_warns)

# ============================================================
#  LOAD TEXT FILES
# ============================================================
def load_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line for line in f.read().splitlines() if line.strip()]
    except FileNotFoundError:
        return ["Файл не найден."]

jokes       = load_text_file("jokes.txt")
predictions = load_text_file("predictions.txt")

# ============================================================
#  PLAYER INIT
# ============================================================
async def init_player(uid_or_ctx):
    uid = str(uid_or_ctx.author.id) if hasattr(uid_or_ctx, "author") else str(uid_or_ctx)
    if uid not in player_funds:
        player_funds[uid] = 1000
        save_funds()
    if uid not in player_bank:
        player_bank[uid] = 0
        save_bank()

async def init_player_funds(ctx):
    await init_player(ctx)

# ============================================================
#  XP / LEVEL SYSTEM
# ============================================================
XP_PER_MESSAGE  = (2, 8)
XP_CD: dict     = {}      # uid -> last xp timestamp

def xp_for_level(lvl: int) -> int:
    return int(100 * (lvl ** 1.5))

def get_level(total_xp: int):
    lvl = 1
    xp  = total_xp
    while xp >= xp_for_level(lvl):
        xp -= xp_for_level(lvl)
        lvl += 1
    return lvl, xp

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    uid = str(message.author.id)
    now = time.time()
    if now - XP_CD.get(uid, 0) >= 60:
        gain = random.randint(*XP_PER_MESSAGE)
        player_xp[uid] = player_xp.get(uid, 0) + gain
        XP_CD[uid] = now
        save_xp()
        # Level-up check
        old_lvl, _ = get_level(player_xp[uid] - gain)
        new_lvl, _ = get_level(player_xp[uid])
        if new_lvl > old_lvl:
            try:
                await message.channel.send(
                    f"🎉 {message.author.mention} достиг **{new_lvl} уровня**!",
                    delete_after=10
                )
            except Exception:
                pass
    await bot.process_commands(message)

@bot.command(
    name="level",
    brief="Показать уровень и XP",
    help=(
        "Показывает текущий уровень, количество XP и прогресс до следующего уровня.\n\n"
        "XP начисляется автоматически за сообщения (2–8 XP каждые 60 секунд).\n\n"
        "**Использование:**\n"
        "`!level` — твой уровень\n"
        "`!level @user` — уровень другого игрока\n\n"
        "**Формула:**\n"
        "XP для уровня N = 100 × N^1.5"
    )
)
async def show_level(ctx, member: nextcord.Member = None):
    await ctx.message.delete()
    if member is None:
        member = ctx.author
    uid       = str(member.id)
    total     = player_xp.get(uid, 0)
    lvl, cur  = get_level(total)
    needed    = xp_for_level(lvl)
    bar_fill  = int((cur / needed) * 20) if needed else 20
    bar       = "█" * bar_fill + "░" * (20 - bar_fill)
    embed = nextcord.Embed(title=f"📊 Уровень {member.display_name}", color=nextcord.Color.purple())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="⭐ Уровень", value=str(lvl), inline=True)
    embed.add_field(name="✨ Всего XP", value=str(total), inline=True)
    embed.add_field(name="📈 Прогресс", value=f"`[{bar}]` {cur}/{needed}", inline=False)
    await ctx.send(embed=embed)

# ============================================================
#  ECONOMY HELPERS
# ============================================================
TAX_THRESHOLD = 20000

def calculate_tax(profit: int) -> int:
    return int(profit * 0.18) if profit > TAX_THRESHOLD else 0

# ============================================================
#  MONEY COMMANDS
# ============================================================
@bot.command(
    name="money",
    brief="Проверить баланс",
    help=(
        "Показывает твой текущий баланс: наличные, деньги в банке и суммарный капитал.\n\n"
        "**Использование:**\n"
        "`!money`\n\n"
        "**Что отображается:**\n"
        "💰 Наличные — деньги «на руках» (используются в играх, магазине, переводах)\n"
        "🏦 Банк — деньги в банке (безопасно хранятся, недоступны для ограблений)\n"
        "💎 Всего — наличные + банк"
    )
)
async def check_funds(ctx):
    await ctx.message.delete()
    await init_player(ctx)
    uid  = str(ctx.author.id)
    cash = player_funds.get(uid, 0)
    bank = player_bank.get(uid, 0)
    embed = nextcord.Embed(title=f"💼 Баланс {ctx.author.display_name}", color=nextcord.Color.gold())
    embed.add_field(name="💰 Наличные", value=f"{cash:,}", inline=True)
    embed.add_field(name="🏦 Банк",     value=f"{bank:,}",  inline=True)
    embed.add_field(name="💎 Всего",    value=f"{cash+bank:,}", inline=True)
    embed.set_thumbnail(url=ctx.author.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command(
    name="pay",
    brief="Перевести деньги другому игроку",
    help=(
        "Переводит указанную сумму из твоих наличных другому игроку.\n\n"
        "**Использование:**\n"
        "`!pay @user <сумма>`\n\n"
        "**Пример:**\n"
        "`!pay @Vasya 5000` — перевести Васе 5000 монет\n\n"
        "**Ограничения:**\n"
        "• Сумма должна быть больше 0\n"
        "• Необходимо иметь достаточно наличных\n"
        "• Деньги снимаются с наличных (не из банка)"
    )
)
async def pay(ctx, member: nextcord.Member, amount: int):
    await ctx.message.delete()
    sender   = str(ctx.author.id)
    receiver = str(member.id)
    if amount <= 0:
        await ctx.send(f"{ctx.author.mention}, сумма должна быть > 0!", delete_after=5)
        return
    if player_funds.get(sender, 0) < amount:
        await ctx.send(f"{ctx.author.mention}, недостаточно средств!", delete_after=5)
        return
    player_funds[sender] -= amount
    player_funds[receiver] = player_funds.get(receiver, 0) + amount
    save_funds()
    await ctx.send(f"💸 {ctx.author.mention} перевёл **{amount:,}** 💰 → {member.mention}")

@bot.command(
    name="deposit",
    brief="Положить деньги в банк",
    help=(
        "Переводит наличные деньги на банковский счёт. Деньги в банке защищены от ограблений.\n\n"
        "**Использование:**\n"
        "`!deposit <сумма>`\n\n"
        "**Пример:**\n"
        "`!deposit 10000` — положить 10 000 монет в банк\n\n"
        "**Совет:**\n"
        "Храни большие суммы в банке, чтобы их не украли при ограблении (`!rob`)."
    )
)
async def deposit(ctx, amount: int):
    await ctx.message.delete()
    await init_player(ctx)
    uid = str(ctx.author.id)
    if amount <= 0 or player_funds.get(uid, 0) < amount:
        await ctx.send("❌ Неверная сумма или недостаточно наличных!", delete_after=5)
        return
    player_funds[uid] -= amount
    player_bank[uid]   = player_bank.get(uid, 0) + amount
    save_funds(); save_bank()
    await ctx.send(f"🏦 {ctx.author.mention} внёс **{amount:,}** в банк. Банк: **{player_bank[uid]:,}** 💰")

@bot.command(
    name="withdraw",
    brief="Снять деньги из банка",
    help=(
        "Снимает деньги с банковского счёта в наличные.\n\n"
        "**Использование:**\n"
        "`!withdraw <сумма>`\n\n"
        "**Пример:**\n"
        "`!withdraw 5000` — снять 5000 монет из банка\n\n"
        "**Внимание:**\n"
        "После снятия деньги становятся наличными и уязвимы для кражи через `!rob`."
    )
)
async def withdraw(ctx, amount: int):
    await ctx.message.delete()
    await init_player(ctx)
    uid = str(ctx.author.id)
    if amount <= 0 or player_bank.get(uid, 0) < amount:
        await ctx.send("❌ Неверная сумма или недостаточно в банке!", delete_after=5)
        return
    player_bank[uid]  -= amount
    player_funds[uid]  = player_funds.get(uid, 0) + amount
    save_funds(); save_bank()
    await ctx.send(f"💰 {ctx.author.mention} снял **{amount:,}** из банка. Наличные: **{player_funds[uid]:,}** 💰")

@bot.command(
    name="top",
    brief="Топ-10 богатейших игроков",
    help=(
        "Показывает таблицу лидеров: 10 игроков с наибольшим капиталом (наличные + банк).\n\n"
        "**Использование:**\n"
        "`!top`\n\n"
        "**Примечание:**\n"
        "Учитывается суммарный капитал — и наличные, и банковский счёт."
    )
)
async def leaderboard(ctx):
    await ctx.message.delete()
    combined = {}
    for uid in set(list(player_funds.keys()) + list(player_bank.keys())):
        combined[uid] = player_funds.get(uid, 0) + player_bank.get(uid, 0)
    top = sorted(combined.items(), key=lambda x: x[1], reverse=True)[:10]
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    lines = []
    for i, (uid, total) in enumerate(top):
        try:
            m = ctx.guild.get_member(int(uid)) or await ctx.guild.fetch_member(int(uid))
            name = m.display_name
        except Exception:
            name = f"<@{uid}>"
        lines.append(f"{medals[i]} **{name}** — {total:,} 💰")
    embed = nextcord.Embed(title="💎 Топ-10 богатейших", color=nextcord.Color.gold(), description="\n".join(lines) or "—")
    await ctx.send(embed=embed)

@bot.command(
    name="toplevel",
    brief="Топ-10 игроков по уровню",
    help=(
        "Показывает таблицу лидеров: 10 игроков с наибольшим уровнем и количеством XP.\n\n"
        "**Использование:**\n"
        "`!toplevel`\n\n"
        "**Как получить XP:**\n"
        "Просто пиши сообщения на сервере — каждые 60 секунд начисляется 2–8 XP."
    )
)
async def top_level(ctx):
    await ctx.message.delete()
    top = sorted(player_xp.items(), key=lambda x: x[1], reverse=True)[:10]
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    lines = []
    for i, (uid, xp) in enumerate(top):
        lvl, _ = get_level(xp)
        try:
            m = ctx.guild.get_member(int(uid)) or await ctx.guild.fetch_member(int(uid))
            name = m.display_name
        except Exception:
            name = f"<@{uid}>"
        lines.append(f"{medals[i]} **{name}** — Lvl {lvl} ({xp:,} XP)")
    embed = nextcord.Embed(title="⭐ Топ-10 по уровням", color=nextcord.Color.blurple(), description="\n".join(lines) or "—")
    await ctx.send(embed=embed)

# ============================================================
#  DAILY BONUS
# ============================================================
DAILY_REWARDS = [500, 750, 1000, 1250, 1500, 2000, 3000]

@bot.command(
    name="daily",
    brief="Получить ежедневный бонус",
    help=(
        "Получи ежедневную награду. Чем дольше серия без пропусков — тем больше бонус!\n\n"
        "**Использование:**\n"
        "`!daily`\n\n"
        "**Награды по дням серии:**\n"
        "День 1: 500 💰\n"
        "День 2: 750 💰\n"
        "День 3: 1 000 💰\n"
        "День 4: 1 250 💰\n"
        "День 5: 1 500 💰\n"
        "День 6: 2 000 💰\n"
        "День 7+: 3 000 💰\n\n"
        "**Правила:**\n"
        "• Можно использовать раз в 24 часа\n"
        "• Если пропустить более 48 часов — серия сбрасывается\n"
        "• При наличии VIP пропуска (`!buy vip_pass`) бонус увеличивается на 50%"
    )
)
async def daily_bonus(ctx):
    await ctx.message.delete()
    await init_player(ctx)
    uid  = str(ctx.author.id)
    now  = datetime.now(timezone.utc)
    data = player_daily.get(uid, {"last": None, "streak": 0})

    if data["last"]:
        last_dt = datetime.fromisoformat(data["last"])
        diff    = (now - last_dt).total_seconds()
        if diff < 86400:
            rem  = int(86400 - diff)
            h, r = divmod(rem, 3600)
            m    = r // 60
            await ctx.send(f"⏳ {ctx.author.mention}, следующий бонус через **{h}ч {m}мин**.", delete_after=10)
            return
        if diff > 172800:
            data["streak"] = 0

    streak  = min(data["streak"] + 1, len(DAILY_REWARDS))
    bonus   = DAILY_REWARDS[streak - 1]
    data["streak"] = streak
    data["last"]   = now.isoformat()
    player_daily[uid]  = data
    player_funds[uid]  = player_funds.get(uid, 0) + bonus
    save_daily(); save_funds()
    await ctx.send(f"🎁 {ctx.author.mention} ежедневный бонус: **+{bonus:,}** 💰 | Серия: **{streak}** 🔥")

# ============================================================
#  ROB
# ============================================================
ROB_CD: dict = {}

@bot.command(
    name="rob",
    brief="Ограбить другого игрока",
    help=(
        "Попытайся ограбить другого игрока и украсть часть его наличных.\n\n"
        "**Использование:**\n"
        "`!rob @user`\n\n"
        "**Механика:**\n"
        "• Шанс успеха: 45%\n"
        "• При успехе: украдешь от 100 до 30% наличных жертвы (не более 5 000)\n"
        "• При провале: заплатишь штраф от 200 до 1 500 монет\n\n"
        "**Ограничения:**\n"
        "• Cooldown: 1 час между ограблениями\n"
        "• Нельзя грабить, если у жертвы меньше 200 наличных\n"
        "• Если у жертвы есть 🛡 Щит (`!buy shield`) — ограбление заблокируется\n"
        "• Деньги в банке украсть невозможно — используй `!deposit`!"
    )
)
async def rob(ctx, member: nextcord.Member):
    await ctx.message.delete()
    await init_player(ctx)
    robber = str(ctx.author.id)
    victim = str(member.id)

    if member.id == ctx.author.id:
        await ctx.send("Нельзя ограбить самого себя!", delete_after=5); return

    victim_inv = player_inventory.get(victim, {})
    if victim_inv.get("shield", 0) > 0:
        victim_inv["shield"] -= 1
        if victim_inv["shield"] == 0:
            del victim_inv["shield"]
        player_inventory[victim] = victim_inv
        save_inventory()
        await ctx.send(f"🛡️ {member.mention} был защищён щитом! {ctx.author.mention} ушёл ни с чем.", delete_after=10)
        return

    now = time.time()
    cd  = ROB_CD.get(robber, 0)
    if now - cd < 3600:
        rem = int(3600 - (now - cd))
        await ctx.send(f"⏳ Следующее ограбление через **{rem//60}мин {rem%60}сек**.", delete_after=10); return

    victim_cash = player_funds.get(victim, 0)
    if victim_cash < 200:
        await ctx.send(f"💸 {member.mention} слишком беден — не стоит рисковать!", delete_after=5); return

    ROB_CD[robber] = now

    if random.random() < 0.45:
        amount = random.randint(100, min(5000, int(victim_cash * 0.3)))
        player_funds[victim]  = victim_cash - amount
        player_funds[robber]  = player_funds.get(robber, 0) + amount
        save_funds()
        await ctx.send(f"🦹 {ctx.author.mention} ограбил {member.mention} на **{amount:,}** 💰!")
    else:
        fine = random.randint(200, 1500)
        player_funds[robber] = max(0, player_funds.get(robber, 0) - fine)
        save_funds()
        await ctx.send(f"👮 {ctx.author.mention} попался и заплатил штраф **{fine:,}** 💰!")

# ============================================================
#  CRIME
# ============================================================
CRIME_CD: dict = {}

@bot.command(
    name="crime",
    brief="Совершить преступление (заработок/риск)",
    help=(
        "Попытайся совершить одно из случайных преступлений и заработать деньги. Есть шанс провала!\n\n"
        "**Использование:**\n"
        "`!crime`\n\n"
        "**Возможные преступления:**\n"
        "• Карманная кража (награда до 800 / штраф до 200)\n"
        "• Угон велосипеда (награда до 1 200 / штраф до 300)\n"
        "• Мошенничество в сети (награда до 2 000 / штраф до 500)\n"
        "• Кража в магазине (награда до 600 / штраф до 150)\n"
        "• Незаконная торговля (награда до 5 000 / штраф до 1 000)\n"
        "• Взлом банкомата (награда до 4 000 / штраф до 800)\n\n"
        "**Механика:**\n"
        "• Шанс провала: 40%\n"
        "• Cooldown: 30 минут"
    )
)
async def crime(ctx):
    await ctx.message.delete()
    await init_player(ctx)
    uid = str(ctx.author.id)
    now = time.time()
    if now - CRIME_CD.get(uid, 0) < 1800:
        rem = int(1800 - (now - CRIME_CD.get(uid, 0)))
        await ctx.send(f"⏳ Следующее преступление через **{rem//60}мин**.", delete_after=10); return
    CRIME_CD[uid] = now

    crimes = [
        ("карманную кражу",        200,  800),
        ("угон велосипеда",        300, 1200),
        ("мошенничество в сети",   500, 2000),
        ("кражу в магазине",       150,  600),
        ("незаконную торговлю",   1000, 5000),
        ("взлом банкомата",        800, 4000),
    ]
    name, fine_max, reward_max = random.choice(crimes)

    if random.random() < 0.4:
        fine = random.randint(fine_max // 2, fine_max)
        player_funds[uid] = max(0, player_funds.get(uid, 0) - fine)
        save_funds()
        await ctx.send(f"👮 {ctx.author.mention} попался на **{name}** и заплатил штраф **{fine:,}** 💰!")
    else:
        reward = random.randint(fine_max, reward_max)
        player_funds[uid] = player_funds.get(uid, 0) + reward
        save_funds()
        await ctx.send(f"😈 {ctx.author.mention} успешно провернул **{name}** и заработал **{reward:,}** 💰!")

# ============================================================
#  SHOP & INVENTORY
# ============================================================
SHOP_ITEMS = {
    "lucky_charm": {"name": "🍀 Амулет удачи",    "price": 5000,  "desc": "+10% к выигрышу в играх (1 день)"},
    "pickaxe":     {"name": "⛏ Кирка",            "price": 3000,  "desc": "+20% к заработку на работе (1 день)"},
    "shield":      {"name": "🛡 Щит",              "price": 4000,  "desc": "Защита от ограбления (1 раз)"},
    "vip_pass":    {"name": "⭐ VIP пропуск",      "price": 50000, "desc": "+50% к ежедневному бонусу (7 дней)"},
    "fishing_rod": {"name": "🎣 Удочка",           "price": 2000,  "desc": "Открывает команду !fish"},
    "bomb":        {"name": "💣 Бомба",            "price": 8000,  "desc": "Украсть от 10% до 30% денег у цели"},
    "lottery_ticket": {"name": "🎟 Лотерейный билет", "price": 500, "desc": "Использовать !lotto для розыгрыша"},
}

@bot.command(
    name="shop",
    brief="Показать магазин предметов",
    help=(
        "Открывает каталог магазина со всеми доступными предметами и их ценами.\n\n"
        "**Использование:**\n"
        "`!shop`\n\n"
        "**Предметы в магазине:**\n"
        "🍀 `lucky_charm` (5 000) — +10% к выигрышу в играх на 1 день\n"
        "⛏ `pickaxe` (3 000) — +20% к заработку на работе `!gb`\n"
        "🛡 `shield` (4 000) — защита от одного ограбления `!rob`\n"
        "⭐ `vip_pass` (50 000) — +50% к ежедневному бонусу на 7 дней\n"
        "🎣 `fishing_rod` (2 000) — открывает доступ к `!fish`\n"
        "💣 `bomb` (8 000) — украсть 10–30% наличных у цели\n"
        "🎟 `lottery_ticket` (500) — участие в лотерее `!lotto`\n\n"
        "Для покупки используй `!buy <id_предмета>`"
    )
)
async def shop(ctx):
    await ctx.message.delete()
    embed = nextcord.Embed(title="🏪 Магазин BAZARCIK_PM", color=nextcord.Color.green())
    for iid, item in SHOP_ITEMS.items():
        embed.add_field(
            name=f"{item['name']} — {item['price']:,} 💰",
            value=f"`!buy {iid}` — {item['desc']}",
            inline=False
        )
    await ctx.send(embed=embed)

@bot.command(
    name="buy",
    brief="Купить предмет из магазина",
    help=(
        "Покупает предмет из магазина за наличные деньги.\n\n"
        "**Использование:**\n"
        "`!buy <id_предмета>`\n\n"
        "**Примеры:**\n"
        "`!buy shield` — купить щит за 4 000 💰\n"
        "`!buy fishing_rod` — купить удочку за 2 000 💰\n"
        "`!buy lottery_ticket` — купить лотерейный билет за 500 💰\n\n"
        "**ID предметов:**\n"
        "`lucky_charm`, `pickaxe`, `shield`, `vip_pass`, `fishing_rod`, `bomb`, `lottery_ticket`\n\n"
        "Посмотри все предметы командой `!shop`"
    )
)
async def buy_shop_item(ctx, item_id: str):
    await ctx.message.delete()
    await init_player(ctx)
    uid = str(ctx.author.id)
    if item_id not in SHOP_ITEMS:
        await ctx.send("❌ Товар не найден. Смотри `!shop`", delete_after=5); return
    item  = SHOP_ITEMS[item_id]
    price = item["price"]
    if player_funds.get(uid, 0) < price:
        await ctx.send(f"❌ Нужно **{price:,}** 💰, у вас **{player_funds.get(uid,0):,}**", delete_after=5); return
    player_funds[uid] -= price
    inv = player_inventory.get(uid, {})
    inv[item_id] = inv.get(item_id, 0) + 1
    player_inventory[uid] = inv
    save_funds(); save_inventory()
    await ctx.send(f"✅ {ctx.author.mention} купил **{item['name']}** за **{price:,}** 💰!")

@bot.command(
    name="inventory",
    brief="Показать свой инвентарь",
    help=(
        "Показывает все предметы в инвентаре указанного игрока (или своём).\n\n"
        "**Использование:**\n"
        "`!inventory` — свой инвентарь\n"
        "`!inventory @user` — инвентарь другого игрока\n\n"
        "**Как использовать предметы:**\n"
        "• 💣 Бомба: `!use bomb @user`\n"
        "• 🎟 Лотерейный билет: `!lotto`\n"
        "• 🛡 Щит: защищает автоматически при ограблении\n"
        "• ⛏ Кирка: работает автоматически при `!gb`\n"
        "• 🎣 Удочка: открывает `!fish`"
    )
)
async def inventory(ctx, member: nextcord.Member = None):
    await ctx.message.delete()
    if member is None:
        member = ctx.author
    uid = str(member.id)
    inv = {k: v for k, v in player_inventory.get(uid, {}).items() if v > 0 and k in SHOP_ITEMS}
    if not inv:
        await ctx.send(f"{member.mention}, инвентарь пуст.", delete_after=5); return
    embed = nextcord.Embed(title=f"🎒 Инвентарь {member.display_name}", color=nextcord.Color.blue())
    for iid, qty in inv.items():
        embed.add_field(name=SHOP_ITEMS[iid]["name"], value=f"x{qty}", inline=True)
    await ctx.send(embed=embed)

@bot.command(
    name="use",
    brief="Использовать предмет из инвентаря",
    help=(
        "Использует активный предмет из инвентаря.\n\n"
        "**Использование:**\n"
        "`!use bomb @user` — взорвать бомбу рядом с игроком, украв 10–30% его наличных\n"
        "`!use lottery_ticket` — перенаправит на команду `!lotto`\n\n"
        "**Примечание:**\n"
        "• 🛡 Щит срабатывает автоматически при ограблении — использовать вручную не нужно\n"
        "• ⛏ Кирка применяется автоматически во время работы `!gb`\n"
        "• 🎣 Удочка открывает команду `!fish` без ручного использования"
    )
)
async def use_item(ctx, item_id: str, member: nextcord.Member = None):
    await ctx.message.delete()
    uid = str(ctx.author.id)
    inv = player_inventory.get(uid, {})

    if inv.get(item_id, 0) <= 0:
        await ctx.send("❌ У вас нет этого предмета!", delete_after=5); return

    if item_id == "bomb":
        if member is None:
            await ctx.send("❌ Укажи цель: `!use bomb @user`", delete_after=5); return
        target = str(member.id)
        amount = int(player_funds.get(target, 0) * random.uniform(0.10, 0.30))
        player_funds[target] = max(0, player_funds.get(target, 0) - amount)
        player_funds[uid]    = player_funds.get(uid, 0) + amount
        inv[item_id] -= 1
        if inv[item_id] == 0: del inv[item_id]
        player_inventory[uid] = inv
        save_funds(); save_inventory()
        await ctx.send(f"💣 {ctx.author.mention} взорвал бомбу рядом с {member.mention} и украл **{amount:,}** 💰!")
    elif item_id == "lottery_ticket":
        await ctx.send("🎟 Используй команду `!lotto` для розыгрыша!", delete_after=5)
    else:
        await ctx.send(f"❌ Предмет `{item_id}` нельзя использовать напрямую.", delete_after=5)

# ============================================================
#  LOTTERY
# ============================================================
LOTTO_POOL: dict = {}
LOTTO_RUNNING: dict = {}

@bot.command(
    name="lotto",
    brief="Добавить билет в общую лотерею",
    help=(
        "Добавляет лотерейный билет из инвентаря в общий пул розыгрыша.\n\n"
        "**Использование:**\n"
        "`!lotto`\n\n"
        "**Как работает:**\n"
        "1. Купи билет в магазине: `!buy lottery_ticket` (500 💰)\n"
        "2. Добавь его в пул: `!lotto`\n"
        "3. Дождись, пока администратор запустит розыгрыш: `!drawlotto`\n"
        "4. Победитель определяется случайно — чем больше билетов, тем выше шанс\n\n"
        "**Приз:** 400 💰 × количество всех билетов в пуле\n\n"
        "**Пример:** 10 билетов в пуле = приз 4 000 💰"
    )
)
async def lottery(ctx):
    await ctx.message.delete()
    await init_player(ctx)
    uid   = str(ctx.author.id)
    gid   = str(ctx.guild.id)
    inv   = player_inventory.get(uid, {})

    if inv.get("lottery_ticket", 0) <= 0:
        await ctx.send(f"{ctx.author.mention}, купи лотерейный билет в `!shop`!", delete_after=5); return

    inv["lottery_ticket"] -= 1
    if inv["lottery_ticket"] == 0:
        del inv["lottery_ticket"]
    player_inventory[uid] = inv
    save_inventory()

    if gid not in LOTTO_POOL:
        LOTTO_POOL[gid] = {}
    LOTTO_POOL[gid][uid] = LOTTO_POOL[gid].get(uid, 0) + 1

    total = sum(LOTTO_POOL[gid].values())
    await ctx.send(f"🎟️ {ctx.author.mention} добавил билет в лотерею! Всего билетов: **{total}**. Розыгрыш через `!drawlotto` (только админ).")

@bot.command(
    name="drawlotto",
    brief="[Админ] Провести розыгрыш лотереи",
    help=(
        "Проводит розыгрыш среди всех участников, внёсших билеты командой `!lotto`.\n\n"
        "**Использование:**\n"
        "`!drawlotto`\n\n"
        "**Только для администраторов!**\n\n"
        "**Механика:**\n"
        "• Каждый участник получает шанс пропорционально количеству своих билетов\n"
        "• Победитель получает приз: 400 💰 × общее число билетов\n"
        "• После розыгрыша пул очищается"
    )
)
@commands.has_permissions(administrator=True)
async def draw_lottery(ctx):
    await ctx.message.delete()
    gid = str(ctx.guild.id)
    if gid not in LOTTO_POOL or not LOTTO_POOL[gid]:
        await ctx.send("🎟 Нет билетов в пуле!", delete_after=5); return

    pool = LOTTO_POOL[gid]
    tickets = []
    for uid, count in pool.items():
        tickets.extend([uid] * count)

    winner_id = random.choice(tickets)
    prize = len(tickets) * 400

    player_funds[winner_id] = player_funds.get(winner_id, 0) + prize
    save_funds()
    LOTTO_POOL[gid] = {}

    try:
        winner = ctx.guild.get_member(int(winner_id)) or await ctx.guild.fetch_member(int(winner_id))
        name = winner.mention
    except Exception:
        name = f"<@{winner_id}>"

    await ctx.send(f"🎉 **ЛОТЕРЕЯ!** Победитель: {name} с призом **{prize:,}** 💰! 🎊")

# ============================================================
#  FISHING
# ============================================================
FISH_CD: dict = {}
FISH_TABLE = [
    ("🐟 Карась",     100,  50),
    ("🐠 Окунь",      200,  35),
    ("🐡 Фугу",       500,  10),
    ("🦈 Акула",     2000,   3),
    ("🦑 Кальмар",    800,  12),
    ("🦐 Креветка",   150,  40),
    ("🗡 Старый меч", 1000,   7),
    ("👢 Сапог",       10,  43),
]

@bot.command(
    name="fish",
    brief="Порыбачить и заработать деньги",
    help=(
        "Забрось удочку и поймай рыбу! Разные уловы приносят разные суммы.\n\n"
        "**Требование:** наличие 🎣 Удочки в инвентаре (`!buy fishing_rod`)\n\n"
        "**Использование:**\n"
        "`!fish`\n\n"
        "**Возможный улов:**\n"
        "🐟 Карась — 100 💰 (часто)\n"
        "🦐 Креветка — 150 💰 (часто)\n"
        "🐠 Окунь — 200 💰 (средне)\n"
        "🐡 Фугу — 500 💰 (редко)\n"
        "🦑 Кальмар — 800 💰 (редко)\n"
        "🗡 Старый меч — 1 000 💰 (очень редко)\n"
        "🦈 Акула — 2 000 💰 (очень редко)\n"
        "👢 Сапог — 10 💰 (нет удачи)\n\n"
        "**Cooldown:** 5 минут между рыбалками"
    )
)
async def fish(ctx):
    await ctx.message.delete()
    await init_player(ctx)
    uid = str(ctx.author.id)

    if player_inventory.get(uid, {}).get("fishing_rod", 0) <= 0:
        await ctx.send(f"{ctx.author.mention}, нужна удочка! Купи в `!shop`.", delete_after=5); return

    now = time.time()
    if now - FISH_CD.get(uid, 0) < 300:
        rem = int(300 - (now - FISH_CD.get(uid, 0)))
        await ctx.send(f"⏳ Следующая рыбалка через **{rem}сек**.", delete_after=10); return

    FISH_CD[uid] = now
    items, weights = zip(*((f[0], f[2]) for f in FISH_TABLE))
    catch   = random.choices(items, weights=weights, k=1)[0]
    reward  = next(f[1] for f in FISH_TABLE if f[0] == catch)
    player_funds[uid] = player_funds.get(uid, 0) + reward
    save_funds()
    await ctx.send(f"🎣 {ctx.author.mention} поймал **{catch}** и получил **{reward}** 💰!")

# ============================================================
#  PROFILE
# ============================================================
@bot.command(
    name="profile",
    brief="Показать профиль игрока",
    help=(
        "Отображает полный профиль игрока: уровень, деньги, варны и другую статистику.\n\n"
        "**Использование:**\n"
        "`!profile` — свой профиль\n"
        "`!profile @user` — профиль другого игрока\n\n"
        "**Что отображается:**\n"
        "⭐ Уровень и суммарный XP\n"
        "💰 Наличные и банковский счёт\n"
        "📦 Показатель Приемер (эффективность на работе)\n"
        "⚠️ Количество предупреждений (варнов)\n"
        "📅 Дата вступления на сервер"
    )
)
async def profile(ctx, member: nextcord.Member = None):
    await ctx.message.delete()
    if member is None:
        member = ctx.author
    await init_player(ctx)
    uid     = str(member.id)
    total   = player_xp.get(uid, 0)
    lvl, _  = get_level(total)
    cash    = player_funds.get(uid, 0)
    bank    = player_bank.get(uid, 0)
    pm      = priemer_data.get(uid, 0)
    warns   = len(player_warns.get(uid, []))

    embed = nextcord.Embed(title=f"👤 Профиль {member.display_name}", color=nextcord.Color.blurple())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="⭐ Уровень",   value=str(lvl),       inline=True)
    embed.add_field(name="✨ Всего XP",  value=f"{total:,}",   inline=True)
    embed.add_field(name="💰 Наличные",  value=f"{cash:,}",    inline=True)
    embed.add_field(name="🏦 Банк",      value=f"{bank:,}",    inline=True)
    embed.add_field(name="📦 Приемер",   value=str(pm),         inline=True)
    embed.add_field(name="⚠️ Варны",     value=str(warns),      inline=True)
    embed.add_field(name="📅 На сервере", value=member.joined_at.strftime("%d.%m.%Y"), inline=True)
    await ctx.send(embed=embed)

# ============================================================
#  GAMES: BLACKJACK
# ============================================================
card_values = {
    "2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,"10":10,
    "J":10,"Q":10,"K":10,"A":11
}
suits = {"hearts":"♥","diamonds":"♦","clubs":"♣","spades":"♠"}

def create_deck():
    deck = [(c, s) for s in suits for c in card_values]
    random.shuffle(deck)
    return deck

def calculate_hand(hand):
    total = sum(card_values[c] for c, _ in hand)
    aces  = sum(1 for c, _ in hand if c == "A")
    while total > 21 and aces:
        total -= 10; aces -= 1
    return total

@bot.command(
    name="bj",
    brief="Сыграть в Блэкджек",
    help=(
        "Классический Блэкджек против дилера. Цель — набрать 21 очко или больше дилера, не перебрав.\n\n"
        "**Использование:**\n"
        "`!bj <ставка>`\n\n"
        "**Пример:**\n"
        "`!bj 1000` — ставка 1 000 монет\n\n"
        "**Правила:**\n"
        "• После раздачи карт выбирай: `!hit` (взять карту) или `!stand` (остановиться)\n"
        "• Дилер берёт карты до тех пор, пока не наберёт 17+\n"
        "• Перебор (>21) — проигрыш\n\n"
        "**Выплаты:**\n"
        "• Блэкджек с первых карт: ×3 ставки\n"
        "• Победа над дилером: ×2 ставки\n"
        "• Ничья: ставка возвращается\n"
        "• При выигрыше >20 000 взимается налог 18%\n\n"
        "**Время на ход:** 60 секунд"
    )
)
async def blackjack(ctx, bet: int):
    await ctx.message.delete()
    await init_player_funds(ctx)
    uid = str(ctx.author.id)

    if bet <= 0 or bet > player_funds.get(uid, 0):
        await ctx.send("❌ Неверная ставка!", delete_after=5); return

    player_funds[uid] -= bet
    save_funds()
    deck  = create_deck()
    ph    = [deck.pop(), deck.pop()]
    dh    = [deck.pop(), deck.pop()]

    def fmt(hand):
        return ", ".join(f"{c}{suits[s]}" for c, s in hand)

    await ctx.send(f"🃏 {ctx.author.mention} начал Блэкджек. Ставка: **{bet:,}**")
    await ctx.send(f"Ваши карты: `{fmt(ph)}` (Сумма: **{calculate_hand(ph)}**)")
    await ctx.send(f"Карты дилера: `{ph[0][0]}{suits[ph[0][1]]}` и скрытая.")

    if calculate_hand(ph) == 21:
        w   = bet * 3
        tax = calculate_tax(w - bet)
        player_funds[uid] += w - tax
        save_funds()
        await ctx.send(f"🎉 **БЛЭКДЖЕК!** {ctx.author.mention} выиграл **{w-tax:,}** 💰!")
        return

    while calculate_hand(ph) < 21:
        await ctx.send("👉 `!hit` — взять карту | `!stand` — остановиться")
        def check(m):
            return (m.author == ctx.author and m.channel == ctx.channel
                    and m.content.lower() in ["!hit", "!stand"])
        try:
            msg = await bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send(f"{ctx.author.mention}, время вышло — стенд.", delete_after=5)
            break
        await msg.delete()
        if msg.content.lower() == "!hit":
            ph.append(deck.pop())
            t = calculate_hand(ph)
            await ctx.send(f"Карта: `{ph[-1][0]}{suits[ph[-1][1]]}` → Сумма: **{t}**")
            if t > 21:
                await ctx.send(f"💥 {ctx.author.mention} перебор! Баланс: **{player_funds[uid]:,}** 💰")
                return
        else:
            break

    while calculate_hand(dh) < 17:
        dh.append(deck.pop())
    await ctx.send(f"Карты дилера: `{fmt(dh)}` (Сумма: **{calculate_hand(dh)}**)")

    pt, dt = calculate_hand(ph), calculate_hand(dh)
    if dt > 21 or pt > dt:
        w   = bet * 2
        tax = calculate_tax(w - bet)
        player_funds[uid] += w - tax
        save_funds()
        await ctx.send(f"🏆 {ctx.author.mention} выиграл **{w-tax:,}** 💰! Баланс: **{player_funds[uid]:,}**")
    elif pt < dt:
        await ctx.send(f"😞 {ctx.author.mention} проиграл. Баланс: **{player_funds[uid]:,}** 💰")
    else:
        player_funds[uid] += bet
        save_funds()
        await ctx.send(f"🤝 Ничья! Ставка возвращена. Баланс: **{player_funds[uid]:,}** 💰")

# ============================================================
#  GAMES: FLIP
# ============================================================
@bot.command(
    name="flip",
    brief="Подбросить монетку на ставку",
    help=(
        "Классическая игра «орёл или решка». Угадай — удвоишь ставку!\n\n"
        "**Использование:**\n"
        "`!flip <ставка> <орел/решка>`\n\n"
        "**Примеры:**\n"
        "`!flip 500 о` — ставка 500 монет на орла\n"
        "`!flip 1000 р` — ставка 1000 монет на решку\n\n"
        "**Варианты выбора:**\n"
        "Орёл: `о`, `орел`, `o`, `orel`\n"
        "Решка: `р`, `решка`, `p`, `reshka`\n\n"
        "**Выплата при победе:** ×2 ставки (с налогом 18% при выигрыше >20 000)"
    )
)
async def flip(ctx, bet: int, choice: str):
    await ctx.message.delete()
    await init_player_funds(ctx)
    uid = str(ctx.author.id)

    if bet <= 0 or bet > player_funds.get(uid, 0):
        await ctx.send("❌ Неверная ставка!", delete_after=5); return

    choice_low = choice.strip().lower()
    orly  = ["о","орел","o","orel"]
    rshka = ["р","решка","p","reshka"]
    if choice_low not in orly + rshka:
        await ctx.send("Выбери **Орёл** (о) или **Решка** (р).", delete_after=5); return

    chosen = "Орёл" if choice_low in orly else "Решка"
    player_funds[uid] -= bet
    result = random.choice(["Орёл", "Решка"])
    save_funds()

    if result == chosen:
        w   = bet * 2
        tax = calculate_tax(w - bet)
        player_funds[uid] += w - tax
        save_funds()
        await ctx.send(f"🪙 {ctx.author.mention} выпал **{result}**! Выигрыш: **{w-tax:,}** 💰")
    else:
        await ctx.send(f"🪙 {ctx.author.mention} выпал **{result}**. Проигрыш! Баланс: **{player_funds[uid]:,}** 💰")

# ============================================================
#  GAMES: SLOTS
# ============================================================
@bot.command(
    name="spin",
    brief="Сыграть в слоты",
    help=(
        "Крути барабаны! Совпади символы и сорви джекпот.\n\n"
        "**Использование:**\n"
        "`!spin <ставка>`\n\n"
        "**Пример:**\n"
        "`!spin 2000` — ставка 2 000 монет\n\n"
        "**Выплаты:**\n"
        "🎰 Три одинаковых символа (ДЖЕКПОТ): ×5 ставки (налог 18% при >20 000)\n"
        "✨ Два одинаковых символа: ×2 ставки\n"
        "😞 Нет совпадений: проигрыш\n\n"
        "**Символы:** 🍒 🍋 🍉 🍇 🍊 🍍 💎 7️⃣"
    )
)
async def spin(ctx, bet: int):
    await ctx.message.delete()
    await init_player_funds(ctx)
    uid = str(ctx.author.id)

    if bet <= 0 or bet > player_funds.get(uid, 0):
        await ctx.send("❌ Неверная ставка!", delete_after=5); return

    player_funds[uid] -= bet
    symbols = ["🍒","🍋","🍉","🍇","🍊","🍍","💎","7️⃣"]
    result  = [random.choice(symbols) for _ in range(3)]
    await ctx.send(f"🎰 {ctx.author.mention} | **{' | '.join(result)}**")

    unique = len(set(result))
    if unique == 1:
        w   = bet * 5
        tax = calculate_tax(w - bet)
        player_funds[uid] += w - tax
        save_funds()
        await ctx.send(f"🎉 **ДЖЕКПОТ!** Выигрыш: **{w-tax:,}** 💰 Баланс: **{player_funds[uid]:,}**")
    elif unique == 2:
        w = bet * 2
        player_funds[uid] += w
        save_funds()
        await ctx.send(f"✨ Два одинаковых! Выигрыш: **{w:,}** 💰 Баланс: **{player_funds[uid]:,}**")
    else:
        save_funds()
        await ctx.send(f"😞 Нет совпадений. Баланс: **{player_funds[uid]:,}** 💰")

# ============================================================
#  GAMES: DICE
# ============================================================
@bot.command(
    name="dice",
    brief="Угадать число на кубике",
    help=(
        "Брось кубик и угадай, какое число выпадет. Угадаешь — выиграешь ×5!\n\n"
        "**Использование:**\n"
        "`!dice <ставка> <число 1-6>`\n\n"
        "**Примеры:**\n"
        "`!dice 500 3` — ставка 500, загадал число 3\n"
        "`!dice 1000 6` — ставка 1000, загадал число 6\n\n"
        "**Выплата при победе:** ×5 ставки\n"
        "**Шанс выигрыша:** 1 из 6 (~16.7%)"
    )
)
async def dice_game(ctx, bet: int, number: int):
    await ctx.message.delete()
    await init_player_funds(ctx)
    uid = str(ctx.author.id)

    if not 1 <= number <= 6:
        await ctx.send("Число от 1 до 6!", delete_after=5); return
    if bet <= 0 or bet > player_funds.get(uid, 0):
        await ctx.send("❌ Неверная ставка!", delete_after=5); return

    player_funds[uid] -= bet
    roll   = random.randint(1, 6)
    faces  = {1:"⚀",2:"⚁",3:"⚂",4:"⚃",5:"⚄",6:"⚅"}
    save_funds()

    if roll == number:
        w = bet * 5
        player_funds[uid] += w
        save_funds()
        await ctx.send(f"🎲 {ctx.author.mention} выпало **{faces[roll]}** — УГАДАЛ! Выигрыш: **{w:,}** 💰!")
    else:
        await ctx.send(f"🎲 {ctx.author.mention} выпало **{faces[roll]}** (загадал {number}). Проигрыш! Баланс: **{player_funds[uid]:,}**")

# ============================================================
#  GAMES: ROULETTE
# ============================================================
REDS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

@bot.command(
    name="roulette",
    brief="Сыграть в рулетку",
    help=(
        "Поставь на цвет или число в рулетке. Чем рискованнее ставка — тем больше выигрыш!\n\n"
        "**Использование:**\n"
        "`!roulette <ставка> <выбор>`\n\n"
        "**Варианты ставок:**\n"
        "`red` — на красный (×2 при победе)\n"
        "`black` — на чёрный (×2 при победе)\n"
        "`green` — на зелёный/0 (×14 при победе)\n"
        "`<число 0-36>` — на конкретное число (×35 при победе)\n\n"
        "**Примеры:**\n"
        "`!roulette 1000 red` — ставка 1000 на красный\n"
        "`!roulette 500 17` — ставка 500 на число 17\n"
        "`!roulette 200 green` — ставка 200 на зелёный (число 0)\n\n"
        "**Шансы:**\n"
        "Красный/Чёрный: 18/37 (~48.6%)\n"
        "Зелёный: 1/37 (~2.7%)\n"
        "Конкретное число: 1/37 (~2.7%)"
    )
)
async def roulette(ctx, bet: int, choice: str):
    await ctx.message.delete()
    await init_player_funds(ctx)
    uid = str(ctx.author.id)

    if bet <= 0 or bet > player_funds.get(uid, 0):
        await ctx.send("❌ Неверная ставка!", delete_after=5); return

    number = random.randint(0, 36)
    color  = "green" if number == 0 else ("red" if number in REDS else "black")
    cemj   = {"red":"🔴","black":"⚫","green":"🟢"}[color]

    player_funds[uid] -= bet
    won = 0
    ch  = choice.lower()

    if   ch == "red"   and color == "red":   won = bet * 2
    elif ch == "black" and color == "black": won = bet * 2
    elif ch == "green" and color == "green": won = bet * 14
    elif ch.isdigit():
        if int(ch) == number:
            won = bet * 35
    else:
        player_funds[uid] += bet
        save_funds()
        await ctx.send("❌ Выбор: red / black / green / число 0-36", delete_after=5); return

    player_funds[uid] += won
    save_funds()

    if won:
        await ctx.send(f"🎡 {ctx.author.mention} Выпало **{number}** {cemj} — ВЫИГРЫШ **{won:,}** 💰! Баланс: **{player_funds[uid]:,}**")
    else:
        await ctx.send(f"🎡 {ctx.author.mention} Выпало **{number}** {cemj}. Проигрыш! Баланс: **{player_funds[uid]:,}** 💰")

# ============================================================
#  WORK SYSTEM
# ============================================================
SPORT_ITEMS_WITH_BRANDS = {
    "GymBeam":           ["Протеиновый батончик","Креатин","BCAA","Коллаген"],
    "BeastPink":         ["Лосины","Спортивные шорты","Шейкер"],
    "VanaVita":          ["Гейнер","Витамины B","Коллаген для суставов"],
    "XBEAM":             ["Ремни для жима","Фитнес-трекеры","Протеиновые батончики"],
    "STRIX":             ["Энергетические гели","Силовые тренажеры"],
    "BSN":               ["Гейнер","Креатин моногидрат","БЦАА"],
    "Muscletech":        ["Гейнер","Креатин моногидрат","Протеиновые батончики"],
    "NOW Foods":         ["Омега-3","Витамин C","Л-карнитин"],
    "The Protein Works": ["Протеиновый коктейль","Шейкер","Гейнер"],
    "Universal":         ["Гейнер","Протеиновый коктейль","Креатин"],
}

ORDERS: dict        = {}
ORDER_MESSAGES: dict = {}
order_history: dict  = {}

def generate_order():
    n = random.randint(1, 30)
    positions = []
    for _ in range(n):
        brand    = random.choice(list(SPORT_ITEMS_WITH_BRANDS.keys()))
        item     = random.choice(SPORT_ITEMS_WITH_BRANDS[brand])
        location = f"3{random.choice('BC')}{random.randint(1,56)}{random.choice('ABCDEFGHJ')}{random.randint(1,4)}"
        positions.append({"location": location, "item": f"{brand} - {item}", "status": "не выполнено"})
    return positions

# ---- PickingView ----
class PickingView(View):
    def __init__(self, user_id: str):
        super().__init__(timeout=None)
        self.user_id  = str(user_id)
        self._picking = False

        self.pick_btn = Button(label="Skenovat' produkt", style=nextcord.ButtonStyle.green)
        self.pick_btn.callback = self._pick

        self.exit_btn = Button(label="Выйти с работы", style=nextcord.ButtonStyle.red, disabled=True)
        self.exit_btn.callback = self._exit

        self.add_item(self.pick_btn)
        self.add_item(self.exit_btn)

    async def _pick(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        uid = self.user_id
        if uid not in ORDERS:
            await interaction.response.send_message("Нет активного заказа!", ephemeral=True); return
        if self._picking:
            await interaction.response.send_message("Подождите!", ephemeral=True); return

        await interaction.response.defer()
        self._picking = True

        positions = [p for p in ORDERS[uid] if p["status"] == "не выполнено"]
        if not positions:
            self._picking = False
            await self._switch_to_finish(interaction); return

        if random.random() < 0.03:
            self.pick_btn.disabled = True
            wait = random.randint(30, 180)
            for r in range(wait, 0, -15):
                try:
                    await interaction.message.edit(
                        content=f"{interaction.user.mention}, ошибка телефона — ждём сапорта. Ожидание: {r}с.", view=self)
                except Exception: pass
                await asyncio.sleep(15)
            self.pick_btn.disabled = False
            self._picking = False
            await interaction.message.edit(content=f"{interaction.user.mention}, продолжай пикинг.", view=self)
            return

        num = random.randint(1, 5)
        picked = 0
        for p in ORDERS[uid]:
            if p["status"] == "не выполнено" and picked < num:
                p["status"] = "выполнено"; picked += 1

        done  = [f"✅ ~~{i+1}. {p['location']} ({p['item']})~~"
                 for i, p in enumerate(ORDERS[uid]) if p["status"] == "выполнено"]
        todo  = [f"{i+1}. {p['location']} ({p['item']})"
                 for i, p in enumerate(ORDERS[uid]) if p["status"] == "не выполнено"]

        content = f"{interaction.user.mention}\n" + "\n".join(done[-10:]) + "\n\n" + "\n".join(todo[:20])
        if len(content) > 1950: content = content[:1950] + "..."

        remaining = [p for p in ORDERS[uid] if p["status"] == "не выполнено"]
        if not remaining:
            self._picking = False
            await self._switch_to_finish(interaction)
        else:
            delay = random.randint(1, 4)
            self.pick_btn.disabled = True
            try: await interaction.message.edit(content=content, view=self)
            except Exception: pass
            await asyncio.sleep(delay)
            self.pick_btn.disabled = False
            self._picking = False
            try: await interaction.message.edit(view=self)
            except Exception: pass

    async def _switch_to_finish(self, interaction: Interaction):
        self.clear_items()
        fb = Button(label="Odoslat' objednavku", style=nextcord.ButtonStyle.blurple)
        fb.callback = self._finish
        self.exit_btn.disabled = False
        self.add_item(fb); self.add_item(self.exit_btn)
        try: await interaction.message.edit(content=f"{interaction.user.mention}, все позиции собраны! Отправь заказ.", view=self)
        except Exception: pass

    async def _finish(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        await interaction.response.defer()
        uid = self.user_id
        num = len(ORDERS.get(uid, []))
        if uid not in order_history: order_history[uid] = []
        order_history[uid].append(num)

        pm = priemer_data.get(uid, 0)
        if   pm < 60:  earnings = random.randint(50,    10_000)
        elif pm < 80:  earnings = random.randint(10_000, 20_000)
        elif pm < 120: earnings = random.randint(20_000, 50_000)
        else:          earnings = random.randint(50_000, 100_000)

        if player_inventory.get(uid, {}).get("pickaxe", 0) > 0:
            earnings = int(earnings * 1.2)

        rate        = 0.07 if earnings <= 47000 else 0.19
        tax_amount  = int(earnings * rate)
        net         = earnings - tax_amount

        player_funds[uid] = player_funds.get(uid, 0) + net
        save_funds()
        if uid in ORDERS:        del ORDERS[uid]
        if uid in ORDER_MESSAGES: del ORDER_MESSAGES[uid]

        self.clear_items()
        nb = Button(label="Новый заказ", style=nextcord.ButtonStyle.green)
        nb.callback = self._new_order
        self.exit_btn.disabled = False
        self.add_item(nb); self.add_item(self.exit_btn)
        try:
            await interaction.message.edit(
                content=(f"{interaction.user.mention}, заказ завершён!\n"
                         f"Начислено: **{earnings:,}** | Налог: **{tax_amount:,}** | Итого: **{net:,}** 💰\n"
                         f"Приемер: **{pm}**"),
                view=self)
        except Exception: pass

    async def _new_order(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        await interaction.response.defer()
        uid = self.user_id
        ORDERS[uid] = generate_order()
        priemer_data[uid] = priemer_data.get(uid, 0)
        save_priemer()

        pickup = "\n".join(f"{i+1}. {o['location']} ({o['item']})" for i,o in enumerate(ORDERS[uid]))
        if len(pickup) > 1800: pickup = pickup[:1800] + "..."
        nv  = PickingView(uid)
        msg = await interaction.channel.send(
            f"{interaction.user.mention}, новый заказ **{len(ORDERS[uid])}** позиций. Приемер: **{priemer_data[uid]}**\n\n**Пикап лист:**\n{pickup}",
            view=nv)
        ORDER_MESSAGES[uid] = msg.id
        try: await interaction.message.delete()
        except Exception: pass

    async def _exit(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        uid = self.user_id
        ORDERS.pop(uid, None); ORDER_MESSAGES.pop(uid, None)
        await interaction.message.edit(content=f"{interaction.user.mention}, вы вышли с работы.", view=None)

# ---- PackingView ----
class PackingView(View):
    def __init__(self, user_id: str, order_size: int):
        super().__init__(timeout=None)
        self.user_id       = str(user_id)
        self.order_size    = order_size
        self.remaining     = order_size
        self.selected_box  = None

        box_map = {"A":range(1,7),"B":range(7,13),"C":range(13,19),"D":range(19,25),"E":range(25,31)}
        for box in box_map:
            btn = Button(label=f"Коробка {box}", style=nextcord.ButtonStyle.blurple)
            btn.callback = self._make_cb(box)
            self.add_item(btn)

        self.collect_btn = Button(label="Собрать товар", style=nextcord.ButtonStyle.green, disabled=True)
        self.collect_btn.callback = self._collect

        self.exit_btn = Button(label="Выйти с работы", style=nextcord.ButtonStyle.red, disabled=True)
        self.exit_btn.callback = self._exit

        self.add_item(self.collect_btn)
        self.add_item(self.exit_btn)

    def _make_cb(self, box):
        async def cb(interaction: Interaction):
            await self._select_box(interaction, box)
        return cb

    async def _select_box(self, interaction: Interaction, box: str):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        box_map = {"A":range(1,7),"B":range(7,13),"C":range(13,19),"D":range(19,25),"E":range(25,31)}
        if self.order_size not in box_map[box]:
            await interaction.response.send_message(
                f"Коробка **{box}** не подходит для {self.order_size} товаров! Выбери правильную.", ephemeral=True); return
        self.selected_box          = box
        self.collect_btn.disabled  = False
        await interaction.message.edit(
            content=f"{interaction.user.mention}, коробка **{box}** выбрана. Осталось: **{self.remaining}** товаров.", view=self)

    async def _collect(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        if self.remaining > 0:
            self.remaining -= random.randint(1, min(5, self.remaining))
            if self.remaining > 0:
                await interaction.message.edit(
                    content=f"{interaction.user.mention}, осталось: **{self.remaining}** товаров.", view=self)
            else:
                await self._complete(interaction)

    async def _complete(self, interaction: Interaction):
        uid      = self.user_id
        earnings = random.randint(50, 10_000)
        player_funds[uid] = player_funds.get(uid, 0) + earnings
        save_funds()
        if uid in ORDERS: del ORDERS[uid]

        self.clear_items()
        self.exit_btn.disabled = False
        nb = Button(label="Новый заказ", style=nextcord.ButtonStyle.green)
        nb.callback = self._new_order
        self.add_item(nb); self.add_item(self.exit_btn)
        await interaction.message.edit(
            content=f"{interaction.user.mention}, баление завершено! Заработано: **{earnings:,}** 💰", view=self)

    async def _new_order(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        ns  = random.randint(1, 30)
        nv  = PackingView(self.user_id, ns)
        await interaction.message.edit(
            content=f"{interaction.user.mention}, новый заказ: **{ns}** товаров. Выберите коробку.", view=nv)

    async def _exit(self, interaction: Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True); return
        uid = self.user_id
        ORDERS.pop(uid, None); ORDER_MESSAGES.pop(uid, None)
        await interaction.message.edit(content=f"{interaction.user.mention}, вы вышли с работы.", view=None)

# ---- GB command ----
@bot.command(
    name="gb",
    brief="Пойти работать на склад",
    help=(
        "Начни рабочую смену на складе GymBeam. Случайно попадёшь на один из двух видов работы.\n\n"
        "**Использование:**\n"
        "`!gb`\n\n"
        "**Виды работы:**\n\n"
        "📦 **Пикинг** — сбор товаров по складу:\n"
        "• Нажимай кнопку **Skenovat' produkt** для сканирования позиций\n"
        "• Собери все позиции из пикап-листа\n"
        "• Нажми **Odoslat' objednavku** для отправки заказа\n"
        "• Изредка возникает «ошибка телефона» — просто подожди\n\n"
        "📦 **Баление** — упаковка товаров:\n"
        "• Выбери правильный размер коробки (A–E) под количество товаров\n"
        "• Коробки A: 1–6 товаров, B: 7–12, C: 13–18, D: 19–24, E: 25–30\n"
        "• Нажимай **Собрать товар** до завершения\n\n"
        "**Заработок зависит от Приемера (`!priemer`):**\n"
        "Приемер < 60: 50 — 10 000 💰\n"
        "Приемер 60–79: 10 000 — 20 000 💰\n"
        "Приемер 80–119: 20 000 — 50 000 💰\n"
        "Приемер 120+: 50 000 — 100 000 💰\n\n"
        "**Бонус:** ⛏ Кирка (`!buy pickaxe`) даёт +20% к заработку\n"
        "**Налог:** 7% (до 47 000) или 19% (свыше 47 000)"
    )
)
async def start_job(ctx):
    await ctx.message.delete()
    await init_player(ctx)
    uid = str(ctx.author.id)
    job = random.choice(["пикинг", "баление"])

    if job == "пикинг":
        ORDERS[uid]           = generate_order()
        priemer_data[uid]     = priemer_data.get(uid, 0)
        save_priemer()

        pickup = "\n".join(f"{i+1}. {o['location']} ({o['item']})" for i,o in enumerate(ORDERS[uid]))
        if len(pickup) > 1800: pickup = pickup[:1800] + "..."

        view = PickingView(uid)
        msg  = await ctx.send(
            f"{ctx.author.mention} 📦 Работа: **пикинг** | Заказ: **{len(ORDERS[uid])}** позиций | Приемер: **{priemer_data[uid]}**\n\n**Пикап лист:**\n{pickup}",
            view=view)
        ORDER_MESSAGES[uid] = msg.id

    else:
        order_size = random.randint(1, 30)
        ORDERS[uid] = [{"item": random.choice(random.choice(list(SPORT_ITEMS_WITH_BRANDS.values())))} for _ in range(order_size)]
        view = PackingView(uid, order_size)
        msg  = await ctx.send(
            f"{ctx.author.mention} 📦 Работа: **баление** | Заказ: **{order_size}** товаров. Выберите коробку.",
            view=view)
        ORDER_MESSAGES[uid] = msg.id

@bot.command(
    name="priemer",
    brief="Посмотреть показатель эффективности работы",
    help=(
        "Показывает твой текущий Приемер — показатель эффективности на работе в GymBeam.\n\n"
        "**Использование:**\n"
        "`!priemer`\n\n"
        "**Что такое Приемер:**\n"
        "Это показатель продуктивности (0–150), который влияет на твой заработок при работе `!gb`.\n\n"
        "**Статусы:**\n"
        "🔴 Низкий (0–59): заработок 50 — 10 000 💰\n"
        "🟡 Средний (60–79): заработок 10 000 — 20 000 💰\n"
        "🟢 Высокий (80–119): заработок 20 000 — 50 000 💰\n"
        "💎 Максимум (120–150): заработок 50 000 — 100 000 💰\n\n"
        "**Как повышается:**\n"
        "Приемер растёт автоматически при выполнении заказов. Если долго не работать — постепенно снижается."
    )
)
async def priemer_cmd(ctx):
    await ctx.message.delete()
    uid = str(ctx.author.id)
    pm  = priemer_data.get(uid, 0)
    embed = nextcord.Embed(title=f"📦 Приемер {ctx.author.display_name}", color=nextcord.Color.orange())
    bar_fill = int((pm / 150) * 20)
    bar = "█" * bar_fill + "░" * (20 - bar_fill)
    embed.add_field(name="Приемер",   value=f"{pm}/150")
    embed.add_field(name="Прогресс",  value=f"`[{bar}]`")
    lv = "🔴 Низкий" if pm < 60 else ("🟡 Средний" if pm < 80 else ("🟢 Высокий" if pm < 120 else "💎 Максимум"))
    embed.add_field(name="Статус", value=lv)
    await ctx.send(embed=embed)

async def update_priemer():
    decay_counter = 0
    while True:
        await asyncio.sleep(60)
        decay_counter += 1
        for uid in list(priemer_data.keys()):
            orders = order_history.get(uid, [])
            if orders:
                avg_o   = len(orders)
                avg_pos = sum(orders) / avg_o
                priemer_data[uid] = int(min(150, priemer_data[uid] + (avg_o * avg_pos) / 10))
            elif decay_counter >= 60:
                priemer_data[uid] = int(max(0, priemer_data[uid] - 1))
        if decay_counter >= 60:
            decay_counter = 0
        save_priemer()
        order_history.clear()

# ============================================================
#  BUSINESS SYSTEM
# ============================================================
business_types = {
    "Киоск с едой":      {"base_cost":200,  "base_profit":20, "taxes":10, "service_cost":5,  "upgrade_cost":100, "repair_cost":0.20},
    "Автомойка":         {"base_cost":300,  "base_profit":25, "taxes":8,  "service_cost":7,  "upgrade_cost":120, "repair_cost":0.25},
    "Лотерейный магазин":{"base_cost":400,  "base_profit":30, "taxes":12, "service_cost":6,  "upgrade_cost":150, "repair_cost":0.30},
    "Офис IT-услуг":     {"base_cost":500,  "base_profit":40, "taxes":15, "service_cost":10, "upgrade_cost":200, "repair_cost":0.35},
    "Фитнес-клуб":       {"base_cost":350,  "base_profit":28, "taxes":5,  "service_cost":8,  "upgrade_cost":140, "repair_cost":0.15},
}

unique_items_biz = {
    "Киоск с едой":       {"item_name":"Фирменный фургон",      "effect":"increase_speed",          "duration":86400, "description":"Скорость операций +10% на 24ч."},
    "Автомойка":          {"item_name":"Промо-карты",           "effect":"double_profit",            "duration":3600,  "description":"2× прибыль для всех на 1ч."},
    "Лотерейный магазин": {"item_name":"Золотой билет",         "effect":"increase_item_chance",     "duration":86400, "description":"Шанс редких предметов +10% на 24ч."},
    "Офис IT-услуг":      {"item_name":"Виртуальный сервер",    "effect":"speed_up_upgrades",        "duration":86400, "description":"Улучшения ×1.2 скорее на 24ч."},
    "Фитнес-клуб":        {"item_name":"Персональный тренер",   "effect":"increase_event_frequency", "duration":86400, "description":"Событий +10% на 24ч."},
}

business_rewards = {
    "Киоск с едой":"Рекламный щит", "Автомойка":"Книга по менеджменту",
    "Лотерейный магазин":"Лотерейные билеты", "Офис IT-услуг":"Рабочие инструменты",
    "Фитнес-клуб":"Фирменный костюм",
}

def calc_next_biz_cost(uid, base_cost):
    count = len(player_businesses.get(str(uid), []))
    return base_cost if count == 0 else (base_cost * 5 if count == 1 else base_cost * 10)

def is_biz_name_unique(uid, name):
    return all(b["name"] != name for b in player_businesses.get(str(uid), []))

def apply_server_effect(effect: str, duration: int):
    server_effects[effect] = time.time() + duration
    save_server_eff()

def check_active_effects():
    now     = time.time()
    expired = [k for k, v in server_effects.items() if v < now]
    for k in expired: del server_effects[k]
    if expired: save_server_eff()

def _apply_biz_unique(uid: str, btype: str) -> str:
    if btype not in unique_items_biz:
        return "❌ Неизвестный тип бизнеса."
    item = unique_items_biz[btype]
    apply_server_effect(item["effect"], item["duration"])
    return f"🛠 **{item['item_name']}** применён! {item['description']}"

@bot.command(
    name="buy_business",
    brief="Купить бизнес",
    help=(
        "Покупает новый бизнес указанного типа с заданным названием.\n\n"
        "**Использование:**\n"
        '`!buy_business "Тип бизнеса" Моё название`\n\n'
        "**Доступные типы:**\n"
        "• `Киоск с едой` — 200 💰, прибыль 20/день\n"
        "• `Автомойка` — 300 💰, прибыль 25/день\n"
        "• `Лотерейный магазин` — 400 💰, прибыль 30/день\n"
        "• `Офис IT-услуг` — 500 💰, прибыль 40/день\n"
        "• `Фитнес-клуб` — 350 💰, прибыль 28/день\n\n"
        "**Примеры:**\n"
        '`!buy_business Автомойка МойАвто`\n\n'
        "**Ограничения:**\n"
        "• Максимум 3 бизнеса на игрока\n"
        "• 2-й бизнес стоит ×5 от базовой цены, 3-й — ×10\n"
        "• Название должно быть уникальным среди твоих бизнесов\n\n"
        "Прибыль выплачивается ежедневно в 20:00 UTC. Подробнее: `!business_info`"
    )
)
async def buy_business(ctx, business_name: str, *, custom_name: str):
    await ctx.message.delete()
    uid = str(ctx.author.id)

    if business_name not in business_types:
        blist = ", ".join(business_types.keys())
        await ctx.send(f"❌ Тип не найден! Доступные: {blist}", delete_after=10); return

    if len(player_businesses.get(uid, [])) >= 3:
        await ctx.send("🚫 Максимум 3 бизнеса!", delete_after=5); return

    if not is_biz_name_unique(uid, custom_name):
        await ctx.send(f"❌ Название '{custom_name}' занято.", delete_after=5); return

    base   = business_types[business_name]["base_cost"]
    cost   = calc_next_biz_cost(uid, base)

    if player_funds.get(uid, 0) < cost:
        await ctx.send(f"❌ Нужно **{cost:,}** 💰 (есть **{player_funds.get(uid,0):,}**)", delete_after=5); return

    player_funds[uid] -= cost
    if uid not in player_businesses: player_businesses[uid] = []

    player_businesses[uid].append({
        "name": custom_name, "business_type": business_name,
        "profit": business_types[business_name]["base_profit"],
        "taxes":  business_types[business_name]["taxes"],
        "service_cost": business_types[business_name]["service_cost"],
        "upgraded": False, "upgrade_cost": business_types[business_name]["upgrade_cost"],
        "upgrade_count": 0, "last_upgrade": 0,
    })
    save_funds(); save_businesses()
    await ctx.send(f"✅ Бизнес **{custom_name}** ({business_name}) куплен за **{cost:,}** 💰!")

@bot.command(
    name="sell_business",
    brief="Продать свой бизнес",
    help=(
        "Продаёт один из твоих бизнесов за 70% от базовой стоимости.\n\n"
        "**Использование:**\n"
        "`!sell_business <название>`\n\n"
        "**Пример:**\n"
        "`!sell_business МойКиоск`\n\n"
        "**Важно:**\n"
        "• Продажа необратима — бизнес будет удалён\n"
        "• Выплачивается 70% от базовой цены типа бизнеса (не от потраченного)\n"
        "• Улучшения и вложения в апгрейды не компенсируются\n\n"
        "Посмотреть свои бизнесы: `!businesses`"
    )
)
async def sell_business_cmd(ctx, *, business_name: str):
    await ctx.message.delete()
    uid = str(ctx.author.id)

    for b in player_businesses.get(uid, []):
        if b["name"] == business_name:
            btype = b["business_type"]
            price = int(business_types[btype]["base_cost"] * 0.7)
            player_funds[uid] = player_funds.get(uid, 0) + price
            player_businesses[uid].remove(b)
            save_funds(); save_businesses()
            await ctx.send(f"💰 **{business_name}** продан за **{price:,}** 💰!"); return

    await ctx.send("❌ Бизнес не найден.", delete_after=5)

@bot.command(
    name="upgrade_business",
    brief="Улучшить бизнес для роста прибыли",
    help=(
        "Улучшает бизнес, увеличивая ежедневную прибыль.\n\n"
        "**Использование:**\n"
        "`!upgrade_business <название>`\n\n"
        "**Пример:**\n"
        "`!upgrade_business МояАвтомойка`\n\n"
        "**Механика:**\n"
        "• Стоимость каждого следующего улучшения возрастает в 1.5 раза\n"
        "• Прибыль после улучшения: базовая × (2 - 0.2 × номер улучшения), минимум ×1.2\n"
        "• С шансом 10% при улучшении активируется уникальный серверный эффект типа бизнеса\n\n"
        "**Ограничение:**\n"
        "Улучшать можно не чаще 1 раза в сутки (24 часа)"
    )
)
async def upgrade_business_cmd(ctx, *, business_name: str):
    await ctx.message.delete()
    uid = str(ctx.author.id)

    for b in player_businesses.get(uid, []):
        if b["name"] == business_name:
            if time.time() - b.get("last_upgrade", 0) < 86400:
                await ctx.send("⏳ Улучшать раз в сутки!", delete_after=5); return
            cnt  = b.get("upgrade_count", 0)
            cost = int(business_types[b["business_type"]]["upgrade_cost"] * (1.5 ** cnt))
            mult = max(1.2, 2 - 0.2 * cnt)

            if player_funds.get(uid, 0) < cost:
                await ctx.send(f"❌ Нужно **{cost:,}** 💰", delete_after=5); return

            player_funds[uid] -= cost
            b["profit"]         = int(b["profit"] * mult)
            b["upgrade_count"]  = cnt + 1
            b["last_upgrade"]   = time.time()
            b["upgraded"]       = True

            msg = f"🔧 **{business_name}** улучшен! Прибыль: **{b['profit']}**/день"
            if random.random() < 0.1:
                msg += "\n" + _apply_biz_unique(uid, b["business_type"])

            save_funds(); save_businesses()
            await ctx.send(msg); return

    await ctx.send("❌ Бизнес не найден.", delete_after=5)

@bot.command(
    name="repair_business",
    brief="Отремонтировать бизнес",
    help=(
        "Ремонтирует бизнес, оплачивая стоимость технического обслуживания.\n\n"
        "**Использование:**\n"
        "`!repair_business <название>`\n\n"
        "**Пример:**\n"
        "`!repair_business МойКиоск`\n\n"
        "**Стоимость ремонта:**\n"
        "• Киоск с едой: 40 💰\n"
        "• Автомойка: 75 💰\n"
        "• Лотерейный магазин: 120 💰\n"
        "• Офис IT-услуг: 175 💰\n"
        "• Фитнес-клуб: ~52 💰\n\n"
        "(Считается как base_cost × repair_cost бизнеса)"
    )
)
async def repair_business_cmd(ctx, *, business_name: str):
    await ctx.message.delete()
    uid = str(ctx.author.id)

    for b in player_businesses.get(uid, []):
        if b["name"] == business_name:
            btype = b["business_type"]
            cost  = int(business_types[btype]["base_cost"] * business_types[btype]["repair_cost"])
            if player_funds.get(uid, 0) < cost:
                await ctx.send(f"❌ Нужно **{cost:,}** 💰", delete_after=5); return
            player_funds[uid] -= cost
            save_funds(); save_businesses()
            await ctx.send(f"🔧 **{business_name}** отремонтирован! Стоимость: **{cost:,}** 💰"); return

    await ctx.send("❌ Бизнес не найден.", delete_after=5)

@bot.command(
    name="businesses",
    brief="Список своих бизнесов",
    help=(
        "Показывает все бизнесы указанного игрока (или свои).\n\n"
        "**Использование:**\n"
        "`!businesses` — свои бизнесы\n"
        "`!businesses @user` — бизнесы другого игрока\n\n"
        "**Отображается:**\n"
        "• Название и тип бизнеса\n"
        "• Ежедневная прибыль\n"
        "• Статус (обычный / улучшенный)\n"
        "• Количество улучшений"
    )
)
async def list_businesses(ctx, member: nextcord.Member = None):
    await ctx.message.delete()
    if member is None: member = ctx.author
    uid = str(member.id)

    blist = player_businesses.get(uid, [])
    if not blist:
        await ctx.send(f"{member.mention} не имеет бизнесов.", delete_after=5); return

    embed = nextcord.Embed(title=f"🏢 Бизнесы {member.display_name}", color=nextcord.Color.gold())
    for b in blist:
        status = "⬆️ Улучшен" if b.get("upgraded") else "🔷 Обычный"
        embed.add_field(
            name=f"{b['name']} ({b['business_type']})",
            value=f"💰 {b['profit']}/день | {status} | Ул: {b.get('upgrade_count',0)}",
            inline=False)
    await ctx.send(embed=embed)

@bot.command(
    name="business_info",
    brief="Информация о типах бизнесов",
    help=(
        "Показывает таблицу со всеми доступными типами бизнесов и их характеристиками.\n\n"
        "**Использование:**\n"
        "`!business_info`\n\n"
        "**Отображается для каждого типа:**\n"
        "• Базовая стоимость покупки\n"
        "• Ежедневная прибыль\n"
        "• Ежедневный налог\n"
        "• Стоимость первого улучшения\n\n"
        "Подробный гайд по командам: `!business_help`"
    )
)
async def business_info_cmd(ctx):
    await ctx.message.delete()
    embed = nextcord.Embed(title="📋 Типы бизнесов", color=nextcord.Color.blue())
    for name, d in business_types.items():
        embed.add_field(
            name=f"🏢 {name}",
            value=(f"Стоимость: **{d['base_cost']:,}** 💰\n"
                   f"Прибыль: **{d['base_profit']}**/день\n"
                   f"Налог: {d['taxes']} | Улучшение: {d['upgrade_cost']}"),
            inline=True)
    await ctx.send(embed=embed)

@bot.command(
    name="use_item",
    brief="Применить уникальный эффект бизнеса",
    help=(
        "Применяет уникальный серверный эффект для указанного типа бизнеса.\n\n"
        "**Использование:**\n"
        "`!use_item <тип бизнеса>`\n\n"
        "**Примеры:**\n"
        "`!use_item Автомойка` — активирует Промо-карты (×2 прибыль на 1 час)\n"
        "`!use_item Офис IT-услуг` — активирует Виртуальный сервер\n\n"
        "**Эффекты по типам:**\n"
        "• Киоск с едой → Фирменный фургон (+10% скорость, 24ч)\n"
        "• Автомойка → Промо-карты (×2 прибыль, 1ч)\n"
        "• Лотерейный магазин → Золотой билет (+10% шанс редких предметов, 24ч)\n"
        "• Офис IT-услуг → Виртуальный сервер (улучшения ×1.2 быстрее, 24ч)\n"
        "• Фитнес-клуб → Персональный тренер (+10% событий, 24ч)"
    )
)
async def use_item_biz_cmd(ctx, *, business_type: str):
    await ctx.message.delete()
    uid = str(ctx.author.id)
    await ctx.send(_apply_biz_unique(uid, business_type))

@bot.command(
    name="active_effects",
    brief="Посмотреть активные серверные эффекты",
    help=(
        "Показывает все активные на данный момент серверные эффекты от бизнесов.\n\n"
        "**Использование:**\n"
        "`!active_effects`\n\n"
        "**Эффекты активируются:**\n"
        "• При улучшении бизнеса (10% шанс)\n"
        "• Через команду `!use_item <тип бизнеса>`\n\n"
        "Для каждого эффекта показывается время истечения в UTC."
    )
)
async def active_effects_cmd(ctx):
    await ctx.message.delete()
    check_active_effects()
    if not server_effects:
        await ctx.send("❌ Нет активных эффектов.", delete_after=5); return
    embed = nextcord.Embed(title="🔮 Активные серверные эффекты", color=nextcord.Color.purple())
    for eff, end in server_effects.items():
        dt = datetime.fromtimestamp(end, tz=timezone.utc).strftime("%H:%M:%S UTC")
        embed.add_field(name=eff, value=f"До: {dt}", inline=False)
    await ctx.send(embed=embed)

@bot.command(
    name="business_help",
    brief="Гайд по системе бизнесов",
    help=(
        "Показывает подробный гайд по всем командам системы бизнесов.\n\n"
        "**Использование:**\n"
        "`!business_help`\n\n"
        "**Включает:**\n"
        "• Список всех команд бизнеса\n"
        "• Краткое описание каждой команды\n"
        "• Советы по развитию бизнеса\n\n"
        "Для просмотра типов и цен используй `!business_info`"
    )
)
async def business_help_cmd(ctx):
    await ctx.message.delete()
    try:
        with open("business_help.txt", "r", encoding="utf-8") as f:
            await ctx.send(f.read())
    except FileNotFoundError:
        embed = nextcord.Embed(title="🏢 Помощь по бизнесам", color=nextcord.Color.green())
        cmds  = [
            ("!buy_business <тип> <название>", "Купить бизнес"),
            ("!sell_business <название>",      "Продать бизнес"),
            ("!upgrade_business <название>",   "Улучшить (раз в сутки)"),
            ("!repair_business <название>",    "Отремонтировать"),
            ("!businesses",                    "Мои бизнесы"),
            ("!business_info",                 "Типы и цены"),
            ("!active_effects",                "Серверные эффекты"),
        ]
        for cmd, desc in cmds:
            embed.add_field(name=f"`{cmd}`", value=desc, inline=False)
        await ctx.send(embed=embed)

@tasks.loop(hours=1)
async def daily_business_income():
    if datetime.now(timezone.utc).hour == 20:
        channel = bot.get_channel(1353724972677201980)
        for uid, biznesy in player_businesses.items():
            total = sum(b["profit"] for b in biznesy)
            if total > 0:
                player_funds[uid] = player_funds.get(uid, 0) + total
                if channel:
                    try: await channel.send(f"💼 <@{uid}> получил прибыль от бизнесов: **{total:,}** 💰")
                    except Exception: pass
        save_funds()

@tasks.loop(hours=1)
async def tax_deduction_task():
    if datetime.now(timezone.utc).hour == 19:
        for uid, biznesy in player_businesses.items():
            total_tax = sum(b["taxes"] for b in biznesy)
            if total_tax > 0:
                player_funds[uid] = max(0, player_funds.get(uid, 0) - total_tax)
        save_funds()

@tasks.loop(hours=1)
async def weekend_competition():
    now = datetime.now(timezone.utc)
    if now.weekday() == 6 and now.hour == 23:
        earnings = {uid: sum(b["profit"] for b in blist) for uid, blist in player_businesses.items()}
        top3     = sorted(earnings.items(), key=lambda x: x[1], reverse=True)[:3]
        rewards  = [{"money":500,"upgrades":3},{"money":200,"upgrades":1},{"money":100,"upgrades":0}]
        medals   = ["🥇","🥈","🥉"]
        lines    = ["**🏆 Итоги недельного соревнования бизнесов:**"]

        for i, (uid, profit) in enumerate(top3):
            r = rewards[i]
            player_funds[uid] = player_funds.get(uid, 0) + r["money"]
            if uid in player_businesses:
                for _ in range(r["upgrades"]):
                    if player_businesses[uid]:
                        b = random.choice(player_businesses[uid])
                        b["profit"] = int(b["profit"] * 1.2)
            lines.append(f"{medals[i]} <@{uid}> — {profit:,} прибыли | Приз: {r['money']:,} 💰, улучшений: {r['upgrades']}")

        save_funds(); save_businesses()
        channel = bot.get_channel(1353724972677201980)
        if channel:
            try: await channel.send("\n".join(lines))
            except Exception: pass

# ============================================================
#  LOAN SYSTEM
# ============================================================
async def get_user_age_on_server(ctx, user_id):
    try:
        member = await ctx.guild.fetch_member(user_id)
        if not member or not member.joined_at: return None
        return (datetime.now(pytz.utc) - member.joined_at.astimezone(pytz.utc)).days
    except Exception:
        return None

def get_max_loan(age):
    if age < 30: return 0
    if age < 60: return 100000
    if age < 90: return 300000
    if age < 120: return 500000
    return 1000000

def get_loan_rate(age): return 0.15 if age > 120 else 0.20

def calc_daily_payment(amount, term, rate): return int(amount * (1 + rate) / term)

@bot.command(
    name="applyloan",
    brief="Оформить кредит",
    help=(
        "Оформляет кредит на указанную сумму и срок. Деньги сразу поступают на наличные.\n\n"
        "**Использование:**\n"
        "`!applyloan <сумма> <срок в днях>`\n\n"
        "**Примеры:**\n"
        "`!applyloan 50000 7` — кредит 50 000 на 7 дней\n"
        "`!applyloan 10000 3` — кредит 10 000 на 3 дня\n\n"
        "**Условия по стажу на сервере:**\n"
        "< 30 дней: кредиты недоступны\n"
        "30–59 дней: до 100 000 💰 (ставка 20%)\n"
        "60–89 дней: до 300 000 💰 (ставка 20%)\n"
        "90–119 дней: до 500 000 💰 (ставка 20%)\n"
        "120+ дней: до 1 000 000 💰 (ставка 15%)\n\n"
        "**Срок:** от 1 до 7 дней\n"
        "**Просрочка:** долг удваивается, срок продлевается на 2 дня\n"
        "**Только один активный кредит одновременно**\n\n"
        "Рассчитать платёж заранее: `!calculatecredit`"
    )
)
async def applyloan(ctx, loan_amount: int, loan_term: int):
    await ctx.message.delete()
    uid = str(ctx.author.id)

    if player_loans.get(uid):
        await ctx.send("❌ Уже есть активный кредит!", delete_after=5); return
    if not 1 <= loan_term <= 7:
        await ctx.send("❌ Срок: 1–7 дней.", delete_after=5); return

    age = await get_user_age_on_server(ctx, ctx.author.id)
    if age is None:
        await ctx.send("Не удалось определить время на сервере.", delete_after=5); return
    max_l = get_max_loan(age)
    if max_l == 0:
        await ctx.send("❌ Нужно быть на сервере ≥30 дней.", delete_after=5); return
    if loan_amount > max_l:
        await ctx.send(f"❌ Максимальная сумма: **{max_l:,}** 💰", delete_after=5); return

    rate  = get_loan_rate(age)
    daily = calc_daily_payment(loan_amount, loan_term, rate)
    due   = (datetime.now() + timedelta(days=loan_term)).strftime("%Y-%m-%d")

    player_loans[uid] = [{
        "loan_amount": loan_amount, "interest_rate": rate,
        "daily_payment": daily, "loan_term": loan_term,
        "due_date": due, "paid_amount": 0,
    }]
    player_funds[uid] = player_funds.get(uid, 0) + loan_amount
    save_funds(); save_loans()

    embed = nextcord.Embed(title="✅ Кредит оформлен", color=nextcord.Color.green())
    embed.add_field(name="Сумма",    value=f"{loan_amount:,} 💰")
    embed.add_field(name="Ставка",   value=f"{int(rate*100)}%")
    embed.add_field(name="Срок",     value=f"{loan_term} дней")
    embed.add_field(name="Ежедн.",   value=f"{daily:,} 💰")
    embed.add_field(name="Погасить до", value=due)
    embed.add_field(name="Баланс",   value=f"{player_funds[uid]:,} 💰")
    await ctx.send(ctx.author.mention, embed=embed)

@bot.command(
    name="calculatecredit",
    brief="Рассчитать кредит до оформления",
    help=(
        "Рассчитывает условия кредита — сумму переплаты и ежедневный платёж — не оформляя его.\n\n"
        "**Использование:**\n"
        "`!calculatecredit <сумма> <срок>`\n\n"
        "**Примеры:**\n"
        "`!calculatecredit 50000 7` — расчёт кредита 50 000 на 7 дней\n"
        "`!calculatecredit 10000 3` — расчёт кредита 10 000 на 3 дня\n\n"
        "Показывает: ставку, итоговую сумму с процентами и ежедневный платёж."
    )
)
async def calc_credit(ctx, loan_amount: int, loan_term: int):
    await ctx.message.delete()
    age   = await get_user_age_on_server(ctx, ctx.author.id) or 0
    rate  = get_loan_rate(age)
    daily = calc_daily_payment(loan_amount, loan_term, rate)
    total = int(loan_amount * (1 + rate))
    await ctx.send(
        f"📊 Кредит **{loan_amount:,}** на **{loan_term}** дней\n"
        f"Ставка: **{int(rate*100)}%** | Итого: **{total:,}** | Ежедневно: **{daily:,}** 💰")

@bot.command(
    name="checkloan",
    brief="Посмотреть статус своего кредита",
    help=(
        "Показывает детали активного кредита: остаток, срок, историю оплат.\n\n"
        "**Использование:**\n"
        "`!checkloan`\n\n"
        "**Отображается:**\n"
        "• Сумма кредита и процентная ставка\n"
        "• Итоговая сумма к возврату\n"
        "• Уже оплачено и остаток\n"
        "• Дата погашения и дней до неё\n\n"
        "**Просрочка:**\n"
        "Если срок истёк — долг удвоится и срок продлится на 2 дня автоматически.\n\n"
        "Погасить кредит: `!payloan <сумма>`"
    )
)
async def check_loan(ctx):
    await ctx.message.delete()
    uid = str(ctx.author.id)
    if not player_loans.get(uid):
        await ctx.send(f"{ctx.author.mention}, кредитов нет.", delete_after=5); return

    loan      = player_loans[uid][0]
    total     = int(loan["loan_amount"] * (1 + loan["interest_rate"]))
    paid      = loan.get("paid_amount", 0)
    remaining = total - paid
    due       = datetime.strptime(loan["due_date"], "%Y-%m-%d")
    days_left = (due - datetime.now()).days

    if datetime.now() > due:
        loan["loan_amount"] *= 2
        loan["due_date"]     = (due + timedelta(days=2)).strftime("%Y-%m-%d")
        save_loans()
        await ctx.send(f"⚠️ {ctx.author.mention}, кредит просрочен! Долг удвоен. Новый срок: **{loan['due_date']}**")
        return

    embed = nextcord.Embed(title=f"💳 Кредит {ctx.author.display_name}", color=nextcord.Color.red())
    embed.add_field(name="Сумма",      value=f"{loan['loan_amount']:,}")
    embed.add_field(name="Ставка",     value=f"{int(loan['interest_rate']*100)}%")
    embed.add_field(name="Итого",      value=f"{total:,}")
    embed.add_field(name="Оплачено",   value=f"{paid:,}")
    embed.add_field(name="Остаток",    value=f"{remaining:,}")
    embed.add_field(name="Дней",       value=str(days_left))
    embed.add_field(name="Срок",       value=loan["due_date"])
    await ctx.send(embed=embed)

@bot.command(
    name="payloan",
    brief="Погасить кредит (частично или полностью)",
    help=(
        "Вносит платёж по активному кредиту. Можно платить частями или сразу всё.\n\n"
        "**Использование:**\n"
        "`!payloan <сумма>`\n\n"
        "**Примеры:**\n"
        "`!payloan 5000` — внести 5 000 в счёт кредита\n"
        "`!payloan 999999` — погасить весь оставшийся долг\n\n"
        "**Важно:**\n"
        "• Деньги снимаются с наличных\n"
        "• Если указать сумму больше остатка — спишется только нужная сумма\n"
        "• Кредит закрывается автоматически при полном погашении\n\n"
        "Проверить остаток: `!checkloan`"
    )
)
async def pay_loan(ctx, amount: int):
    await ctx.message.delete()
    uid = str(ctx.author.id)
    if not player_loans.get(uid):
        await ctx.send("❌ Нет активного кредита.", delete_after=5); return
    if player_funds.get(uid, 0) < amount:
        await ctx.send("❌ Недостаточно средств.", delete_after=5); return

    loan      = player_loans[uid][0]
    total     = int(loan["loan_amount"] * (1 + loan["interest_rate"]))
    paid      = loan.get("paid_amount", 0)
    remaining = total - paid
    amount    = min(amount, remaining)

    player_funds[uid]    -= amount
    loan["paid_amount"]  += amount

    if loan["paid_amount"] >= total:
        player_loans[uid].pop(0)
        await ctx.send(f"✅ {ctx.author.mention}, кредит погашен! Баланс: **{player_funds[uid]:,}** 💰")
    else:
        await ctx.send(f"💳 {ctx.author.mention}, внесено **{amount:,}** 💰. Остаток: **{remaining-amount:,}** 💰. Баланс: **{player_funds[uid]:,}**")

    save_funds(); save_loans()

@tasks.loop(hours=1)
async def send_loan_warnings():
    now = datetime.now()
    for uid, loans in list(player_loans.items()):
        for loan in loans:
            due  = datetime.strptime(loan["due_date"], "%Y-%m-%d")
            diff = due - now
            user = bot.get_user(int(uid))
            if not user: continue
            try:
                if timedelta(days=2, hours=23) < diff <= timedelta(days=3):
                    await user.send(f"⚠️ Кредит истекает через **3 дня** ({loan['due_date']})!")
                elif timedelta(hours=23) < diff <= timedelta(days=1):
                    await user.send(f"⚠️ Кредит истекает завтра ({loan['due_date']})!")
            except Exception:
                pass

# ============================================================
#  MODERATION
# ============================================================
@bot.command(
    name="mute",
    brief="[Админ] Замутить участника",
    help=(
        "Выдаёт мут участнику сервера на указанное количество минут.\n\n"
        "**Использование:**\n"
        "`!mute @user <минуты>`\n\n"
        "**Примеры:**\n"
        "`!mute @Vasya 30` — мут на 30 минут\n"
        "`!mute @Vasya 1440` — мут на 24 часа\n\n"
        "**Механика:**\n"
        "• Участнику даётся 1 минута предупреждения перед мутом\n"
        "• Создаётся роль «БАН банан🍌» с запретом писать и говорить\n"
        "• По истечении времени мут снимается автоматически\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def mute(ctx, member: nextcord.Member, mute_time: int):
    await ctx.message.delete()
    await ctx.send(f"⏳ {member.mention}, у тебя 1 минута перед мутом на **{mute_time}** минут.")
    await asyncio.sleep(60)
    role = nextcord.utils.get(ctx.guild.roles, name="БАН банан🍌")
    if not role:
        role = await ctx.guild.create_role(name="БАН банан🍌")
        for ch in ctx.guild.text_channels:
            await ch.set_permissions(role, speak=False, send_messages=False)
    await member.add_roles(role)
    await ctx.send(f"🔇 {member.mention} замучен на **{mute_time}** минут.")
    await asyncio.sleep(mute_time * 60)
    await member.remove_roles(role)
    await ctx.send(f"🔊 {member.mention} размучен.")

@bot.command(
    name="unmute",
    brief="[Админ] Снять мут с участника",
    help=(
        "Немедленно снимает мут с участника сервера.\n\n"
        "**Использование:**\n"
        "`!unmute @user`\n\n"
        "**Пример:**\n"
        "`!unmute @Vasya`\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def unmute(ctx, member: nextcord.Member):
    await ctx.message.delete()
    role = nextcord.utils.get(ctx.guild.roles, name="БАН банан🍌")
    if role and role in member.roles:
        await member.remove_roles(role)
        await ctx.send(f"🔊 {member.mention} размучен.")
    else:
        await ctx.send(f"{member.mention} не замучен.", delete_after=5)

@bot.command(
    name="ban",
    brief="[Админ] Забанить участника",
    help=(
        "Банит участника сервера на указанное количество дней, после чего разбанивает автоматически.\n\n"
        "**Использование:**\n"
        "`!ban @user <дней>`\n\n"
        "**Примеры:**\n"
        "`!ban @Vasya 3` — бан на 3 дня\n"
        "`!ban @Vasya 1` — бан на 1 день\n\n"
        "**Механика:**\n"
        "• Участнику даётся 1 минута предупреждения\n"
        "• Сообщения за последние 7 дней удаляются\n"
        "• По истечении срока участник разбанивается автоматически\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def ban(ctx, member: nextcord.Member, ban_days: int):
    await ctx.message.delete()
    await ctx.send(f"⏳ {member.mention}, у тебя 1 минута перед баном на **{ban_days}** дней.")
    await asyncio.sleep(60)
    await member.ban(reason=f"Бан на {ban_days} дней", delete_message_days=7)
    await ctx.send(f"🔨 {member.mention} забанен на **{ban_days}** дней.")
    await asyncio.sleep(ban_days * 86400)
    await ctx.guild.unban(member)
    await ctx.send(f"✅ {member.mention} разбанен.")

@bot.command(
    name="kick",
    brief="[Админ] Кикнуть участника с сервера",
    help=(
        "Выгоняет участника с сервера (он сможет вернуться по приглашению).\n\n"
        "**Использование:**\n"
        "`!kick @user` — без причины\n"
        "`!kick @user <причина>` — с указанием причины\n\n"
        "**Примеры:**\n"
        "`!kick @Vasya Нарушение правил`\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def kick(ctx, member: nextcord.Member, *, reason: str = "Не указана"):
    await ctx.message.delete()
    await member.kick(reason=reason)
    await ctx.send(f"👢 {member.mention} выгнан. Причина: **{reason}**")

@bot.command(
    name="warn",
    brief="[Админ] Выдать предупреждение участнику",
    help=(
        "Выдаёт предупреждение (варн) участнику сервера. Участник получит уведомление в ЛС.\n\n"
        "**Использование:**\n"
        "`!warn @user` — без причины\n"
        "`!warn @user <причина>` — с причиной\n\n"
        "**Примеры:**\n"
        "`!warn @Vasya Спам в чате`\n"
        "`!warn @Vasya`\n\n"
        "**Только для администраторов!**\n\n"
        "Посмотреть варны: `!warns @user`\n"
        "Снять варны: `!clearwarn @user`"
    )
)
@commands.has_permissions(administrator=True)
async def warn_member(ctx, member: nextcord.Member, *, reason: str = "Не указана"):
    await ctx.message.delete()
    uid = str(member.id)
    if uid not in player_warns: player_warns[uid] = []
    player_warns[uid].append({"reason": reason, "date": datetime.now().strftime("%d.%m.%Y %H:%M"), "by": str(ctx.author.id)})
    save_warns()
    count = len(player_warns[uid])
    await ctx.send(f"⚠️ {member.mention}, предупреждение #{count}! Причина: **{reason}**")
    try: await member.send(f"⚠️ Вы получили предупреждение на **{ctx.guild.name}**.\nПричина: {reason}\nВарн #{count}")
    except Exception: pass

@bot.command(
    name="warns",
    brief="Посмотреть предупреждения игрока",
    help=(
        "Показывает список всех предупреждений (варнов) указанного участника.\n\n"
        "**Использование:**\n"
        "`!warns` — свои варны\n"
        "`!warns @user` — варны другого участника\n\n"
        "Отображаются последние 10 предупреждений с датой и причиной."
    )
)
async def check_warns(ctx, member: nextcord.Member = None):
    await ctx.message.delete()
    if member is None: member = ctx.author
    uid  = str(member.id)
    wrnl = player_warns.get(uid, [])
    embed = nextcord.Embed(title=f"⚠️ Варны {member.display_name}", color=nextcord.Color.orange())
    if not wrnl:
        embed.description = "Нет предупреждений. ✅"
    else:
        for i, w in enumerate(wrnl[-10:], 1):
            embed.add_field(name=f"#{i}", value=f"{w['reason']} ({w['date']})", inline=False)
    await ctx.send(embed=embed)

@bot.command(
    name="clearwarn",
    brief="[Админ] Снять все варны с участника",
    help=(
        "Полностью очищает историю предупреждений указанного участника.\n\n"
        "**Использование:**\n"
        "`!clearwarn @user`\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def clear_warns(ctx, member: nextcord.Member):
    await ctx.message.delete()
    uid = str(member.id)
    player_warns[uid] = []
    save_warns()
    await ctx.send(f"✅ Все предупреждения {member.mention} сброшены.")

@bot.command(
    name="clear",
    brief="[Админ] Удалить сообщения в канале",
    help=(
        "Удаляет указанное количество последних сообщений в текущем канале.\n\n"
        "**Использование:**\n"
        "`!clear <количество>`\n\n"
        "**Примеры:**\n"
        "`!clear 10` — удалить 10 последних сообщений\n"
        "`!clear 100` — удалить 100 сообщений (максимум)\n\n"
        "**Ограничение:** от 1 до 100 сообщений за раз\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def clear_messages(ctx, amount: int):
    await ctx.message.delete()
    if not 1 <= amount <= 100:
        await ctx.send("Количество от 1 до 100.", delete_after=5); return
    deleted = await ctx.channel.purge(limit=amount)
    msg = await ctx.send(f"🗑️ Удалено **{len(deleted)}** сообщений.")
    await asyncio.sleep(3); await msg.delete()

@bot.command(
    name="clearday",
    brief="[Админ] Удалить сообщения за N дней",
    help=(
        "Удаляет все сообщения в канале за указанное количество последних дней.\n\n"
        "**Использование:**\n"
        "`!clearday <дней>`\n\n"
        "**Примеры:**\n"
        "`!clearday 1` — удалить сообщения за последние сутки\n"
        "`!clearday 7` — удалить сообщения за последнюю неделю\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def clearday(ctx, days: int):
    await ctx.message.delete()
    if days <= 0:
        await ctx.send("Дней > 0.", delete_after=5); return
    limit   = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = await ctx.channel.purge(after=limit)
    msg = await ctx.send(f"🗑️ Удалено **{len(deleted)}** сообщений за {days} дней.")
    await asyncio.sleep(3); await msg.delete()

@bot.command(
    name="clearuser",
    brief="[Админ] Удалить сообщения конкретного участника",
    help=(
        "Удаляет последние N сообщений указанного участника в текущем канале.\n\n"
        "**Использование:**\n"
        "`!clearuser @user <количество>`\n\n"
        "**Примеры:**\n"
        "`!clearuser @Vasya 50` — удалить 50 последних сообщений Васи\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def clearuser(ctx, member: nextcord.Member, amount: int):
    await ctx.message.delete()
    if amount <= 0:
        await ctx.send("Количество > 0.", delete_after=5); return
    deleted = await ctx.channel.purge(limit=amount, check=lambda m: m.author == member)
    await ctx.send(f"🗑️ Удалено **{len(deleted)}** сообщений от {member.mention}.", delete_after=5)

@bot.command(
    name="clearuserday",
    brief="[Админ] Удалить сообщения участника за N дней",
    help=(
        "Удаляет все сообщения указанного участника за последние N дней в текущем канале.\n\n"
        "**Использование:**\n"
        "`!clearuserday @user <дней>`\n\n"
        "**Примеры:**\n"
        "`!clearuserday @Vasya 3` — удалить сообщения Васи за 3 дня\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def clearuserdays(ctx, member: nextcord.Member, days: int):
    await ctx.message.delete()
    if days <= 0:
        await ctx.send("Дней > 0.", delete_after=5); return
    limit   = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0
    async for msg in ctx.channel.history(limit=500):
        if msg.author == member and msg.created_at.replace(tzinfo=timezone.utc) >= limit:
            await msg.delete(); deleted += 1
    await ctx.send(f"🗑️ Удалено **{deleted}** сообщений от {member.mention} за {days} дней.", delete_after=5)

# ============================================================
#  INFO COMMANDS
# ============================================================
@bot.command(
    name="userinfo",
    brief="Информация об участнике сервера",
    help=(
        "Показывает подробную информацию об участнике сервера.\n\n"
        "**Использование:**\n"
        "`!userinfo` — о себе\n"
        "`!userinfo @user` — о другом участнике\n\n"
        "**Отображается:**\n"
        "• Отображаемое имя и ID\n"
        "• Дата вступления на сервер\n"
        "• Дата создания аккаунта Discord\n"
        "• Список ролей участника"
    )
)
async def user_info(ctx, member: nextcord.Member = None):
    await ctx.message.delete()
    if member is None: member = ctx.author
    embed = nextcord.Embed(title=f"👤 {member.display_name}", color=nextcord.Color.blue())
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="Имя",           value=member.display_name)
    embed.add_field(name="ID",            value=str(member.id))
    embed.add_field(name="Присоединился", value=member.joined_at.strftime("%d.%m.%Y %H:%M"))
    embed.add_field(name="Аккаунт создан",value=member.created_at.strftime("%d.%m.%Y %H:%M"))
    embed.add_field(name="Роли",          value=", ".join(r.mention for r in member.roles[1:]) or "—")
    await ctx.send(embed=embed)

@bot.command(
    name="serverinfo",
    brief="Информация о сервере",
    help=(
        "Показывает общую информацию о текущем сервере.\n\n"
        "**Использование:**\n"
        "`!serverinfo`\n\n"
        "**Отображается:**\n"
        "• Название и ID сервера\n"
        "• Дата создания\n"
        "• Количество участников, каналов, ролей и эмодзи"
    )
)
async def server_info(ctx):
    await ctx.message.delete()
    g     = ctx.guild
    embed = nextcord.Embed(title=f"🖥️ {g.name}", color=nextcord.Color.green())
    embed.add_field(name="ID",         value=str(g.id))
    embed.add_field(name="Создан",     value=g.created_at.strftime("%d.%m.%Y"))
    embed.add_field(name="Участники",  value=str(g.member_count))
    embed.add_field(name="Каналы",     value=str(len(g.channels)))
    embed.add_field(name="Роли",       value=str(len(g.roles)))
    embed.add_field(name="Эмодзи",     value=str(len(g.emojis)))
    if g.icon: embed.set_thumbnail(url=g.icon.url)
    await ctx.send(embed=embed)

@bot.command(
    name="moneyhelp",
    brief="Гайд по денежной системе",
    help=(
        "Показывает список всех команд экономической системы с кратким описанием.\n\n"
        "**Использование:**\n"
        "`!moneyhelp`\n\n"
        "Также используй `!help <команда>` для подробного описания любой команды."
    )
)
async def moneyhelp(ctx):
    await ctx.message.delete()
    try:
        with open("moneyhelp.txt", "r", encoding="utf-8") as f:
            await ctx.send(f.read())
    except FileNotFoundError:
        embed = nextcord.Embed(title="💰 Денежная система", color=nextcord.Color.gold())
        cmds  = [
            ("!money",                  "Баланс (наличные + банк)"),
            ("!pay @user сумма",        "Перевод"),
            ("!deposit сумма",          "Положить в банк"),
            ("!withdraw сумма",         "Снять из банка"),
            ("!daily",                  "Ежедневный бонус"),
            ("!rob @user",              "Ограбить (cooldown 1ч)"),
            ("!crime",                  "Преступление (cooldown 30мин)"),
            ("!shop",                   "Магазин"),
            ("!buy <id>",               "Купить предмет"),
            ("!inventory",              "Инвентарь"),
            ("!applyloan сумма дней",   "Оформить кредит"),
            ("!payloan сумма",          "Погасить кредит"),
            ("!checkloan",              "Статус кредита"),
            ("!top",                    "Топ богатейших"),
        ]
        for c, d in cmds:
            embed.add_field(name=f"`{c}`", value=d, inline=False)
        await ctx.send(embed=embed)

# ============================================================
#  FUN COMMANDS
# ============================================================
@bot.command(
    name="joke",
    aliases=["randomjoke","jokes"],
    brief="Случайная шутка",
    help=(
        "Отправляет случайную шутку из базы данных бота.\n\n"
        "**Использование:**\n"
        "`!joke`\n\n"
        "**Псевдонимы:** `!randomjoke`, `!jokes`"
    )
)
async def tell_joke(ctx):
    await ctx.message.delete()
    await ctx.send(f"{ctx.author.mention} {random.choice(jokes)}")

@bot.command(
    name="predict",
    aliases=["fortune","prophecy"],
    brief="Случайное предсказание",
    help=(
        "Выдаёт случайное предсказание или предзнаменование.\n\n"
        "**Использование:**\n"
        "`!predict`\n\n"
        "**Псевдонимы:** `!fortune`, `!prophecy`"
    )
)
async def tell_prediction(ctx):
    await ctx.message.delete()
    await ctx.send(f"{ctx.author.mention} {random.choice(predictions)}")

@bot.command(
    name="greet",
    brief="Поприветствовать участника",
    help=(
        "Отправляет приветствие от бота указанному участнику.\n\n"
        "**Использование:**\n"
        "`!greet @user`\n\n"
        "**Пример:**\n"
        "`!greet @Vasya`"
    )
)
async def greet_user(ctx, member: nextcord.Member):
    await ctx.message.delete()
    await ctx.send(f"Привет {member.mention} от бота базарчик пм")

@bot.command(
    name="pick",
    brief="Позвать участника на сервер",
    help=(
        "Отправляет участнику «приглашение» зайти на сервер в шуточной форме.\n\n"
        "**Использование:**\n"
        "`!pick @user`\n\n"
        "**Пример:**\n"
        "`!pick @Vasya`"
    )
)
async def pick_user(ctx, member: nextcord.Member):
    await ctx.message.delete()
    await ctx.send(f"{member.mention} а ну быстро зашол ато банчик")

@bot.command(
    name="z",
    brief="Напомнить об украинском языке",
    help=(
        "Отправляет мотивирующее сообщение о важности украинского языка.\n\n"
        "**Использование:**\n"
        "`!z @user`\n\n"
        "**Пример:**\n"
        "`!z @Vasya`"
    )
)
async def z_user(ctx, member: nextcord.Member):
    await ctx.message.delete()
    await ctx.send(
        f"{member.mention}! Слухай уважно! Настав час остаточно та безповоротно відмовитися від усього, що пахне московією. "
        f"Жодного слова їхньою отруйною мовою, жодного виразу, жодного кальки з того, що тисячоліттями нищило нашу культуру. "
        f"З цього моменту твоє слово — лише українське, чисте, міцне, як криця, що кується в полум'ї свободи. "
        f"Пам'ятай: кожен, хто зберігає російське в собі, — дає ворогу маленьку шпарину, крізь яку тече його отрута. "
        f"Ми, українці, не маємо права на слабкість. Ми відкидаємо все московське: мову, музику, кіно, книжки, навіть звички мислити так, як нас навчали з імперських підручників. "
        f"Ми говоримо українською не тому, що так модно чи зручно, а тому, що це наш фронт, це наша зброя, це наша перемога. "
        f"{member.mention}, зроби свій вибір. Кожне твоє слово українською — це удар по імперії. "
        f"Будь воїном слова, і нехай більше жоден московський звук не торкнеться твого вуст!"
    )

@bot.command(
    name="random",
    brief="Случайный «невезучий» игрок дня",
    help=(
        "Случайно выбирает одного из фиксированного списка игроков, которому «не повезло» сегодня.\n\n"
        "**Использование:**\n"
        "`!random`\n\n"
        "Список участников: NIKUSA, REOSTISLAV, TANCHIK, STROLEKOFK"
    )
)
async def fortune_random(ctx):
    await ctx.message.delete()
    fortune_list = ["Игрок NIKUSA","Игрок REOSTISLAV","Игрок TANCHIK","Игрок STROLEKOFK"]
    await ctx.send(f"🎉 Сегодня удача не на стороне: **{random.choice(fortune_list)}**!")

@bot.command(
    name="8ball",
    brief="Магический шар — ответ на любой вопрос",
    help=(
        "Задай вопрос магическому шару и получи пророческий ответ!\n\n"
        "**Использование:**\n"
        "`!8ball <вопрос>`\n\n"
        "**Примеры:**\n"
        "`!8ball Я разбогатею?`\n"
        "`!8ball Стоит ли ставить всё на рулетку?`\n\n"
        "**Типы ответов:**\n"
        "✅ Положительные (5 вариантов)\n"
        "🤔 Нейтральные (3 варианта)\n"
        "❌ Отрицательные (4 варианта)"
    )
)
async def magic_8ball(ctx, *, question: str = None):
    await ctx.message.delete()
    if not question:
        await ctx.send("❗ `!8ball <вопрос>`", delete_after=5); return
    answers = [
        "✅ Определённо да!", "✅ Без сомнений!", "✅ Скорее всего да.",
        "✅ Всё указывает на да.", "✅ Я думаю — да.",
        "🤔 Спроси позже.", "🤔 Трудно сказать.", "🤔 Неясно.",
        "❌ Не думаю.", "❌ Мои источники говорят нет.",
        "❌ Перспективы неутешительны.", "❌ Определённо нет.",
    ]
    embed = nextcord.Embed(color=nextcord.Color.dark_blue())
    embed.add_field(name="❓ Вопрос", value=question, inline=False)
    embed.add_field(name="🎱 Ответ",  value=random.choice(answers), inline=False)
    await ctx.send(embed=embed)

@bot.command(
    name="rate",
    brief="Оценить что-либо по шкале 0-100",
    help=(
        "Бот случайно оценивает любую вещь, человека или идею по шкале от 0 до 100.\n\n"
        "**Использование:**\n"
        "`!rate <что угодно>`\n\n"
        "**Примеры:**\n"
        "`!rate моя удача`\n"
        "`!rate @Vasya`\n"
        "`!rate сервер BAZARCIK_PM`"
    )
)
async def rate_something(ctx, *, thing: str = None):
    await ctx.message.delete()
    if not thing:
        await ctx.send("❗ `!rate <что-то>`", delete_after=5); return
    score    = random.randint(0, 100)
    bar_fill = score // 5
    bar      = "█" * bar_fill + "░" * (20 - bar_fill)
    await ctx.send(f"⭐ **{thing}**\n`[{bar}]` **{score}/100**")

@bot.command(
    name="coinflip",
    aliases=["cf"],
    brief="Подбросить монетку (без ставки)",
    help=(
        "Подбрасывает монетку просто так, без ставок.\n\n"
        "**Использование:**\n"
        "`!coinflip`\n"
        "`!cf`\n\n"
        "Для игры на деньги используй `!flip <ставка> <орел/решка>`"
    )
)
async def coinflip(ctx):
    await ctx.message.delete()
    result = random.choice(["🦅 Орёл", "🍀 Решка"])
    await ctx.send(f"🪙 {ctx.author.mention} бросил монетку — **{result}**!")

@bot.command(
    name="hug",
    brief="Обнять участника",
    help=(
        "Отправляет тёплое объятие выбранному участнику сервера.\n\n"
        "**Использование:**\n"
        "`!hug @user`\n\n"
        "**Пример:**\n"
        "`!hug @Vasya`"
    )
)
async def hug(ctx, member: nextcord.Member):
    await ctx.message.delete()
    msgs = [
        f"🤗 {ctx.author.mention} крепко обнимает {member.mention}!",
        f"💛 {ctx.author.mention} тепло обнял {member.mention}!",
        f"🤗 {member.mention} получает уютные объятия от {ctx.author.mention}!",
    ]
    await ctx.send(random.choice(msgs))

@bot.command(
    name="slap",
    brief="Дать пощёчину участнику",
    help=(
        "Даёт шуточную пощёчину выбранному участнику.\n\n"
        "**Использование:**\n"
        "`!slap @user`\n\n"
        "**Пример:**\n"
        "`!slap @Vasya`"
    )
)
async def slap(ctx, member: nextcord.Member):
    await ctx.message.delete()
    await ctx.send(f"👋 {ctx.author.mention} дал пощёчину {member.mention}!")

@bot.command(
    name="kiss",
    brief="Поцеловать участника",
    help=(
        "Посылает воздушный поцелуй выбранному участнику.\n\n"
        "**Использование:**\n"
        "`!kiss @user`\n\n"
        "**Пример:**\n"
        "`!kiss @Vasya`"
    )
)
async def kiss(ctx, member: nextcord.Member):
    await ctx.message.delete()
    await ctx.send(f"💋 {ctx.author.mention} поцеловал {member.mention}!")

@bot.command(
    name="avatar",
    brief="Показать аватар участника",
    help=(
        "Показывает аватар в полном размере.\n\n"
        "**Использование:**\n"
        "`!avatar` — свой аватар\n"
        "`!avatar @user` — аватар другого участника"
    )
)
async def get_avatar(ctx, member: nextcord.Member = None):
    await ctx.message.delete()
    if member is None: member = ctx.author
    embed = nextcord.Embed(title=f"🖼️ Аватар {member.display_name}", color=nextcord.Color.blue())
    embed.set_image(url=member.display_avatar.url)
    await ctx.send(embed=embed)

@bot.command(
    name="say",
    brief="[Админ] Написать от имени бота",
    help=(
        "Заставляет бота написать указанный текст в текущем канале.\n\n"
        "**Использование:**\n"
        "`!say <текст>`\n\n"
        "**Пример:**\n"
        "`!say Всем привет!`\n\n"
        "**Только для администраторов!**\n"
        "Твоё исходное сообщение будет удалено."
    )
)
@commands.has_permissions(administrator=True)
async def say(ctx, *, text: str):
    await ctx.message.delete()
    await ctx.send(text)

@bot.command(
    name="embed",
    brief="[Админ] Отправить красивый embed",
    help=(
        "Отправляет форматированное embed-сообщение с заголовком и текстом.\n\n"
        "**Использование:**\n"
        '`!embed "Заголовок" текст сообщения`\n\n'
        "**Пример:**\n"
        '`!embed "Важно" Завтра технические работы на сервере!`\n\n'
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def embed_cmd(ctx, title: str, *, text: str):
    await ctx.message.delete()
    embed = nextcord.Embed(title=title, description=text, color=nextcord.Color.blurple())
    await ctx.send(embed=embed)

@bot.command(
    name="announce",
    brief="[Админ] Сделать объявление с @here",
    help=(
        "Создаёт официальное объявление с пингом @here и красивым оформлением.\n\n"
        "**Использование:**\n"
        "`!announce <текст объявления>`\n\n"
        "**Пример:**\n"
        "`!announce Сервер будет недоступен с 20:00 до 21:00 по МСК`\n\n"
        "**Важно:**\n"
        "• Пингует @here — все онлайн-участники получат уведомление\n"
        "• В подписи указывается имя администратора\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def announce(ctx, *, text: str):
    await ctx.message.delete()
    embed = nextcord.Embed(
        title="📢 Объявление",
        description=text,
        color=nextcord.Color.red()
    )
    embed.set_footer(text=f"От {ctx.author.display_name}")
    await ctx.send("@here", embed=embed)

# ============================================================
#  GIVE MONEY (admin)
# ============================================================
@bot.command(
    name="give",
    brief="[Админ] Выдать деньги участнику",
    help=(
        "Начисляет указанную сумму на наличные счёт участника.\n\n"
        "**Использование:**\n"
        "`!give @user <сумма>`\n\n"
        "**Примеры:**\n"
        "`!give @Vasya 10000` — выдать Васе 10 000 монет\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def give_money(ctx, member: nextcord.Member, amount: int):
    await ctx.message.delete()
    uid = str(member.id)
    player_funds[uid] = player_funds.get(uid, 0) + amount
    save_funds()
    await ctx.send(f"✅ {member.mention} получил **{amount:,}** 💰. Баланс: **{player_funds[uid]:,}**")

@bot.command(
    name="take",
    brief="[Админ] Снять деньги с участника",
    help=(
        "Снимает указанную сумму с наличного счёта участника (минимум до 0).\n\n"
        "**Использование:**\n"
        "`!take @user <сумма>`\n\n"
        "**Примеры:**\n"
        "`!take @Vasya 5000` — снять 5 000 монет у Васи\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def take_money(ctx, member: nextcord.Member, amount: int):
    await ctx.message.delete()
    uid = str(member.id)
    player_funds[uid] = max(0, player_funds.get(uid, 0) - amount)
    save_funds()
    await ctx.send(f"✅ У {member.mention} снято **{amount:,}** 💰. Баланс: **{player_funds[uid]:,}**")

@bot.command(
    name="setmoney",
    brief="[Админ] Установить баланс участника",
    help=(
        "Устанавливает точное значение наличных на счету участника.\n\n"
        "**Использование:**\n"
        "`!setmoney @user <сумма>`\n\n"
        "**Примеры:**\n"
        "`!setmoney @Vasya 0` — обнулить баланс Васи\n"
        "`!setmoney @Vasya 100000` — установить 100 000 монет\n\n"
        "**Только для администраторов!**"
    )
)
@commands.has_permissions(administrator=True)
async def set_money(ctx, member: nextcord.Member, amount: int):
    await ctx.message.delete()
    uid = str(member.id)
    player_funds[uid] = amount
    save_funds()
    await ctx.send(f"✅ Баланс {member.mention} установлен: **{amount:,}** 💰")

# ============================================================
#  PETITION SYSTEM
# ============================================================
@bot.command(
    name="petition",
    brief="Создать петицию",
    help=(
        "Создаёт новую петицию, которую другие участники могут подписать командой `!vote`.\n\n"
        "**Использование:**\n"
        "`!petition <текст петиции>`\n\n"
        "**Пример:**\n"
        "`!petition Добавить новый игровой канал`\n\n"
        "**Как работает:**\n"
        "1. Ты создаёшь петицию с текстом\n"
        "2. Нужно набрать 10% голосов от числа участников сервера\n"
        "3. После набора подписей петиция уходит на голосование администраторов\n"
        "4. 3 администратора голосуют командами `!yes <номер>` / `!no <номер>`\n"
        "5. Большинством голосов петиция одобряется или отклоняется\n\n"
        "Посмотреть активные петиции: `!petitions`"
    )
)
async def petition(ctx, *, text: str = None):
    await ctx.message.delete()
    if not text:
        await ctx.send("❗ `!petition <текст>`", delete_after=10); return

    try:
        with open("petitions.json","r",encoding="utf-8") as f: petitions = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError): petitions = []

    pid      = len(petitions) + 1
    required = max(1, int(ctx.guild.member_count * 0.1) - 1)
    data     = {
        "id": pid, "author": ctx.author.id, "text": text,
        "votes": 0, "voters": [], "status": "active",
        "message_id": None, "required_votes": required,
        "reviews": {"yes": [], "no": []},
    }
    petitions.append(data)
    with open("petitions.json","w",encoding="utf-8") as f: json.dump(petitions, f, indent=4)

    msg = await ctx.send(
        f"📜 **Петиция №{pid}**\n{text}\n\n"
        f"Автор: <@{ctx.author.id}>\nПодписей: 0/{required}\n👮 Голоса: 0/3\n\n"
        f"✍️ `!vote {pid}`")
    data["message_id"] = msg.id
    with open("petitions.json","w",encoding="utf-8") as f: json.dump(petitions, f, indent=4)

@bot.command(
    name="vote",
    brief="Подписать петицию",
    help=(
        "Ставит подпись под активной петицией.\n\n"
        "**Использование:**\n"
        "`!vote <номер петиции>`\n\n"
        "**Примеры:**\n"
        "`!vote 1` — подписать петицию №1\n"
        "`!vote 5` — подписать петицию №5\n\n"
        "**Правила:**\n"
        "• Каждый участник может подписать петицию только один раз\n"
        "• После набора нужного числа подписей петиция уходит к администраторам\n\n"
        "Список петиций: `!petitions`"
    )
)
async def vote_petition(ctx, petition_id: int = None):
    await ctx.message.delete()
    if petition_id is None:
        await ctx.send("❗ `!vote <номер>`", delete_after=10); return

    try:
        with open("petitions.json","r",encoding="utf-8") as f: petitions = json.load(f)
    except: await ctx.send("Нет петиций.", delete_after=5); return

    p = next((x for x in petitions if x["id"] == petition_id), None)
    if not p:
        await ctx.send("Петиция не найдена.", delete_after=5); return
    if p["status"] != "active":
        await ctx.send("Петиция закрыта.", delete_after=5); return
    if str(ctx.author.id) in [str(v) for v in p["voters"]]:
        await ctx.send("Ты уже подписал.", delete_after=5); return

    p["votes"] += 1
    p["voters"].append(str(ctx.author.id))
    with open("petitions.json","w",encoding="utf-8") as f: json.dump(petitions, f, indent=4)

    av = len(p.get("reviews",{}).get("yes",[])) + len(p.get("reviews",{}).get("no",[]))
    content = (f"📜 **Петиция №{p['id']}**\n{p['text']}\n\n"
               f"Автор: <@{p['author']}>\nПодписей: **{p['votes']}/{p['required_votes']}**\n"
               f"👮 Голоса: {av}/3\n\n"
               f"{'🔔 Ожидает решения админов!' if p['votes'] >= p['required_votes'] else f'✍️ `!vote {p[chr(105)+chr(100)]}`'}")
    try:
        msg = await ctx.channel.fetch_message(p["message_id"])
        await msg.edit(content=content)
    except Exception: pass
    await ctx.send("✅ Подпись принята!", delete_after=5)

@bot.command(
    name="yes",
    brief="[Админ] Одобрить петицию",
    help=(
        "Голосует «За» по петиции, набравшей достаточно подписей.\n\n"
        "**Использование:**\n"
        "`!yes <номер петиции>`\n\n"
        "**Пример:**\n"
        "`!yes 1` — проголосовать «За» петицию №1\n\n"
        "**Только для администраторов!**\n\n"
        "Для принятия решения нужны голоса 3 администраторов.\n"
        "Голосовать «Против»: `!no <номер>`"
    )
)
async def yes_petition(ctx, petition_id: int):
    await _handle_admin_vote(ctx, petition_id, "yes")

@bot.command(
    name="no",
    brief="[Админ] Отклонить петицию",
    help=(
        "Голосует «Против» по петиции, набравшей достаточно подписей.\n\n"
        "**Использование:**\n"
        "`!no <номер петиции>`\n\n"
        "**Пример:**\n"
        "`!no 1` — проголосовать «Против» петицию №1\n\n"
        "**Только для администраторов!**\n\n"
        "Для принятия решения нужны голоса 3 администраторов.\n"
        "Голосовать «За»: `!yes <номер>`"
    )
)
async def no_petition(ctx, petition_id: int):
    await _handle_admin_vote(ctx, petition_id, "no")

async def _handle_admin_vote(ctx, petition_id: int, vote_type: str):
    await ctx.message.delete()
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("Только администратор!", delete_after=5); return

    try:
        with open("petitions.json","r",encoding="utf-8") as f: petitions = json.load(f)
    except: await ctx.send("Нет петиций.", delete_after=5); return

    for p in petitions:
        if p["id"] == petition_id:
            if p["status"] != "active":
                await ctx.send("Петиция уже рассмотрена.", delete_after=5); return
            if p["votes"] < p["required_votes"]:
                await ctx.send(f"Не хватает подписей ({p['votes']}/{p['required_votes']})", delete_after=5); return
            if "reviews" not in p: p["reviews"] = {"yes":[],"no":[]}
            if ctx.author.id in p["reviews"]["yes"] + p["reviews"]["no"]:
                await ctx.send("Вы уже голосовали.", delete_after=5); return

            p["reviews"][vote_type].append(ctx.author.id)
            total  = len(p["reviews"]["yes"]) + len(p["reviews"]["no"])
            result = None

            if total >= 3:
                p["status"] = "approved" if len(p["reviews"]["yes"]) > len(p["reviews"]["no"]) else "rejected"
                result      = "✅ Одобрена" if p["status"] == "approved" else "❌ Отклонена"

            with open("petitions.json","w",encoding="utf-8") as f: json.dump(petitions, f, indent=4)

            content = (f"📜 **Петиция №{p['id']}**\n{p['text']}\n\n"
                      f"Автор: <@{p['author']}>\nПодписей: {p['votes']}/{p['required_votes']}\n"
                      f"👮 Голоса: {total}/3\n\n"
                      f"{result + ' большинством голосов!' if result else '🔔 Ожидает решения.'}")
            try:
                msg = await ctx.channel.fetch_message(p["message_id"])
                await msg.edit(content=content)
            except Exception: pass

            await ctx.send(
                f"{'Петиция закрыта: ' + result if result else f'{total}/3 проголосовало.'}",
                delete_after=10)
            return

    await ctx.send("Петиция не найдена.", delete_after=5)

@bot.command(
    name="petitions",
    brief="Список активных петиций",
    help=(
        "Показывает список всех активных петиций на сервере.\n\n"
        "**Использование:**\n"
        "`!petitions`\n\n"
        "Для каждой петиции показывается:\n"
        "• Номер и текст (первые 60 символов)\n"
        "• Текущее количество подписей и необходимое\n\n"
        "Подписать петицию: `!vote <номер>`\n"
        "Создать петицию: `!petition <текст>`"
    )
)
async def list_petitions(ctx):
    await ctx.message.delete()
    try:
        with open("petitions.json","r",encoding="utf-8") as f: petitions = json.load(f)
    except: await ctx.send("Нет петиций.", delete_after=5); return

    active = [p for p in petitions if p["status"] == "active"]
    if not active:
        await ctx.send("Нет активных петиций.", delete_after=5); return

    embed = nextcord.Embed(title="📜 Активные петиции", color=nextcord.Color.blue())
    for p in active[:10]:
        embed.add_field(
            name=f"#{p['id']}: {p['text'][:60]}{'...' if len(p['text'])>60 else ''}",
            value=f"Подписей: {p['votes']}/{p['required_votes']}",
            inline=False)
    await ctx.send(embed=embed)

# ============================================================
#  AUTO VOICE CHANNELS
# ============================================================
AUTO_CHANNELS = {
    1402746822191218749: 1402733375986466816,
    1402746847713296526: 1402732822375960676,
    1402746870773584062: 1402732572206960661,
    1472756792491643031: 1402748456883454097,
}

@bot.event
async def on_voice_state_update(member, before, after):
    if after.channel and after.channel.id in AUTO_CHANNELS:
        guild    = member.guild
        cat_id   = AUTO_CHANNELS[after.channel.id]
        category = guild.get_channel(cat_id)
        new_name = after.channel.name.replace("Create", "")
        prefix   = "_ZP" if new_name == "🔊 Poslucháreň" else " "

        existing = set()
        for ch in category.voice_channels:
            if ch.name.startswith(new_name + prefix):
                try: existing.add(int(ch.name.replace(new_name + prefix, "").strip()))
                except ValueError: pass

        num = 1
        while num in existing: num += 1

        new_ch = await guild.create_voice_channel(name=f"{new_name}{prefix}{num}", category=category)
        await new_ch.edit(sync_permissions=True)
        await member.move_to(new_ch)

    if before.channel:
        if before.channel.id in AUTO_CHANNELS: return
        if before.channel.category_id not in AUTO_CHANNELS.values(): return
        if not re.search(r"\d+$", before.channel.name): return
        await asyncio.sleep(5)
        if len(before.channel.members) == 0:
            try: await before.channel.delete()
            except Exception as e: print(f"[ERROR] delete channel: {e}")

# ============================================================
#  HELP COMMAND
# ============================================================
class MyHelpCommand(commands.HelpCommand):

    # ── Общий !help ──────────────────────────────────────────
    async def send_bot_help(self, mapping):
        ctx = self.context
        try: await ctx.message.delete()
        except Exception: pass

        # Если есть файл help.txt — используем его
        try:
            with open("help.txt", "r", encoding="utf-8") as f:
                help_text = f.read()
            try:
                await ctx.author.send(help_text)
            except nextcord.Forbidden:
                await ctx.send(f"{ctx.author.mention}, разреши ЛС!")
            return
        except FileNotFoundError:
            pass

        # ── Иначе строим embed ──────────────────────────────
        sections = {
            "💰 Экономика": [
                ("`!money`",          "Показать баланс (наличные + банк)"),
                ("`!pay @user сумма`","Перевести деньги другому игроку"),
                ("`!deposit сумма`",  "Положить деньги в банк"),
                ("`!withdraw сумма`", "Снять деньги из банка"),
                ("`!daily`",          "Ежедневный бонус (серия до 3 000 💰)"),
                ("`!top`",            "Топ-10 богатейших игроков"),
                ("`!toplevel`",       "Топ-10 по уровню и XP"),
            ],
            "⭐ Профиль и уровень": [
                ("`!profile [@user]`","Полный профиль игрока"),
                ("`!level [@user]`",  "Уровень и XP-прогресс"),
                ("`!avatar [@user]`", "Аватар в полном размере"),
                ("`!userinfo [@user]`","Информация об участнике сервера"),
                ("`!serverinfo`",     "Информация о сервере"),
            ],
            "🎯 Заработок и риск": [
                ("`!rob @user`",      "Ограбить игрока (cooldown 1ч, шанс 45%)"),
                ("`!crime`",          "Совершить преступление (cooldown 30мин, шанс 60%)"),
                ("`!fish`",           "Порыбачить (нужна удочка, cooldown 5мин)"),
                ("`!lotto`",          "Добавить лотерейный билет в пул"),
                ("`!drawlotto`",      "🔑 Провести розыгрыш лотереи"),
            ],
            "🎰 Казино и игры": [
                ("`!bj ставка`",                "Блэкджек (×3 блэкджек / ×2 победа)"),
                ("`!flip ставка орел/решка`",   "Орёл или решка (×2)"),
                ("`!spin ставка`",              "Слоты (×5 джекпот / ×2 два одинаковых)"),
                ("`!dice ставка число`",        "Угадай кубик 1–6 (×5)"),
                ("`!roulette ставка выбор`",    "Рулетка: red/black/green/число (×2–×35)"),
            ],
            "🛒 Магазин и инвентарь": [
                ("`!shop`",               "Каталог магазина"),
                ("`!buy <id>`",           "Купить предмет"),
                ("`!inventory [@user]`",  "Посмотреть инвентарь"),
                ("`!use <id> [@user]`",   "Использовать предмет (bomb требует @user)"),
            ],
            "🏢 Бизнес": [
                ("`!buy_business тип название`", "Купить бизнес (макс. 3)"),
                ("`!sell_business название`",    "Продать бизнес (70% стоимости)"),
                ("`!upgrade_business название`", "Улучшить бизнес (раз в сутки)"),
                ("`!repair_business название`",  "Отремонтировать бизнес"),
                ("`!businesses [@user]`",        "Список бизнесов"),
                ("`!business_info`",             "Типы и характеристики бизнесов"),
                ("`!active_effects`",            "Активные серверные эффекты"),
                ("`!business_help`",             "Гайд по бизнес-командам"),
            ],
            "💳 Кредиты": [
                ("`!applyloan сумма дней`",    "Оформить кредит (стаж 30+ дней)"),
                ("`!calculatecredit сумма дн`","Рассчитать кредит без оформления"),
                ("`!checkloan`",               "Статус активного кредита"),
                ("`!payloan сумма`",           "Внести платёж по кредиту"),
            ],
            "📦 Работа на складе": [
                ("`!gb`",      "Начать смену (пикинг или баление, случайно)"),
                ("`!priemer`", "Показатель эффективности (влияет на зарплату)"),
            ],
            "📜 Петиции": [
                ("`!petition текст`",   "Создать петицию"),
                ("`!vote номер`",       "Подписать петицию"),
                ("`!petitions`",        "Список активных петиций"),
                ("`!yes номер`",        "🔑 Проголосовать «За» (Admin)"),
                ("`!no номер`",         "🔑 Проголосовать «Против» (Admin)"),
            ],
            "🛡️ Модерация": [
                ("`!mute @user минуты`",     "🔑 Замутить участника"),
                ("`!unmute @user`",          "🔑 Снять мут"),
                ("`!ban @user дней`",        "🔑 Забанить на N дней"),
                ("`!kick @user [причина]`",  "🔑 Кикнуть участника"),
                ("`!warn @user [причина]`",  "🔑 Выдать предупреждение"),
                ("`!warns [@user]`",         "Посмотреть варны"),
                ("`!clearwarn @user`",       "🔑 Сбросить все варны"),
                ("`!clear N`",               "🔑 Удалить N сообщений"),
                ("`!clearday N`",            "🔑 Удалить сообщения за N дней"),
                ("`!clearuser @user N`",     "🔑 Удалить N сообщений участника"),
                ("`!clearuserday @user N`",  "🔑 Удалить сообщения участника за N дней"),
            ],
            "👑 Администратор": [
                ("`!give @user сумма`",    "Выдать деньги участнику"),
                ("`!take @user сумма`",    "Снять деньги с участника"),
                ("`!setmoney @user сумма`","Установить точный баланс"),
                ("`!say текст`",           "Написать от имени бота"),
                ("`!embed заголовок текст`","Отправить красивый embed"),
                ("`!announce текст`",      "Объявление с пингом @here"),
            ],
            "🎭 Развлечения": [
                ("`!joke`",              "Случайная шутка"),
                ("`!predict`",           "Случайное предсказание"),
                ("`!8ball вопрос`",      "Магический шар — ответ на вопрос"),
                ("`!rate что-угодно`",   "Оценить что-либо по шкале 0–100"),
                ("`!coinflip` / `!cf`",  "Подбросить монетку"),
                ("`!hug @user`",         "Обнять участника"),
                ("`!slap @user`",        "Дать пощёчину"),
                ("`!kiss @user`",        "Поцеловать участника"),
                ("`!greet @user`",       "Поприветствовать участника"),
                ("`!z @user`",           "Напомнить об украинском языке"),
                ("`!random`",            "Случайный «невезучий» игрок дня"),
                ("`!pick @user`",        "Позвать участника зайти"),
            ],
            "ℹ️ Информация": [
                ("`!moneyhelp`",    "Гайд по экономике"),
                ("`!business_help`","Гайд по бизнесу"),
                ("`!help команда`", "Подробная справка по любой команде"),
            ],
        }

        # Разбиваем на несколько embed (Discord ограничивает кол-во полей)
        embeds = []
        first  = True
        for section_name, commands_list in sections.items():
            if first:
                emb = nextcord.Embed(
                    title="📖 Помощь — BAZARCIK_PM",
                    description=(
                        "Полный список команд бота. Префикс: **`!`**\n"
                        "🔑 = только администраторы\n"
                        "Подробнее по команде: **`!help <команда>`**\n\u200b"
                    ),
                    color=nextcord.Color.blurple()
                )
                first = False
            else:
                emb = nextcord.Embed(color=nextcord.Color.blurple())

            lines = "\n".join(f"{cmd} — {desc}" for cmd, desc in commands_list)
            emb.add_field(name=section_name, value=lines, inline=False)
            embeds.append(emb)

        embeds[-1].set_footer(text="Используй !help <команда> для подробной информации по любой команде")

        try:
            for emb in embeds:
                await ctx.author.send(embed=emb)
            if ctx.guild:
                await ctx.send(f"📬 {ctx.author.mention}, справка отправлена тебе в ЛС!", delete_after=8)
        except nextcord.Forbidden:
            # Если ЛС закрыты — шлём в канал (только первый embed, чтобы не спамить)
            await ctx.send(
                f"{ctx.author.mention}, разреши личные сообщения от участников сервера, "
                "чтобы получить полную справку. Показываю краткую версию здесь:",
                embed=embeds[0]
            )

    # ── !help <команда> ──────────────────────────────────────
    async def send_command_help(self, command):
        ctx = self.context
        try: await ctx.message.delete()
        except Exception: pass

        embed = nextcord.Embed(
            title=f"📋 Справка: !{command.name}",
            color=nextcord.Color.gold()
        )

        # Краткое описание
        if command.brief:
            embed.description = f"_{command.brief}_"

        # Синтаксис
        params = command.signature or ""
        embed.add_field(
            name="📌 Синтаксис",
            value=f"`!{command.name} {params}`".strip(),
            inline=False
        )

        # Подробное описание
        if command.help:
            embed.add_field(
                name="📖 Описание",
                value=command.help,
                inline=False
            )
        else:
            embed.add_field(
                name="📖 Описание",
                value="_Подробное описание отсутствует._",
                inline=False
            )

        # Псевдонимы
        if command.aliases:
            embed.add_field(
                name="🔀 Псевдонимы",
                value=", ".join(f"`!{a}`" for a in command.aliases),
                inline=False
            )

        # Проверяем, требует ли команда прав администратора
        for check in command.checks:
            if "administrator" in str(check):
                embed.add_field(
                    name="🔑 Права",
                    value="Только для администраторов сервера",
                    inline=False
                )
                break

        embed.set_footer(text="!help — список всех команд")
        await ctx.send(embed=embed)

    # ── !help <группа> ───────────────────────────────────────
    async def send_group_help(self, group):
        await self.send_command_help(group)

    # ── Команда не найдена ────────────────────────────────────
    async def command_not_found(self, string):
        return f"❌ Команда `!{string}` не найдена. Используй `!help` для списка команд."

    async def send_error_message(self, error):
        ctx = self.context
        await ctx.send(error, delete_after=8)

bot.help_command = MyHelpCommand()

# ============================================================
#  ERROR HANDLER
# ============================================================
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Недостаточно прав!", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Пропущен аргумент: `{error.param.name}`. Используй `!help {ctx.command}`", delete_after=10)
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Неверный аргумент! Используй `!help {}`".format(ctx.command), delete_after=5)
    elif isinstance(error, commands.CommandNotFound):
        pass
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"⏳ Cooldown! Попробуй через {error.retry_after:.0f}сек.", delete_after=5)
    else:
        print(f"[ERROR] Command '{ctx.command}': {error}")

# ============================================================
#  EVENTS
# ============================================================
@bot.event
async def on_ready():
    print(f"✅ {bot.user.name}#{bot.user.discriminator} запущен!")
    print(f"   Серверов: {len(bot.guilds)}")
    send_loan_warnings.start()
    daily_business_income.start()
    tax_deduction_task.start()
    weekend_competition.start()
    bot.loop.create_task(update_priemer())

@bot.event
async def on_member_join(member):
    try:
        with open("help.txt","r",encoding="utf-8") as f: help_text = f.read()
    except FileNotFoundError:
        help_text = "Добро пожаловать! Используй !help для списка команд."
    try:
        await member.send(
            f"👋 Привет, **{member.name}**! Добро пожаловать на **{member.guild.name}**!\n\n{help_text}")
    except nextcord.Forbidden:
        pass

# ============================================================
#  RUN
# ============================================================
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if not TOKEN:
    raise ValueError("DISCORD_BOT_TOKEN не найден в .env файле!")
bot.run(TOKEN)
