import nextcord
from nextcord.ext import commands, tasks
from nextcord.ui import View, Button
from nextcord import Interaction, SlashOption

import asyncio
import random
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
import os
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import time
from PIL import Image, ImageDraw, ImageFont
import io
import pytz
import re
import discord
from discord.ext import commands
from gtts import gTTS

# Устанавливаем intents
intents = nextcord.Intents.default()
intents.members = True
intents.message_content = True  # Включаем возможность читать контент сообщений
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, case_insensitive=True)

def load_jokes():
    with open('jokes.txt', 'r', encoding='utf-8') as file:
        return file.read().splitlines()

def load_predictions():
    with open('predictions.txt', 'r', encoding='utf-8') as file:
        return file.read().splitlines()

jokes = load_jokes()
predictions = load_predictions()

# Команда для шуток
@bot.command(name="joke", aliases=["randomjoke", "jokes"])
async def tell_joke(ctx):
    joke = random.choice(jokes)
    # Удаляем команду пользователя
    await ctx.message.delete()
    await ctx.send(f"{ctx.author.mention} {joke}")

# Команда для предсказаний
@bot.command(name="predict", aliases=["fortune", "prophecy"])
async def tell_prediction(ctx):
    prediction = random.choice(predictions)
    # Удаляем команду пользователя
    await ctx.message.delete()
    await ctx.send(f"{ctx.author.mention} {prediction}")

# Команда для приветствия
@bot.command(name="greet")
async def greet_user(ctx, member: nextcord.Member):
    # Удаляем команду пользователя
    await ctx.message.delete()
    # Просто отправляем приветственное сообщение
    await ctx.send(f"Привет {member.mention} от бота базарчик пм")

# Команда для мута
@bot.command(name="mute")
@commands.has_permissions(administrator=True)  # Только администраторы
async def mute(ctx, member: nextcord.Member, time: int):
    # Удаляем команду пользователя
    await ctx.message.delete()
    # Отправляем предупреждение перед наказанием
    await ctx.send(f"{member.mention}, у тебя есть 1 минута на размышление перед тем, как я наложу мут на {time} минут.")
    
    # Ожидаем 1 минуту
    await asyncio.sleep(60)

    # Создаем роль "Muted", если ее нет
    mute_role = nextcord.utils.get(ctx.guild.roles, name="БАН банан🍌")
    if not mute_role:
        mute_role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.text_channels:
            await channel.set_permissions(mute_role, speak=False, send_messages=False)

    await member.add_roles(mute_role)
    await ctx.send(f"{member.mention} был замучен на {time} минут.")
    
    # Ожидаем указанное время и снимаем мут
    await asyncio.sleep(time * 60)
    await member.remove_roles(mute_role)
    await ctx.send(f"{member.mention} мут был снят.")

# Команда для бана
@bot.command(name="ban")
@commands.has_permissions(administrator=True)  # Только администраторы
async def ban(ctx, member: nextcord.Member, time: int):
    # Удаляем команду пользователя
    await ctx.message.delete()
    # Отправляем предупреждение перед наказанием
    await ctx.send(f"{member.mention}, у тебя есть 1 минута на размышление перед тем, как я забаню тебя на {time} дней.")
    
    # Ожидаем 1 минуту
    await asyncio.sleep(60)
    
    await member.ban(reason="Бан на время", delete_message_days=7)
    await ctx.send(f"{member.mention} был забанен на {time} дней.")
    
    # Ожидаем указанное время и снимаем бан
    await asyncio.sleep(time * 86400)
    await ctx.guild.unban(member)
    await ctx.send(f"{member.mention} разбанен.")

# Команда для модерации (например, для удаления сообщений)
@bot.command(name="clear")
@commands.has_permissions(administrator=True)  # Только администраторы
async def clear(ctx, amount: int):
    # Удаляем команду пользователя
    await ctx.message.delete()
    if amount <= 0 or amount > 100:
        await ctx.send("Количество сообщений должно быть больше 0 и меньше 100.")
        return
    deleted = await ctx.channel.purge(limit=amount)
    await ctx.send(f"Удалено {len(deleted)} сообщений.", delete_after=5)
    await ctx.channel.purge(limit=1)

@bot.command(name="clearday")
@commands.has_permissions(administrator=True)  # Только администраторы
async def clearday(ctx, days: int):
    # Удаляем команду пользователя
    await ctx.message.delete()
    
    if days <= 0:
        await ctx.send("Количество дней должно быть больше 0.")
        return
    
    # Получаем временную границу
    time_limit = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)

    # Удаляем сообщения, отправленные за указанный период
    deleted = await ctx.channel.purge(after=time_limit)
    
    await ctx.send(f"Удалено {len(deleted)} сообщений за последние {days} дней.", delete_after=5)    
    
@bot.command(name="clearuser")
@commands.has_permissions(administrator=True)  # Только администраторы
async def clearuser(ctx, member: nextcord.Member, amount: int):
    # Удаляем команду пользователя
    await ctx.message.delete()
    
    if amount <= 0:
        await ctx.send("Количество сообщений должно быть больше 0.")
        return
    
    # Получаем список сообщений от пользователя
    deleted = await ctx.channel.purge(limit=amount, check=lambda message: message.author == member)
    
    await ctx.send(f"Удалено {len(deleted)} сообщений от {member.mention}.", delete_after=5)

    import datetime

@bot.command(name="clearuserday")
@commands.has_permissions(administrator=True)  # Только администраторы
async def clearuserdays(ctx, member: nextcord.Member, days: int):
    # Удаляем команду пользователя
    await ctx.message.delete()
    
    if days <= 0:
        await ctx.send("Количество дней должно быть больше 0.")
        return
    
    # Получаем текущее время UTC
    time_limit = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    
    deleted = 0
    async for message in ctx.channel.history(limit=200):
        if message.author == member and message.created_at >= time_limit:
            await message.delete()
            deleted += 1
    
    await ctx.send(f"Удалено {deleted} сообщений от {member.mention} за последние {days} дней.", delete_after=5)

    
@bot.command(name="pick")
async def pick_user(ctx, member: nextcord.Member):
    # Удаляем команду пользователя
    await ctx.message.delete()
    # Просто отправляем приветственное сообщение
    await ctx.send(f"{member.mention} а ну быстро зашол ато банчик")

@bot.command(name="z")
async def z_user(ctx, member: nextcord.Member):
    await ctx.message.delete()
    await ctx.send(f"{member.mention}! Слухай уважно! Настав час остаточно та безповоротно відмовитися від усього, що пахне московією. Жодного слова їхньою отруйною мовою, жодного виразу, жодного кальки з того, що тисячоліттями нищило нашу культуру. З цього моменту твоє слово — лише українське, чисте, міцне, як криця, що кується в полум’ї свободи. Пам’ятай: кожен, хто зберігає російське в собі, — дає ворогу маленьку шпарину, крізь яку тече його отрута. Ми, українці, не маємо права на слабкість. Ми відкидаємо все московське: мову, музику, кіно, книжки, навіть звички мислити так, як нас навчали з імперських підручників. Ми говоримо українською не тому, що так модно чи зручно, а тому, що це наш фронт, це наша зброя, це наша перемога. {member.mention}, зроби свій вибір. Залиш русизм у минулому, як брудний шматок історії, що ми спалимо разом із ворогом. Кожне твоє слово українською — це удар по імперії. Кожна твоя відмова від російського — це крок до нашої спільної свободи. Будь воїном слова, і нехай більше жоден московський звук не торкнеться твого вуст!")
    
    
import random
import asyncio
from collections import Counter
import nextcord


# Доступные и недоступные работы
# Доступные и недоступные работы
import random
import asyncio

# Доступные и недоступные работы










# Карты и их значения
card_values = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10,
    'J': 10, 'Q': 10, 'K': 10, 'A': 11
}

# Символы мастей
suits = {
    'hearts': '♥',
    'diamonds': '♦',
    'clubs': '♣',
    'spades': '♠'
}

FUNDS_FILE = "player_funds.json"

# Функция для загрузки фишек из файла
def load_funds():
    try:
        with open(FUNDS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Функция для сохранения фишек в файл
def save_funds():
    with open(FUNDS_FILE, "w") as f:
        json.dump(player_funds, f)

# Загружаем фишки при запуске бота
player_funds = load_funds()

# Загрузка данных
def load_data(file):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_data(file, data):
    with open(file, "w") as f:
        json.dump(data, f)




'''
player_businesses = load_data(BUSINESS_FILE)

# Бизнесы и их параметры

business_rewards = {
    "Киоск с едой": "Рекламный щит",
    "Автомойка": "Книга по менеджменту",
    "Лотерейный магазин": "Лотерейные билеты",
    "Офис IT-услуг": "Рабочие инструменты",
    "Фитнес-клуб": "Фирменный костюм"
}


# Функции расчёта стоимости бизнеса
def calculate_next_business_cost(user_id, base_cost):
    count = len(player_businesses.get(str(user_id), []))
    if count == 0:
        return base_cost
    elif count == 1:
        return base_cost * 5
    else:
        return base_cost * 10


# Команда: Купить бизнес
def is_business_name_unique(user_id, business_name):
    if user_id not in player_businesses:
        return True
    return all(business['name'] != business_name for business in player_businesses[user_id])


# Команда: Купить бизнес с уникальным названием
@bot.command()
async def buy_business(ctx, business_name: str, *, custom_name: str):
    user_id = str(ctx.author.id)

    if business_name not in business_types:
        await ctx.send("❌ Такого бизнеса нет!")
        return

    if len(player_businesses.get(user_id, [])) >= 3:
        await ctx.send("🚫 У вас уже 3 бизнеса!")
        return

    if not is_business_name_unique(user_id, custom_name):
        await ctx.send(f"❌ Название '{custom_name}' уже занято. Пожалуйста, выберите другое название.")
        return

    base_cost = business_types[business_name]["base_cost"]
    final_cost = calculate_next_business_cost(user_id, base_cost)

    if player_funds.get(user_id, 0) < final_cost:
        await ctx.send(f"❌ Не хватает денег (нужно {final_cost})!")
        return

    # Покупка бизнеса
    player_funds[user_id] -= final_cost
    if user_id not in player_businesses:
        player_businesses[user_id] = []
    player_businesses[user_id].append({
        "name": custom_name,
        "business_type": business_name,
        "profit": business_types[business_name]["base_profit"],
        "taxes": business_types[business_name]["taxes"],
        "service_cost": business_types[business_name]["service_cost"],
        "upgraded": False,
        "upgrade_cost": business_types[business_name]["upgrade_cost"]
    })

    save_data(FUNDS_FILE, player_funds)
    save_data(BUSINESS_FILE, player_businesses)

    await ctx.send(f"✅ Бизнес '{custom_name}' ({business_name}) куплен за {final_cost}!")


# Команда: Информация о всех бизнесах
@bot.command()
async def business_info(ctx):
    business_info_message = "**Информация о всех доступных бизнесах:**\n"

    for business_name, business_data in business_types.items():
        business_info_message += f"🏢 **{business_name}**\n"
        business_info_message += f"   - **Стоимость**: {business_data['base_cost']} 💰\n"
        business_info_message += f"   - **Прибыль**: {business_data['base_profit']} 💸\n"
        business_info_message += f"   - **Налоги**: {business_data['taxes']} 💵\n"
        business_info_message += f"   - **Стоимость обслуживания**: {business_data['service_cost']} 💼\n"
        business_info_message += f"   - **Стоимость улучшения**: {business_data['upgrade_cost']} 🛠\n\n"

    await ctx.send(business_info_message)


# Команда: Продать бизнес
@bot.command()
async def sell_business(ctx, *, business_name: str):
    user_id = str(ctx.author.id)

    if user_id not in player_businesses or not player_businesses[user_id]:
        await ctx.send("❌ У вас нет бизнеса для продажи.")
        return

    for business in player_businesses[user_id]:
        if business["name"] == business_name:
            sale_price = int(business_types[business_name]["base_cost"] * 0.7)
            player_funds[user_id] += sale_price
            player_businesses[user_id].remove(business)

            save_data(FUNDS_FILE, player_funds)
            save_data(BUSINESS_FILE, player_businesses)

            await ctx.send(f"💰 {business_name} продан за {sale_price}!")
            return

    await ctx.send("❌ У вас нет такого бизнеса.")


# Команда: Улучшить бизнес
@bot.command()
async def upgrade_business(ctx, *, business_name: str):
    user_id = str(ctx.author.id)

    if user_id not in player_businesses:
        await ctx.send("❌ У вас нет бизнеса.")
        return

    for business in player_businesses[user_id]:
        if business["name"] == business_name:
            last_upgrade = business.get("last_upgrade", 0)
            if time.time() - last_upgrade < 86400:
                await ctx.send("⏳ Улучшать можно раз в сутки!")
                return

            upgrade_count = business.get("upgrade_count", 0)
            upgrade_cost = int(business_types[business_name]["upgrade_cost"] * (1.5 ** upgrade_count))
            profit_multiplier = max(1.2, 2 - (0.2 * upgrade_count))

            if player_funds.get(user_id, 0) < upgrade_cost:
                await ctx.send(f"❌ Не хватает денег (нужно {upgrade_cost})!")
                return

            player_funds[user_id] -= upgrade_cost
            business["profit"] = int(business["profit"] * profit_multiplier)
            business["upgrade_count"] = upgrade_count + 1
            business["last_upgrade"] = time.time()

            # Уникальные предметы, которые могут выпадать
            if random.random() < 0.1:  # 10% шанс на выпадение уникального предмета
                item = use_unique_item(user_id, business_name)
                await ctx.send(item)

            save_data(FUNDS_FILE, player_funds)
            save_data(BUSINESS_FILE, player_businesses)

            await ctx.send(f"🔧 {business_name} улучшен! 📈 Новая прибыль: {business['profit']} 💰")
            return

    await ctx.send("❌ У вас нет такого бизнеса.")


# Конкуренция на выходных
@tasks.loop(hours=24)
async def weekend_competition():
    now = datetime.utcnow()
    if now.weekday() == 6 and now.hour == 23 and now.minute == 59:
        earnings = {}

        for user_id, businesses in player_businesses.items():
            earnings[user_id] = sum(b["profit"] for b in businesses)

        sorted_earnings = sorted(earnings.items(), key=lambda x: x[1], reverse=True)

        rewards = {
            0: {"upgrades": 3, "money": 500},
            1: {"upgrades": 1, "money": 200},
            2: {"upgrades": 0, "money": 100}
        }

        results = "**🏆 Итоги соревнования:**\n"
        for i, (user_id, total_profit) in enumerate(sorted_earnings[:3]):
            reward = rewards.get(i, {"upgrades": 0, "money": 0})
            player_funds[user_id] = player_funds.get(user_id, 0) + reward["money"]

            if user_id in player_businesses and player_businesses[user_id]:
                for _ in range(reward["upgrades"]):
                    business = random.choice(player_businesses[user_id])
                    business["profit"] = int(business["profit"] * 1.2)

            save_data(FUNDS_FILE, player_funds)
            save_data(BUSINESS_FILE, player_businesses)

            results += f"🥇 **{i + 1} место** – <@{user_id}> 💰 **{total_profit}** прибыли. 🏆 Приз: {reward['money']} денег и {reward['upgrades']} улучшений\n"

        channel = bot.get_channel(1353724972677201980)
        if channel:
            await channel.send(results)


# Команда: Просмотреть бизнесы
server_effects = {}  # Для хранения активных эффектов на сервере

# Бизнесы и их параметры
business_types = {
    "Киоск с едой": {"base_cost": 200, "base_profit": 20, "taxes": 10, "service_cost": 5, "upgrade_cost": 100,
                     "repair_cost": 0.2},
    "Автомойка": {"base_cost": 300, "base_profit": 25, "taxes": 8, "service_cost": 7, "upgrade_cost": 120,
                  "repair_cost": 0.25},
    "Лотерейный магазин": {"base_cost": 400, "base_profit": 30, "taxes": 12, "service_cost": 6, "upgrade_cost": 150,
                           "repair_cost": 0.3},
    "Офис IT-услуг": {"base_cost": 500, "base_profit": 40, "taxes": 15, "service_cost": 10, "upgrade_cost": 200,
                      "repair_cost": 0.35},
    "Фитнес-клуб": {"base_cost": 350, "base_profit": 28, "taxes": 5, "service_cost": 8, "upgrade_cost": 140,
                    "repair_cost": 0.15}
}

# Уникальные предметы и их эффекты
unique_items = {
    "Киоск с едой": {
        "item_name": "Фирменный фургон",
        "effect": "increase_speed",
        "duration": 86400,  # 24 часа в секундах
        "description": "Увеличивает скорость всех операций на сервере на 10% в течение 24 часов."
    },
    "Автомойка": {
        "item_name": "Промо-карты для Автомойки",
        "effect": "double_profit",
        "duration": 3600,  # 1 час в секундах
        "description": "Активирует 2x бонус к прибыли для всех игроков на сервере на 1 час."
    },
    "Лотерейный магазин": {
        "item_name": "Золотой билет",
        "effect": "increase_item_chance",
        "duration": 86400,  # 24 часа в секундах
        "description": "Увеличивает шанс выпадения редких предметов на 10% на 24 часа."
    },
    "Офис IT-услуг": {
        "item_name": "Виртуальный сервер",
        "effect": "speed_up_upgrades",
        "duration": 86400,  # 24 часа в секундах
        "description": "Ускоряет все улучшения бизнеса на 20% на сервере на 24 часа."
    },
    "Фитнес-клуб": {
        "item_name": "Персональный тренер",
        "effect": "increase_event_frequency",
        "duration": 86400,  # 24 часа в секундах
        "description": "Увеличивает количество ежедневных прибыльных событий для всех бизнесов на 10% в течение 24 часов."
    }
}


# Функции для применения эффектов
def apply_effect(effect_name, duration):
    end_time = time.time() + duration
    server_effects[effect_name] = end_time
    save_data("server_effects.json", server_effects)


def check_active_effects():
    current_time = time.time()
    expired_effects = [effect for effect, end_time in server_effects.items() if end_time < current_time]

    for effect in expired_effects:
        del server_effects[effect]

    save_data("server_effects.json", server_effects)


# Применение эффектов
def use_unique_item(user_id, business_name):
    if business_name not in unique_items:
        return "❌ Такой бизнес не существует."

    item = unique_items[business_name]
    effect = item["effect"]
    duration = item["duration"]
    apply_effect(effect, duration)

    return f"🛠 Уникальный предмет **{item['item_name']}** использован! Эффект: {item['description']}."


# Команда: Использовать уникальный предмет
@bot.command()
async def use_unique_item(ctx, business_name: str):
    user_id = str(ctx.author.id)
    message = use_unique_item(user_id, business_name)
    await ctx.send(message)


# Команда: Просмотр активных эффектов
@bot.command()
async def active_effects(ctx):
    check_active_effects()

    if not server_effects:
        await ctx.send("❌ Нет активных эффектов на сервере.")
        return

    effect_list = "\n".join(
        f"🔮 {effect} до {datetime.utcfromtimestamp(end_time).strftime('%Y-%m-%d %H:%M:%S')}"
        for effect, end_time in server_effects.items()
    )

    await ctx.send(f"**Активные эффекты на сервере:**\n{effect_list}")


# Команда: Бизнесы игрока
@bot.command()
async def businesses(ctx):
    user_id = str(ctx.author.id)

    if user_id not in player_businesses or not player_businesses[user_id]:
        await ctx.send("❌ У вас нет бизнеса.")
        return

    business_list = "\n".join(
        f"🏢 {b['name']} | 💰 {b['profit']} | 🏗 {'Улучшен' if b['upgraded'] else 'Обычный'}"
        for b in player_businesses[user_id]
    )
    await ctx.send(f"**Ваши бизнесы:**\n{business_list}")


# Команда: Просмотр предметов
@bot.command()
async def items(ctx):
    items_list = "\n".join(
        f"🎁 {item['item_name']} - {item['description']}"
        for item in unique_items.values()
    )
    await ctx.send(f"**Доступные уникальные предметы:**\n{items_list}")

@tasks.loop(hours=24)
async def tax_deduction():
    now = datetime.now(timezone.utc)

    if now.hour == 19 and now.minute == 0:  # Списание налогов каждую полночь
        for user_id, businesses in player_businesses.items():
            total_taxes = 0
            for business in businesses:
                total_taxes += business["taxes"]
                player_funds[user_id] -= business["taxes"]

            save_data(FUNDS_FILE, player_funds)

            channel = bot.get_channel(1353724972677201980)  # Укажите свой канал
            user_mention = f"<@{user_id}>"
            if channel:
                await channel.send(f"{user_mention}, у вас списано {total_taxes} налогов. Ваш баланс: {player_funds[user_id]}.")


# Команда: Ремонт бизнеса
@bot.command()
async def repair_business(ctx, *, business_name: str):
    user_id = str(ctx.author.id)

    if user_id not in player_businesses or not player_businesses[user_id]:
        await ctx.send("❌ У вас нет бизнеса.")
        return

    for business in player_businesses[user_id]:
        if business["name"] == business_name:
            repair_cost = int(business_types[business_name]["base_cost"] * business["repair_cost"])

            if player_funds.get(user_id, 0) < repair_cost:
                await ctx.send(f"❌ Не хватает денег для ремонта (нужно {repair_cost})!")
                return

            player_funds[user_id] -= repair_cost
            save_data(FUNDS_FILE, player_funds)

            await ctx.send(f"🔧 {business_name} отремонтирован! Стоимость ремонта: {repair_cost}.")
            return

    await ctx.send("❌ У вас нет такого бизнеса.")


@bot.command()
async def business_help(ctx):
    # Открываем файл и читаем его содержимое
    try:
        with open('business_help.txt', 'r', encoding='utf-8') as file:
            help_message = file.read()

        # Отправляем сообщение
        await ctx.send(help_message)

    except FileNotFoundError:
        await ctx.send("Извините, файл с помощью не найден.")
'''




# Функция для создания новой колоды
def create_deck():
    deck = [(card, suit) for suit in suits for card in card_values]
    random.shuffle(deck)
    return deck

# Функция для подсчета суммы карт
def calculate_hand(hand):
    total = sum(card_values[card] for card, _ in hand)
    aces = sum(1 for card, _ in hand if card == 'A')
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

# Функция для инициализации фишек игрока
async def init_player_funds(ctx):
    if str(ctx.author.id) not in player_funds:
        player_funds[str(ctx.author.id)] = 1000  # Начальные фишки
        save_funds()

# Команда для игры в Блекджек с учетом ставок

def calculate_tax(profit):
    if profit > 20000:
        tax = profit * 0.18  # 18% налог
        return int(tax)
    return 0


# Блэкджек
@bot.command(name="bj")
async def blackjack(ctx, bet: int):
    await ctx.message.delete()
    await init_player_funds(ctx)
    if bet <= 0:
        await ctx.send("Ставка должна быть положительным числом.")
        return
    if bet > player_funds[str(ctx.author.id)]:
        await ctx.send("У вас недостаточно денег для этой ставки.")
        return

    player_funds[str(ctx.author.id)] -= bet  # Вычитаем ставку из фишек
    save_funds()
    deck = create_deck()
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]
    await ctx.send(f"{ctx.author.mention} начал игру в Блэкджек. Ставка: {bet}")
    await ctx.send(
        f"Ваши карты: {', '.join([f'{card[0]}{suits[card[1]]}' for card in player_hand])} (Сумма: {calculate_hand(player_hand)})")
    await ctx.send(f"Карты дилера: {dealer_hand[0][0]}{suits[dealer_hand[0][1]]} и скрытая карта.")

    if calculate_hand(player_hand) == 21:  # Проверка на блэкджек
        winnings = bet * 3  # Больше награда за блэкджек
        player_funds[str(ctx.author.id)] += winnings
        save_funds()
        tax = calculate_tax(winnings - bet)  # Чистая прибыль - ставка
        if tax > 0:
            player_funds[str(ctx.author.id)] -= tax
            save_funds()
            await ctx.send(f"Налог с выигрыша: {tax} денег.")
        await ctx.send(
            f"Поздравляем, у {ctx.author.mention} Блэкджек! Вы выиграли {winnings} денег! Теперь у вас {player_funds[str(ctx.author.id)]} денег.")
        return

    while calculate_hand(player_hand) < 21:
        await ctx.send("Хотите взять еще карту? Введите !hit для добора или !stand для завершения.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ['!hit', '!stand']

        msg = await bot.wait_for('message', check=check)

        # Удаление сообщения с командой после получения
        await msg.delete()

        if msg.content.lower() == '!hit':
            player_hand.append(deck.pop())
            await ctx.send(
                f"Вы взяли {player_hand[-1][0]}{suits[player_hand[-1][1]]}. (Сумма: {calculate_hand(player_hand)})")
            if calculate_hand(player_hand) > 21:
                await ctx.send(
                    f"{ctx.author.mention} проиграл! Сумма ваших карт: {calculate_hand(player_hand)}. Вы превысили 21!")
                return
        elif msg.content.lower() == '!stand':
            break

    while calculate_hand(dealer_hand) < 17:
        dealer_hand.append(deck.pop())

    await ctx.send(
        f"Карты дилера: {', '.join([f'{card[0]}{suits[card[1]]}' for card in dealer_hand])}. (Сумма: {calculate_hand(dealer_hand)})")

    player_total = calculate_hand(player_hand)
    dealer_total = calculate_hand(dealer_hand)

    if player_total > 21:
        await ctx.send("Вы проиграли, так как превысили 21!")
    elif dealer_total > 21 or player_total > dealer_total:
        winnings = bet * 2
        player_funds[str(ctx.author.id)] += winnings
        save_funds()
        tax = calculate_tax(winnings - bet)  # Чистая прибыль - ставка
        if tax > 0:
            player_funds[str(ctx.author.id)] -= tax
            save_funds()
            await ctx.send(f"Налог с выигрыша: {tax} денег.")
        await ctx.send(
            f"{ctx.author.mention} выиграл! Ваш выигрыш: {winnings} денег. Теперь у вас {player_funds[str(ctx.author.id)]} денег.")
    elif player_total < dealer_total:
        await ctx.send(f"{ctx.author.mention} проиграл! Теперь у вас {player_funds[str(ctx.author.id)]} денег.")
    else:
        player_funds[str(ctx.author.id)] += bet  # Возвращаем ставку при ничье
        save_funds()
        await ctx.send(
            f"Ничья {ctx.author.mention}! Ваша ставка возвращена. У вас {player_funds[str(ctx.author.id)]} денег.")


# Команда для игрового автомата (flip)
@bot.command()
async def flip(ctx, bet: int, choice: str):
    await ctx.message.delete()
    await init_player_funds(ctx)

    if bet > player_funds[str(ctx.author.id)]:
        await ctx.send("У вас недостаточно денег для этой ставки.")
        return
    if bet <= 0:
        await ctx.send("Ставка должна быть положительным числом.")
        return

    choice = choice.strip().lower()
    valid_choices = ["о", "орел", "o", "orel", "р", "решка", "p", "reshka"]

    if choice not in valid_choices:
        await ctx.send("Вы должны выбрать Орел (о, o, орел) или Решка (р, p, решка).")
        return

    choice_result = "Орел" if choice in ["о", "орел", "o", "orel"] else "Решка"

    player_funds[str(ctx.author.id)] -= bet
    save_funds()
    result = random.choice(["о", "р", "o", "p"])
    result_str = "Орел" if result in ["о", "o"] else "Решка"

    if result_str == choice_result:
        winnings = bet * 2
        player_funds[str(ctx.author.id)] += winnings
        save_funds()
        tax = calculate_tax(winnings - bet)  # Чистая прибыль - ставка
        if tax > 0:
            player_funds[str(ctx.author.id)] -= tax
            save_funds()
            await ctx.send(f"Налог с выигрыша: {tax} денег.")
        await ctx.send(
            f"{ctx.author.mention} выиграл! Выпал {result_str}. Выигрыш: {winnings} денег. У вас теперь {player_funds[str(ctx.author.id)]} денег.")
    else:
        await ctx.send(
            f"{ctx.author.mention} проиграл. Выпал {result_str}. У вас теперь {player_funds[str(ctx.author.id)]} денег.")


@bot.command()
async def spin(ctx, bet: int):
    await ctx.message.delete()
    await init_player_funds(ctx)
    if bet > player_funds[str(ctx.author.id)]:
        await ctx.send("У вас недостаточно денег для этой ставки.")
        return
    if bet <= 0:
        await ctx.send("Ставка должна быть положительным числом.")
        return

    player_funds[str(ctx.author.id)] -= bet
    save_funds()
    symbols = ["🍒", "🍋", "🍉", "🍇", "🍊", "🍍"]
    spin_result = [random.choice(symbols) for _ in range(3)]

    await ctx.send(f"{ctx.author.mention} крутит слоты... | Результат: {' | '.join(spin_result)}")

    if len(set(spin_result)) == 1:  # Все три символа одинаковые
        winnings = bet * 5
        player_funds[str(ctx.author.id)] += winnings
        save_funds()
        tax = calculate_tax(winnings - bet)  # Чистая прибыль - ставка
        if tax > 0:
            player_funds[str(ctx.author.id)] -= tax
            save_funds()
            await ctx.send(f"Налог с выигрыша: {tax} денег.")
        await ctx.send(f"{ctx.author.mention} выиграл! Все символы совпали! Выигрыш: {winnings} денег. У вас теперь {player_funds[str(ctx.author.id)]} денег.")
    elif len(set(spin_result)) == 2:  # Два одинаковых символа
        winnings = bet * 2
        player_funds[str(ctx.author.id)] += winnings
        save_funds()
        tax = calculate_tax(winnings - bet)  # Чистая прибыль - ставка
        if tax > 0:
            player_funds[str(ctx.author.id)] -= tax
            save_funds()
            await ctx.send(f"Налог с выигрыша: {tax} денег.")
        await ctx.send(f"{ctx.author.mention} выиграл! Два символа совпали! Выигрыш: {winnings} денег. У вас теперь {player_funds[str(ctx.author.id)]} денег.")
    else:
        await ctx.send(f"{ctx.author.mention} проиграл. У вас теперь {player_funds[str(ctx.author.id)]} денег.")



AVAILABLE_JOBS = ["пикинг", "баление"]
UNAVAILABLE_JOBS = ["бафер", "боксы", "вратки"]

# Список товаров с брендами
SPORT_ITEMS_WITH_BRANDS = {
    "GymBeam": ["Протеиновый батончик", "Креатин", "BCAA", "Коллаген"],
    "BeastPink": ["Лосины", "Спортивные шорты", "Шейкер"],
    "VanaVita": ["Гейнер", "Витамины B", "Коллаген для суставов"],
    "XBEAM": ["Ремни для жима", "Фитнес-трекеры", "Протеиновые батончики"],
    "STRIX": ["Энергетические гели", "Силовые тренажеры"],
    "BSN": ["Гейнер", "Креатин моногидрат", "БЦАА"],
    "Muscletech": ["Гейнер", "Креатин моногидрат", "Протеиновые батончики"],
    "NOW Foods": ["Омега-3", "Витамин C", "Л-карнитин"],
    "The Protein Works": ["Протеиновый коктейль", "Шейкер", "Гейнер"],
    "Universal": ["Гейнер", "Протеиновый коктейль", "Креатин"]
}

# Хранение заказов
ORDERS = {}
ORDER_MESSAGES = {}

ORDERS_COMPLETED_FILE = "orders_completed.json"

def load_orders_completed():
    try:
        with open(ORDERS_COMPLETED_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_orders_completed():
    with open(ORDERS_COMPLETED_FILE, "w", encoding="utf-8") as file:
        json.dump(USER_ORDERS_COMPLETED, file, indent=4)

USER_ORDERS_COMPLETED = load_orders_completed()

PRIEMER_FILE = "priemer_data.json"

def generate_baling_order():
    num_items = random.randint(1, 30)
    items = []
    for _ in range(num_items):
        brand = random.choice(list(SPORT_ITEMS_WITH_BRANDS.keys()))
        item = random.choice(SPORT_ITEMS_WITH_BRANDS[brand])
        items.append(f"{brand} - {item}")
    return items

class PackingView(View):
    def __init__(self, user_id: int, order_size: int):
        super().__init__()
        self.user_id = user_id
        self.order_size = order_size
        self.remaining_items = order_size
        self.selected_box = None

        self.exit_button = Button(label="Выйти с работы", style=nextcord.ButtonStyle.red, disabled=True)
        self.exit_button.callback = self.exit_job

        box_sizes = {
            "A": range(1, 7),
            "B": range(7, 13),
            "C": range(13, 19),
            "D": range(19, 25),
            "E": range(25, 31),
        }

        for box in box_sizes.keys():
            button = Button(label=f"Коробка {box}", style=nextcord.ButtonStyle.blurple)
            button.callback = self.create_box_callback(box)
            self.add_item(button)

        self.collect_button = Button(label="Собрать товар", style=nextcord.ButtonStyle.green, disabled=True)
        self.collect_button.callback = self.collect_item
        self.add_item(self.collect_button)
        self.add_item(self.exit_button)

    def create_box_callback(self, box: str):
        async def callback(interaction: nextcord.Interaction):
            await self.select_box(interaction, box)
        return callback

    async def select_box(self, interaction: nextcord.Interaction, box: str):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        box_sizes = {
            "A": range(1, 7),
            "B": range(7, 13),
            "C": range(13, 19),
            "D": range(19, 25),
            "E": range(25, 31),
        }

        if self.order_size not in box_sizes[box]:
            await interaction.response.send_message(f"Эта коробка не подходит! Выберите подходящий размер.", ephemeral=True)
            return

        self.selected_box = box
        self.collect_button.disabled = False
        await interaction.message.edit(content=f"{interaction.user.mention}, выбрана коробка {box}. Осталось собрать: {self.remaining_items} товаров.", view=self)

    async def collect_item(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        if self.remaining_items > 0:
            self.remaining_items -= random.randint(1, min(5, self.remaining_items))  # Собираем 1-5 товаров за раз
            if self.remaining_items > 0:
                await interaction.message.edit(content=f"{interaction.user.mention}, осталось собрать: {self.remaining_items} товаров.", view=self)
            else:
                await self.complete_order(interaction)

    async def complete_order(self, interaction: nextcord.Interaction):
        earnings = random.randint(50, 10000)
        player_funds[str(self.user_id)] = player_funds.get(str(self.user_id), 0) + earnings
        save_funds()

        self.clear_items()
        self.exit_button.disabled = False
        new_order_button = Button(label="Начать новый заказ", style=nextcord.ButtonStyle.green)
        new_order_button.callback = self.start_new_order
        self.add_item(new_order_button)
        self.add_item(self.exit_button)

        await interaction.message.edit(content=f"{interaction.user.mention}, заказ завершен! Вы заработали {earnings} денег.\nХотите начать новый заказ?", view=self)

    async def start_new_order(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        new_order_size = random.randint(1, 30)
        new_view = PackingView(self.user_id, new_order_size)
        await interaction.message.edit(content=f"{interaction.user.mention}, новый заказ из {new_order_size} товаров. Выберите коробку.", view=new_view)

    async def exit_job(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        await interaction.message.edit(content=f"{interaction.user.mention}, вы вышли с работы.", view=None)


class OrderProcessingView(View):
    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id
        self.pick_button = Button(label="Собирать товары", style=nextcord.ButtonStyle.green)
        self.pick_button.callback = self.collect_items
        self.add_item(self.pick_button)

    async def collect_items(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        if user_id not in ORDERS:
            await interaction.response.send_message("У вас нет активного заказа!", ephemeral=True)
            return

        items = ORDERS[user_id]

        num_to_collect = min(random.randint(1, 5), len(items))
        collected_items = items[:num_to_collect]
        ORDERS[user_id] = items[num_to_collect:]

        collected_list = "\n".join([f"✅ {item['item']}" for item in collected_items])
        remaining_list = "\n".join([f"{i+1}. {item['item']}" for i, item in enumerate(ORDERS[user_id])])

        if ORDERS[user_id]:
            await interaction.message.edit(content=f"{interaction.user.mention}, вы собрали:\n{collected_list}\n\nОсталось:\n{remaining_list}")
        else:
            await self.complete_order(interaction)

    async def complete_order(self, interaction: nextcord.Interaction):
        user_id = str(interaction.user.id)
        earnings = random.randint(50, 100000)

        player_funds[user_id] = player_funds.get(user_id, 0) + earnings
        save_funds()
        del ORDERS[user_id]

        self.clear_items()
        exit_button = Button(label="Выйти с работы", style=nextcord.ButtonStyle.red)
        exit_button.callback = self.exit_job
        self.add_item(exit_button)

        new_order_button = Button(label="Начать новый заказ", style=nextcord.ButtonStyle.green)
        new_order_button.callback = self.start_new_order
        self.add_item(new_order_button)

        await interaction.message.edit(content=f"{interaction.user.mention}, заказ завершен! Вы заработали {earnings} денег.", view=self)

    async def exit_job(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return
        await interaction.message.edit(content=f"{interaction.user.mention}, вы вышли с работы.", view=None)

    async def start_new_order(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        order_size = random.randint(1, 30)
        ORDERS[user_id] = [{"item": random.choice(random.choice(list(SPORT_ITEMS_WITH_BRANDS.values())))} for _ in range(order_size)]

        view = PackingView(user_id, order_size)
        await interaction.channel.send(f"{interaction.user.mention}, выберите коробку для заказа из {order_size} товаров.", view=view)

class BalingView(View):
    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id
        self.box_selected = None
        self.items_collected = []
        self.box_button = Button(label="Выбрать коробку", style=nextcord.ButtonStyle.blurple)
        self.box_button.callback = self.select_box
        self.collect_button = Button(label="Собирать заказ", style=nextcord.ButtonStyle.green, disabled=True)
        self.collect_button.callback = self.collect_items
        self.send_button = Button(label="Отправить коробку", style=nextcord.ButtonStyle.red, disabled=True)
        self.send_button.callback = self.send_box
        self.add_item(self.box_button)
        self.add_item(self.collect_button)
        self.add_item(self.send_button)

    async def select_box(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        order_size = len(ORDERS[user_id])
        if order_size <= 6:
            self.box_selected = "A"
        elif order_size <= 12:
            self.box_selected = "B"
        elif order_size <= 18:
            self.box_selected = "C"
        elif order_size <= 24:
            self.box_selected = "D"
        else:
            self.box_selected = "E"

        self.box_button.disabled = True
        self.collect_button.disabled = False
        await interaction.message.edit(content=f"{interaction.user.mention}, выбрана коробка {self.box_selected}. Начинайте сборку заказа!", view=self)

    async def collect_items(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        order_items = ORDERS[user_id]

        if not order_items:
            self.collect_button.disabled = True
            self.send_button.disabled = False
            await interaction.message.edit(content=f"{interaction.user.mention}, заказ собран! Отправьте коробку.", view=self)
            return

        num_to_collect = min(random.randint(1, 5), len(order_items))
        collected = order_items[:num_to_collect]
        self.items_collected.extend(collected)
        del ORDERS[user_id][:num_to_collect]

        remaining = len(ORDERS[user_id])
        await interaction.message.edit(content=f"{interaction.user.mention}, собрано {len(self.items_collected)} товаров. Осталось {remaining}.", view=self)

    async def send_box(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        if user_id not in priemer_data:
            priemer_data[user_id] = 0

        earnings = random.randint(50, 100000)
        player_funds[user_id] = player_funds.get(user_id, 0) + earnings
        save_funds()

        del ORDERS[user_id]
        del ORDER_MESSAGES[user_id]

        await interaction.message.edit(content=f"{interaction.user.mention}, заказ отправлен! Вы заработали {earnings} денег.", view=None)



def load_priemer():
    try:
        with open(PRIEMER_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_priemer():
    with open(PRIEMER_FILE, "w", encoding="utf-8") as file:
        json.dump(priemer_data, file, indent=4)

priemer_data = load_priemer()

order_history = {}  # Хранение количества заказов и позиций за последний час

async def update_priemer():
    decay_counter = 0  # Счетчик для уменьшения премиума

    while True:
        await asyncio.sleep(60)  # Обновление каждую минуту
        decay_counter += 1  # Увеличиваем счетчик времени

        for user_id in priemer_data:
            orders = order_history.get(user_id, [])
            if orders:
                avg_orders_per_min = len(orders)
                avg_positions_per_order = sum(orders) / avg_orders_per_min
                increase = (avg_orders_per_min * avg_positions_per_order) / 10
                priemer_data[user_id] = int(min(150, priemer_data[user_id] + increase))
            else:
                if decay_counter >= 60:  # Уменьшать премиум только раз в 60 минут
                    priemer_data[user_id] = int(max(0, priemer_data[user_id] - 1))

        if decay_counter >= 60:
            decay_counter = 0  # Сбрасываем счетчик после уменьшения

        save_priemer()
        order_history.clear()

loop = asyncio.get_event_loop()
loop.create_task(update_priemer())

@bot.command()
async def priemer(ctx):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    if user_id in priemer_data:
        await ctx.send(f"Priemer {ctx.author.mention}: {priemer_data[user_id]}")
    else:
        await ctx.send("Вы еще не начали работать!")

def generate_order():
    num_positions = random.randint(1, 30)
    positions = []
    for _ in range(num_positions):
        brand = random.choice(list(SPORT_ITEMS_WITH_BRANDS.keys()))
        item = random.choice(SPORT_ITEMS_WITH_BRANDS[brand])
        location = f"3{random.choice('BC')}{random.randint(1, 56)}{random.choice('ABCDEFGHJ')}{random.randint(1, 4)}"
        positions.append({"location": location, "item": f"{brand} - {item}", "status": "не выполнено"})
    return positions

class PickingView(View):
    def __init__(self, user_id: int):
        super().__init__()
        self.user_id = user_id
        self.pick_button = Button(label="Skenovat' produkt", style=nextcord.ButtonStyle.green)
        self.pick_button.callback = self.pick_positions
        self.exit_button = Button(label="Выйти с работы", style=nextcord.ButtonStyle.red)
        self.exit_button.callback = self.exit_job
        self.exit_button.disabled = True  # Сначала кнопка "Выйти с работы" неактивна
        self.add_item(self.pick_button)
        self.add_item(self.exit_button)
        self.disabled = False  # Флаг блокировки кнопки

    async def pick_positions(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return
        
        user_id = str(interaction.user.id)

        if user_id not in ORDERS:
            await interaction.response.send_message("У вас нет активного заказа!", ephemeral=True)
            return

        if self.disabled:
            await interaction.response.send_message("Подождите перед следующим нажатием!", ephemeral=True)
            return
        
        positions = [p for p in ORDERS[user_id] if p["status"] == "не выполнено"]
        
        if not positions:
            await self.finish_order(interaction)
            return

        if random.random() < 0.03:
            self.pick_button.disabled = True
            self.disabled = True
            time = random.randint(60, 300)
            for remaining in range(time, 0, -1):
                await interaction.message.edit(content=f"{interaction.user.mention}, у вас ошибка в телефоне, ждем сапорта. Ожидание: {remaining} сек.", view=self)
                await asyncio.sleep(1)
            self.pick_button.disabled = False
            self.disabled = False
            await interaction.message.edit(content=f"{interaction.user.mention}, можете продолжать пикинг.", view=self)
            return

        num_to_pick = random.randint(1, 5)
        for _ in range(min(num_to_pick, len(positions))):
            positions[0]["status"] = "выполнено"
            positions.pop(0)

        incomplete = []
        completed = []

        for i, p in enumerate(ORDERS[user_id]):
            if p["status"] == "не выполнено":
                incomplete.append(f"{i+1}. {p['location']} ({p['item']})")
            else:
                completed.append(f"✅~~{i+1}. {p['location']} ({p['item']})~~✅")

        pickup_list = "\n".join(completed) + "\n" + "\n" + "\n".join(incomplete)

        await interaction.message.edit(content=f"{interaction.user.mention}, обновленный пикап лист:\n{pickup_list}")

        if not positions:
            await self.switch_to_finish_button(interaction)
        else:
            delay = random.randint(1, 5)
            self.pick_button.disabled = True
            await interaction.message.edit(view=self)
            await asyncio.sleep(delay)
            self.pick_button.disabled = False
            await interaction.message.edit(view=self)

    async def switch_to_finish_button(self, interaction: nextcord.Interaction):
        """Заменяет кнопку 'Сканировать продукт' на кнопки завершения заказа и выхода с работы."""
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        self.clear_items()
        finish_button = Button(label="Odoslat' objednavku", style=nextcord.ButtonStyle.blurple)
        finish_button.callback = self.finish_order
        self.add_item(finish_button)
        self.add_item(self.exit_button)  # Разблокировать кнопку "Выйти с работы"
        await interaction.message.edit(view=self)

    async def finish_order(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        num_positions = len(ORDERS[user_id])
        priemer_data[user_id] = priemer_data.get(user_id, 0)

        if user_id not in order_history:
            order_history[user_id] = []
        order_history[user_id].append(num_positions)

        if priemer_data[user_id] < 60:
            earnings = random.randint(50, 10000)
        elif priemer_data[user_id] < 80:
            earnings = random.randint(10000, 20000)
        elif priemer_data[user_id] < 120:
            earnings = random.randint(20000, 50000)
        else:
            earnings = random.randint(50000, 100000)

        tax = 0.07 if earnings <= 47000 else 0.19
        tax_amount = int(earnings * tax)
        earnings_after_tax = earnings - tax_amount

        player_funds[user_id] = player_funds.get(user_id, 0) + earnings_after_tax
        save_funds()
        del ORDERS[user_id]
        del ORDER_MESSAGES[user_id]
        await interaction.message.edit(
            content=f"{interaction.user.mention}, заказ завершен! Вы заработали {earnings} денег. Налог: {tax_amount}. Итоговая сумма: {earnings_after_tax}. Ваш priemer: {priemer_data[user_id]}",
            view=None)
        self.exit_button.disabled = False
        await self.show_new_order_button(interaction)
    
    async def start_new_order(self, interaction: nextcord.Interaction):
        """Начинает новый заказ."""
        # Проверка, что кнопка нажата пользователем, который выполняет заказ
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        user_id = str(interaction.user.id)
        ORDERS[user_id] = generate_order()  # Генерируем новый заказ

        pickup_list = "\n".join([ 
            f"{i+1}. {order['location']} ({order['item']})"
            for i, order in enumerate(ORDERS[user_id])
        ])

        view = PickingView(user_id)

        message = await interaction.channel.send(
            f"{interaction.user.mention}, вы начали новый заказ из {len(ORDERS[user_id])} позиций. Ваш priemer: {priemer_data[user_id]}\n\n**Пикап лист:**\n{pickup_list}",
            view=view
        )

        ORDER_MESSAGES[user_id] = message.id
        await interaction.message.delete() 
    
    async def show_new_order_button(self, interaction: nextcord.Interaction):
        """Показывает кнопку для начала нового заказа после завершения текущего."""
        # Проверка, что кнопка нажата пользователем, который выполняет заказ
        if str(interaction.user.id) != self.user_id:
            return

        self.clear_items()
        new_order_button = Button(label="Начать новый заказ", style=nextcord.ButtonStyle.green)
        new_order_button.callback = self.start_new_order  # Устанавливаем callback на новый метод
        self.add_item(new_order_button)
        self.add_item(self.exit_button)  # Оставляем кнопку "Выйти с работы"
        await interaction.message.edit(view=self)

    
    async def show_exit_button(self, interaction: nextcord.Interaction):
        """Показывает кнопку "Выйти с работы" после завершения заказа."""
        if str(interaction.user.id) != self.user_id:
            return

        self.clear_items()
        self.add_item(self.exit_button)
        await interaction.message.edit(view=self)

    async def exit_job(self, interaction: nextcord.Interaction):
        """Заканчивает работу и уведомляет о выходе."""
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        user_id = str(interaction.user.id)

        # Проверка, есть ли заказ у пользователя
        if user_id in ORDERS:
            del ORDERS[user_id]  # Удаляем заказ, если он существует
            del ORDER_MESSAGES[user_id]  # Удаляем сообщение заказа
        await interaction.message.edit(content=f"{interaction.user.mention}, вы вышли с работы.", view=None)


@bot.command(name="gb")
async def start_job(ctx):
    await ctx.message.delete()
    job = random.choice(["пикинг", "баление"])

    if job not in ["пикинг", "баление"]:
        await ctx.send(f"{ctx.author.mention}, такой работы не существует!")
        return

    user_id = str(ctx.author.id)

    if job == "пикинг":
        ORDERS[user_id] = generate_order()
        priemer_data[user_id] = priemer_data.get(user_id, 0)
        save_priemer()

        pickup_list = "\n".join([f"{i+1}. {order['location']} ({order['item']})" for i, order in enumerate(ORDERS[user_id])])
        view = PickingView(user_id)

        message = await ctx.send(
            f"{ctx.author.mention}, вы начали работу на пикинге. Вам выдан заказ из {len(ORDERS[user_id])} позиций. Ваш priemer: {priemer_data[user_id]}\n\n**Пикап лист:**\n{pickup_list}",
            view=view
        )
        ORDER_MESSAGES[user_id] = message.id

    elif job == "баление":
        order_size = random.randint(1, 30)
        ORDERS[user_id] = [{"item": random.choice(random.choice(list(SPORT_ITEMS_WITH_BRANDS.values())))} for _ in range(order_size)]

        view = PackingView(user_id, order_size)
        await ctx.send(f"{ctx.author.mention}, выберите коробку для заказа из {order_size} товаров.", view=view) # Сохраняем ID сообщения  # Сохраняем ID сообщения  # Сохраняем ID сообщения
# Проверка фишек

@bot.command(name="pay")
async def pay(ctx, member: nextcord.Member, amount: int):
    """Позволяет перевести деньги другому пользователю."""
    await ctx.message.delete()
    sender_id = str(ctx.author.id)
    receiver_id = str(member.id)

    # Проверка корректности суммы
    if amount <= 0:
        await ctx.send(f"{ctx.author.mention}, сумма перевода должна быть положительным числом!")
        return

    # Проверяем, есть ли у отправителя достаточно денег
    if player_funds.get(sender_id, 0) < amount:
        await ctx.send(f"{ctx.author.mention}, у вас недостаточно средств для перевода!")
        return

    # Совершаем перевод
    player_funds[sender_id] -= amount
    player_funds[receiver_id] = player_funds.get(receiver_id, 0) + amount

    # Сохраняем изменения
    save_funds()

    # Подтверждаем перевод
    await ctx.send(f"{ctx.author.mention} отправил {amount} денег {member.mention}!")


LOANS_FILE = "player_loans.json"

# Функция для загрузки данных о кредитах
def load_loans():
    try:
        with open(LOANS_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# Функция для сохранения данных о кредитах
def save_loans():
    with open(LOANS_FILE, "w") as f:
        json.dump(player_loans, f)


# Загружаем данные при запуске бота
player_loans = load_loans()


# Функция для расчета возраста пользователя на сервере
async def get_user_age_on_server(ctx, user_id):
    try:
        member = await ctx.guild.fetch_member(user_id)
    except Exception as e:
        print(f"Ошибка при получении участника: {e}")
        return None

    if member is None:
        return None

    join_date = member.joined_at
    if not join_date:
        return None

    join_date = join_date.astimezone(pytz.utc)
    today = datetime.now(pytz.utc)
    age_on_server = (today - join_date).days
    return age_on_server

# Функция для получения максимальной суммы кредита
def get_max_loan_amount(age_on_server):
    if age_on_server < 30:
        return 0
    elif age_on_server < 60:
        return 100000
    elif age_on_server < 90:
        return 300000
    elif age_on_server < 120:
        return 500000
    else:
        return 1000000

# Функция для расчета ежедневного платежа
def calculate_daily_payment(loan_amount, loan_term, interest_rate):
    total_amount_to_pay = loan_amount * (1 + interest_rate)
    daily_payment = total_amount_to_pay / loan_term
    return int(daily_payment)

# Функция для получения процентной ставки
def get_interest_rate(age_on_server):
    if age_on_server > 120:
        return 0.15
    return 0.20

# Функция для оформления кредита
@bot.command()
async def applyloan(ctx, loan_amount: int, loan_term: int):
    await ctx.message.delete()
    user_id = str(ctx.author.id)

    # Проверяем, есть ли уже активный кредит
    if user_id in player_loans and player_loans[user_id]:
        await ctx.send(f"{ctx.author.mention}, у вас уже есть активный кредит. Погасите его, прежде чем брать новый.")
        return

    if loan_term > 7:
        await ctx.send("Максимальный срок кредита — 7 дней.")
        return

    age_on_server = await get_user_age_on_server(ctx, ctx.author.id)
    if age_on_server is None:
        await ctx.send(f"{ctx.author.mention}, не удалось получить информацию о вашем возрасте на сервере.")
        return

    max_loan = get_max_loan_amount(age_on_server)
    if loan_amount > max_loan:
        await ctx.send(f"Вы можете взять кредит не более {max_loan}.")
        return

    interest_rate = get_interest_rate(age_on_server)
    daily_payment = calculate_daily_payment(loan_amount, loan_term, interest_rate)
    due_date = (datetime.now() + timedelta(days=loan_term)).strftime("%Y-%m-%d")

    # Записываем новый кредит
    player_loans[user_id] = [{
        "loan_amount": loan_amount,
        "interest_rate": interest_rate,
        "daily_payment": daily_payment,
        "loan_term": loan_term,
        "due_date": due_date,
        "paid_amount": 0
    }]

    # Добавляем деньги пользователю
    player_funds[user_id] = player_funds.get(user_id, 0) + loan_amount

    save_funds()
    save_loans()

    await ctx.send(
        f"{ctx.author.mention} взял кредит на {loan_amount} денег. Ежедневный платеж: {daily_payment} денег.\n"
        f"Дата погашения: {due_date}. Ваш текущий баланс: {player_funds[user_id]} денег."
    )





# Функция для расчета кредита
@bot.command()
async def calculatecredit(ctx, loan_amount: int, loan_term: int):
    await ctx.message.delete()
    age_on_server = await get_user_age_on_server(ctx, ctx.author.id)
    interest_rate = get_interest_rate(age_on_server)
    daily_payment = calculate_daily_payment(loan_amount, loan_term, interest_rate)

    await ctx.send(f"Кредит на сумму {loan_amount} на {loan_term} дней.\n"
                   f"Процентная ставка: {interest_rate * 100}%.\n"
                   f"Ежедневный платеж: {daily_payment:.2f}")


# Функция для проверки и отправки предупреждений
@tasks.loop(minutes=60)
async def send_loan_warnings():
    for user_id, loans in player_loans.items():
        for loan in loans:
            due_date = datetime.strptime(loan['due_date'], "%Y-%m-%d")
            if due_date - datetime.now() == timedelta(days=3):
                user = bot.get_user(int(user_id))
                if user:
                    await user.send(f"Ваш кредит сроком до {loan['due_date']} истекает через 3 дня.")
            elif due_date - datetime.now() == timedelta(days=1):
                user = bot.get_user(int(user_id))
                if user:
                    await user.send(f"Ваш кредит сроком до {loan['due_date']} истекает через 1 день.")
            elif due_date - datetime.now() == timedelta(hours=12):
                user = bot.get_user(int(user_id))
                if user:
                    await user.send(f"Ваш кредит сроком до {loan['due_date']} истекает через 12 часов.")
            elif due_date - datetime.now() == timedelta(hours=1):
                user = bot.get_user(int(user_id))
                if user:
                    await user.send(f"Ваш кредит сроком до {loan['due_date']} истекает через 1 час.")

# Функция для проверки и обновления погашения кредита
@bot.command()
async def checkloan(ctx):
    await ctx.message.delete()
    user_id = str(ctx.author.id)

    if user_id not in player_loans or not player_loans[user_id]:
        await ctx.send(f"{ctx.author.mention}, у вас нет активного кредита.")
        return

    loan = player_loans[user_id][0]  # Берем единственный кредит
    loan_amount = loan['loan_amount']
    interest_rate = loan['interest_rate']

    total_debt = int(loan_amount * (1 + interest_rate))  # Общая сумма с процентами
    paid_amount = loan.get('paid_amount', 0)
    remaining_amount = total_debt - paid_amount

    due_date = datetime.strptime(loan['due_date'], "%Y-%m-%d")
    days_left = (due_date - datetime.now()).days

    if datetime.now() > due_date:
        new_due_date = due_date + timedelta(days=2)
        loan['due_date'] = new_due_date.strftime("%Y-%m-%d")
        loan['loan_amount'] *= 2  # Увеличиваем основной долг в 2 раза
        save_loans()

        await ctx.send(
            f"⚠️ {ctx.author.mention}, у вас просроченный кредит! Долг удвоен. Новая дата погашения: {new_due_date.strftime('%Y-%m-%d')}."
        )
        return

    await ctx.send(
        f"💰 Кредит {ctx.author.mention}:\n"
        f"📌 **Сумма кредита:** {loan_amount} денег\n"
        f"📌 **Процентная ставка:** {interest_rate * 100}%\n"
        f"📌 **Итоговая сумма к погашению:** {total_debt} денег\n"
        f"📌 **Погашено:** {paid_amount} денег\n"
        f"📌 **Осталось погасить:** {remaining_amount} денег\n"
        f"📌 **Осталось дней до погашения:** {days_left} дней\n"
        f"📌 **Дата погашения:** {loan['due_date']}"
    )


# Функция для погашения кредита
@bot.command()
async def payloan(ctx, payment_amount: int):
    await ctx.message.delete()
    user_id = str(ctx.author.id)

    if user_id not in player_loans or not player_loans[user_id]:
        await ctx.send("У вас нет активного кредита.")
        return

    if user_id not in player_funds or player_funds[user_id] < payment_amount:
        await ctx.send("У вас недостаточно денег для оплаты кредита.")
        return

    loan = player_loans[user_id][0]
    paid_amount = loan.get('paid_amount', 0)
    remaining_balance = (loan['loan_amount'] * (1 + loan['interest_rate'])) - paid_amount

    if payment_amount > remaining_balance:
        payment_amount = remaining_balance  # Не позволяем переплатить

    # Вычитаем деньги у пользователя
    player_funds[user_id] -= payment_amount
    loan["paid_amount"] += payment_amount

    # Проверяем, погашен ли кредит
    if loan["paid_amount"] >= loan["loan_amount"] * (1 + loan["interest_rate"]):
        player_loans[user_id].remove(loan)
        await ctx.send(f"Вы полностью погасили кредит. Ваш новый баланс: {player_funds[user_id]} денег.")
    else:
        await ctx.send(
            f"Вы внесли {payment_amount} денег.\n"
            f"Осталось погасить: {remaining_balance - payment_amount} денег.\n"
            f"Ваш новый баланс: {player_funds[user_id]} денег."
        )

    save_funds()
    save_loans()



# Функция для обработки непогашенного кредита
@bot.command()
async def handleunpaidloan(ctx):
    await ctx.message.delete()
    user_id = str(ctx.author.id)

    if user_id not in player_loans or not player_loans[user_id]:
        await ctx.send("У вас нет активного кредита.")
        return

    loan = player_loans[user_id][0]
    loan_amount = loan['loan_amount']

    # Если не погашено вовремя, штрафуем
    if datetime.now() > datetime.strptime(loan['due_date'], "%Y-%m-%d"):
        # Если прошло 2 дополнительных дня
        if (datetime.now() - datetime.strptime(loan['due_date'], "%Y-%m-%d")).days > 2:
            player_funds[user_id]['balance'] -= loan_amount * 10
            player_loans[user_id].remove(loan)
            save_funds()
            save_loans()
            await ctx.send(f"Вы не погасили кредит вовремя. С вашего счета списано {loan_amount * 10}.")
        else:
            await ctx.send(
                f"У вас есть еще время для погашения кредита, долг сейчас в 2 раза больше. Дата погашения: {loan['due_date']}.")
    else:
        await ctx.send("Ваш кредит еще не просрочен.")


# Команда для получения информации о кредитах
@bot.command(name="moneyhelp")
async def moneyhelp(ctx):
    # Чтение содержимого файла
    try:
        with open("moneyhelp.txt", "r", encoding="utf-8") as file:
            help_text = file.read()
    except FileNotFoundError:
        help_text = "Файл с информацией не найден."

    # Отправка содержимого файла в чат
    await ctx.send(help_text)


tax_channel_id = 1351953330791776421   # Укажите свой канал ID


# Функция для списания налога
# async def apply_daily_tax():
#     # Получаем канал, в который будем отправлять сообщения
#     tax_channel = bot.get_channel(tax_channel_id)
#
#     if not tax_channel:
#         print("Канал для налога не найден.")
#         return
#
#     # Проходим по всем пользователям и списываем налог
#     for user_id, balance in player_funds.items():
#         # Если у пользователя меньше 37981 денег, налог 19%
#         if balance < 37981:
#             tax = int(balance * 0.19)
#         else:
#             # Если больше или равно 37981, налог 25%
#             tax = int(balance * 0.25)
#
#         # Списываем налог с баланса
#         player_funds[user_id] -= tax
#         save_funds()  # Сохраняем изменения
#     #
#     #     # Получаем пользователя по ID
#     #     user = await bot.fetch_user(user_id)
#     #
#     #     # Отправляем сообщение о списании налога в общий канал
#     #     await tax_channel.send(
#     #         f"{user.mention}, с вашего баланса был списан налог в размере {tax} денег. Ваш новый баланс: {player_funds[user_id]}.")
#     #
#     # print("Налоги были успешно списаны.")


# # Планируем задачу, которая будет запускаться каждый день в 20:00
# scheduler = AsyncIOScheduler()
# scheduler.add_job(apply_daily_tax,
#                   CronTrigger(hour=20, minute=0))  # Используем CronTrigger для ежедневного запуска в 20:00

# Убедитесь, что бот использует asyncio
loop = asyncio.get_event_loop()

@bot.command(name="money")
async def check_funds(ctx):
    await ctx.message.delete()
    await init_player_funds(ctx)
    await ctx.send(f"{ctx.author.mention}, у вас {player_funds[str(ctx.author.id)]} денег.")
# Запуск бота

@bot.command(name="userinfo")
async def user_info(ctx, member: nextcord.Member = None):
    await ctx.message.delete()
    if member is None:
        member = ctx.author

    embed = nextcord.Embed(title=f"Информация о пользователе {member}", color=nextcord.Color.blue())
    embed.add_field(name="Имя", value=member.name, inline=True)
    embed.add_field(name="ID", value=member.id, inline=True)
    embed.add_field(name="Дата присоединения", value=member.joined_at.strftime("%d/%m/%Y %H:%M"), inline=True)
    embed.add_field(name="Дата регистрации", value=member.created_at.strftime("%d/%m/%Y %H:%M"), inline=True)
    embed.add_field(name="Статус", value=member.status, inline=True)
    embed.set_thumbnail(url=member.avatar.url)

    await ctx.send(embed=embed)

# Команда для получения информации о сервере
@bot.command(name="serverinfo")
async def server_info(ctx):
    await ctx.message.delete()
    server = ctx.guild
    embed = nextcord.Embed(title=f"Информация о сервере {server.name}", color=nextcord.Color.green())
    embed.add_field(name="Название сервера", value=server.name, inline=True)
    embed.add_field(name="ID сервера", value=server.id, inline=True)
    embed.add_field(name="Создан", value=server.created_at.strftime("%d/%m/%Y %H:%M"), inline=True)
    embed.add_field(name="Количество участников", value=server.member_count, inline=True)
    embed.set_thumbnail(url=server.icon.url)

    await ctx.send(embed=embed)


class MyHelpCommand(commands.HelpCommand):
    async def send_bot_help(self, mapping):
        try:
            with open("help.txt", "r", encoding="utf-8") as file:
                help_text = file.read()
        except FileNotFoundError:
            help_text = "Файл помощи не найден. Обратитесь к администратору."

        ctx = self.context
        user = ctx.author  # получаем пользователя, вызвавшего команду

        # Удаляем сообщение с командой !help
        try:
            await ctx.message.delete()
        except nextcord.Forbidden:
            print("Нет прав на удаление сообщения.")
        except AttributeError:
            print("Сообщение не найдено (возможно, вызвано не через обычный текст).")

        # Отправляем помощь в ЛС
        try:
            await user.send(help_text)
        except nextcord.Forbidden:
            await ctx.send(
                f"{user.mention}, я не могу отправить тебе сообщение в ЛС. Разреши их в настройках приватности.")



@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    # Запуск задачи при запуске бота
    send_loan_warnings.start()
    # scheduler.start()

@bot.event
async def on_member_join(member):
    print(f"[JOIN] {member.name} присоединился!")
    try:
        # Чтение файла help.txt
        try:
            with open("help.txt", "r", encoding="utf-8") as file:
                help_text = file.read()
        except FileNotFoundError:
            help_text = "Файл помощи не найден. Обратитесь к администратору."

        # Отправка приветствия + help в ЛС
        await member.send(f"Привет от бота BAZARCIK_PM, {member.name}! Добро пожаловать на сервер BAZARCIK_PM!\n\n{help_text}")

    except nextcord.Forbidden:
        print(f'Не удалось отправить ЛС пользователю {member.name}.')


# channel: category

fortune_members = [
    "Игрок NIKUSA",
    "Игрок REOSTISLAV",
    "Игрок TANCHIK",
    "Игрок STROLEKOFK"
]

@bot.command(name="random")
async def fortune(ctx):
    await ctx.message.delete()
    winner = random.choice(fortune_members)
    await ctx.send(f"🎉 Сегодня удача не на стороне: **{winner}**!")

AUTO_CHANNELS = {
    1402746822191218749: 1402733375986466816,
    1402746847713296526: 1402732822375960676,
    1402746870773584062: 1402732572206960661,
    1472756792491643031: 1402748456883454097
}

@bot.event
async def on_voice_state_update(member, before, after):
    # === СОЗДАНИЕ КАНАЛА ===
    if after.channel and after.channel.id in AUTO_CHANNELS:
        guild = member.guild
        auto_channel = after.channel
        category_id = AUTO_CHANNELS[auto_channel.id]
        category = guild.get_channel(category_id)

        # print(f"[INFO] {member} зашёл в автоканал {auto_channel.name}")

        new_name = auto_channel.name.replace("Create", "")

        prefix = "_ZP" if new_name == "🔊 Poslucháreň" else " "

        # Поиск занятых номеров
        existing_numbers = set()
        for channel in category.voice_channels:
            if channel.name.startswith(new_name + prefix):
                try:
                    num = int(channel.name.replace(new_name + prefix, "").strip())
                    existing_numbers.add(num)
                except ValueError:
                    continue

        # Поиск свободной цифры
        new_number = 1
        while new_number in existing_numbers:
            new_number += 1

        new_channel_name = f"{new_name}{prefix}{new_number}"

        # print(f"[CREATE] Создаётся канал: {new_channel_name}")

        # Права
        overwrites = {
            guild.default_role: nextcord.PermissionOverwrite(connect=True),
            member: nextcord.PermissionOverwrite(connect=True, manage_channels=True),
        }

        # Создание канала
        # Создание канала
        new_channel = await guild.create_voice_channel(
            name=new_channel_name,
            category=category
        )

        # Синхронизация прав с категорией
        await new_channel.edit(sync_permissions=True)

        await member.move_to(new_channel)

        # print(f"[MOVE] {member} перемещён в {new_channel.name}")

    # === УДАЛЕНИЕ ПУСТОГО КАНАЛА ===
    if before.channel:
        if before.channel.id in AUTO_CHANNELS:
            return

        if before.channel.category_id not in AUTO_CHANNELS.values():
            return

        # Универсальная проверка: имя заканчивается на цифру
        if not re.search(r"\d+$", before.channel.name):
            return

        # print(f"[CHECK] {member} покинул {before.channel.name}, проверка на пустоту через 5 секунд...")
        await asyncio.sleep(5)

        if len(before.channel.members) == 0:
            try:
                await before.channel.delete()
                # print(f"[DELETE] Удалён пустой канал: {before.channel.name}")
            except Exception as e:
                print(f"[ERROR] Не удалось удалить канал {before.channel.name}: {e}")


import json
import nextcord
from nextcord.ext import commands

@bot.command()
async def petition(ctx, *, text=None):
    await ctx.message.delete()
    if text is None:
        await ctx.send(
            "❗ Неверное использование команды!\n"
            "Правильно: `!petition <текст петиции>`\n"
            "Пример: `!petition Добавить новые смайлики на сервер`",
            delete_after=15
        )
        return

    try:
        with open("petitions.json", "r", encoding="utf-8") as f:
            petitions = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        petitions = []

    petition_id = len(petitions) + 1
    required_votes = max(1, int(ctx.guild.member_count * 0.1)) - 1

    petition_data = {
        "id": petition_id,
        "author": ctx.author.id,
        "text": text,
        "votes": 0,
        "voters": [],
        "status": "active",
        "reviewed_by": None,
        "message_id": None,
        "required_votes": required_votes,
        "admin_votes": [],          # новые поля
        "admin_results": {}         # id -> yes/no
    }

    petitions.append(petition_data)

    with open("petitions.json", "w", encoding="utf-8") as f:
        json.dump(petitions, f, indent=4)

    sent_message = await ctx.send(
        f"**Петиция №{petition_id}**\n{text}\n\n"
        f"Автор: <@{ctx.author.id}>\n"
        f"Подписей: 0/{required_votes}\n"
        f"👮 Голоса админов: 0/3\n\n"
        f"📢 Подпиши петицию командой: `!vote {petition_id}`"
    )

    petition_data["message_id"] = sent_message.id
    with open("petitions.json", "w", encoding="utf-8") as f:
        json.dump(petitions, f, indent=4)


@bot.command()
async def vote(ctx, petition_id: int = None):
    await ctx.message.delete()

    if petition_id is None:
        await ctx.send("❗ Укажи номер петиции. Пример: `!vote 1`", delete_after=10)
        return

    try:
        with open("petitions.json", "r", encoding="utf-8") as f:
            petitions = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        await ctx.send("❗ Петиции не найдены.", delete_after=10)
        return

    petition = next((p for p in petitions if p["id"] == petition_id), None)

    if not petition:
        await ctx.send("❗ Петиция с таким номером не найдена.", delete_after=10)
        return

    if petition["status"] != "active":
        await ctx.send("❌ Эта петиция уже закрыта и подписать её нельзя.", delete_after=10)
        return

    if str(ctx.author.id) in petition["voters"]:
        await ctx.send("🔁 Ты уже подписал эту петицию.", delete_after=10)
        return

    petition["votes"] += 1
    petition["voters"].append(str(ctx.author.id))

    with open("petitions.json", "w", encoding="utf-8") as f:
        json.dump(petitions, f, indent=4)

    # Создание текста обновлённой петиции
    content = (
        f"**Петиция №{petition['id']}**\n"
        f"{petition['text']}\n\n"
        f"Автор: <@{petition['author']}>\n"
        f"Подписей: {petition['votes']}/{petition['required_votes']}"
    )

    # Добавим поле для голосов админов
    admin_votes = petition.get("admin_votes", {})
    content += f"\n👮 Голоса админов: {len(admin_votes)}/3"

    if petition["votes"] >= petition["required_votes"]:
        content += (
            "\n\n🔔 Петиция достигла необходимого количества голосов и ожидает решения от администраторов."
            f"\nАдминистраторы могут использовать команды: `!yes {petition['id']}` или `!no {petition['id']}`"
        )
    else:
        content += f"\n\n📢 Подпиши петицию командой: `!vote {petition['id']}`"

    try:
        channel = ctx.channel
        message = await channel.fetch_message(petition["message_id"])
        await message.edit(content=content)
    except Exception as e:
        print(f"[Ошибка обновления петиции #{petition_id}] {e}")

    await ctx.send("✅ Ты подписал петицию.", delete_after=5)


@bot.command()
async def yes(ctx, petition_id: int):
    await handle_admin_vote(ctx, petition_id, vote_type="yes")

@bot.command()
async def no(ctx, petition_id: int):
    await handle_admin_vote(ctx, petition_id, vote_type="no")


async def handle_admin_vote(ctx, petition_id: int, vote_type: str):
    await ctx.message.delete()
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("Только администратор может использовать эту команду.", delete_after=10)
        return

    try:
        with open("petitions.json", "r", encoding="utf-8") as f:
            petitions = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        await ctx.send("Нет активных петиций.", delete_after=10)
        return

    for petition in petitions:
        if petition["id"] == petition_id:
            if petition["status"] != "active":
                await ctx.send("Эта петиция уже была рассмотрена.", delete_after=15)
                return

            if petition["votes"] < petition["required_votes"]:
                await ctx.send(
                    f"Петиция ещё не набрала необходимое количество голосов.\n"
                    f"Текущие голоса: {petition['votes']}/{petition['required_votes']}",
                    delete_after=15
                )
                return

            if "reviews" not in petition:
                petition["reviews"] = {"yes": [], "no": []}

            if ctx.author.id in petition["reviews"]["yes"] or ctx.author.id in petition["reviews"]["no"]:
                await ctx.send("Вы уже проголосовали за эту петицию.", delete_after=10)
                return

            petition["reviews"][vote_type].append(ctx.author.id)

            total_votes = len(petition["reviews"]["yes"]) + len(petition["reviews"]["no"])
            result_text = None

            if total_votes >= 3:
                if len(petition["reviews"]["yes"]) > len(petition["reviews"]["no"]):
                    petition["status"] = "approved"
                    result_text = "✅ Одобрена"
                else:
                    petition["status"] = "rejected"
                    result_text = "❌ Отклонена"

            # Обновим файл
            with open("petitions.json", "w", encoding="utf-8") as f:
                json.dump(petitions, f, indent=4)

            # Обновим сообщение с петицией
            try:
                channel = ctx.channel
                message = await channel.fetch_message(petition["message_id"])

                content = (
                    f"**Петиция №{petition['id']}**\n"
                    f"{petition['text']}\n\n"
                    f"Автор: <@{petition['author']}>\n"
                    f"Подписей: {petition['votes']}/{petition['required_votes']}"
                )

                content += f"\n👮 Голоса админов: {total_votes}/3"

                if petition["status"] == "active":
                    content += (
                        "\n\n🔔 Петиция достигла необходимого количества голосов и ожидает решения от администраторов."
                        f"\nАдминистраторы могут использовать команды: `!yes {petition['id']}` или `!no {petition['id']}`"
                    )
                else:
                    content += f"\n\n{result_text} большинством голосов администраторов"

                await message.edit(content=content)

            except Exception as e:
                print(f"[Ошибка обновления сообщения петиции #{petition_id}] {e}")

            if petition["status"] == "active":
                await ctx.send(f"Ваш голос засчитан. Сейчас проголосовало {total_votes}/3 админов.", delete_after=10)
            return

    await ctx.send("Петиция не найдена.", delete_after=10)


YOUR_USER_ID = 539475816342487040  # Замінити на свій Discord User ID

AUDIO_FILE = "greeting.mp3"

intents = discord.Intents.default()
intents.voice_states = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

def generate_greeting():
    """Генеруємо аудіо привітання якщо файл не існує"""
    if not os.path.exists(AUDIO_FILE):
        tts = gTTS("Привіт Юра Яковенко", lang="uk")
        tts.save(AUDIO_FILE)
        print(f"Аудіо файл '{AUDIO_FILE}' створено.")

@bot.event
async def on_ready():
    print(f"Бот запущений як {bot.user}")
    generate_greeting()

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    # Тільки коли саме ти заходиш у канал
    if member.id != YOUR_USER_ID:
        return
    if after.channel is None or before.channel == after.channel:
        return

    channel = after.channel
    greeted = False

    try:
        # Бот заходить у той самий канал
        vc = await channel.connect()

        # Відтворюємо привітання
        audio_source = discord.FFmpegPCMAudio(AUDIO_FILE)
        vc.play(audio_source)

        # Чекаємо поки програє
        while vc.is_playing():
            await asyncio.sleep(0.5)

        greeted = True
        await vc.disconnect()

    except Exception as e:
        print(f"Помилка при відтворенні: {e}")
        if vc and vc.is_connected():
            await vc.disconnect()

    if not greeted:
        # Якщо не привіталось — кікаємо всіх крім тебе
        print("Не вдалось привітати — кікаємо всіх!")
        for m in list(channel.members):
            if m.id != YOUR_USER_ID:
                try:
                    await m.move_to(None)
                    print(f"Кікнув {m.name}")
                except Exception as e:
                    print(f"Не вдалось кікнути {m.name}: {e}")


# Устанавливаем кастомную команду help
bot.help_command = MyHelpCommand()
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
bot.run(TOKEN)