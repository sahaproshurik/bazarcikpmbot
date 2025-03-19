import nextcord
from discord.ext import commands, tasks
import random
from nextcord.ext import commands
from nextcord.ui import View, Button  # Добавляем импорт View и Button
import asyncio
from collections import Counter
import json
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

# Устанавливаем intents
intents = nextcord.Intents.default()
intents.message_content = True  # Включаем возможность читать контент сообщений

bot = commands.Bot(command_prefix="!", intents=intents)

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
    mute_role = nextcord.utils.get(ctx.guild.roles, name="Muted")
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
        return tax
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
            await ctx.send(f"Налог с выигрыша ({tax}): {tax} денег.")
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
            await ctx.send(f"Налог с выигрыша ({tax}): {tax} денег.")
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
            await ctx.send(f"Налог с выигрыша ({tax}): {tax} денег.")
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
            await ctx.send(f"Налог с выигрыша ({tax}): {tax} денег.")
        await ctx.send(f"{ctx.author.mention} выиграл! Все символы совпали! Выигрыш: {winnings} денег. У вас теперь {player_funds[str(ctx.author.id)]} денег.")
    elif len(set(spin_result)) == 2:  # Два одинаковых символа
        winnings = bet * 2
        player_funds[str(ctx.author.id)] += winnings
        save_funds()
        tax = calculate_tax(winnings - bet)  # Чистая прибыль - ставка
        if tax > 0:
            player_funds[str(ctx.author.id)] -= tax
            save_funds()
            await ctx.send(f"Налог с выигрыша ({tax}): {tax} денег.")
        await ctx.send(f"{ctx.author.mention} выиграл! Два символа совпали! Выигрыш: {winnings} денег. У вас теперь {player_funds[str(ctx.author.id)]} денег.")
    else:
        await ctx.send(f"{ctx.author.mention} проиграл. У вас теперь {player_funds[str(ctx.author.id)]} денег.")



AVAILABLE_JOBS = ["пикинг"]
UNAVAILABLE_JOBS = ["баление", "бафер", "боксы", "вратки"]

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

PRIEMER_FILE = "priemer_data.json"

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
    while True:
        await asyncio.sleep(3600)
        for user_id in priemer_data:
            orders = order_history.get(user_id, [])
            if orders:
                avg_orders_per_hour = len(orders)
                avg_positions_per_order = sum(orders) / avg_orders_per_hour
                increase = (avg_orders_per_hour * avg_positions_per_order) / 10
                priemer_data[user_id] = min(150, priemer_data[user_id] + increase)
            else:
                priemer_data[user_id] = max(0, priemer_data[user_id] - 1)
        save_priemer()
        order_history.clear()

loop = asyncio.get_event_loop()
loop.create_task(update_priemer())

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

        if random.random() < 0.05:
            self.pick_button.disabled = True
            self.disabled = True
            for remaining in range(60, 0, -1):
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
async def start_job(ctx, job: str):
    await ctx.message.delete()
    job = job.lower()
    if job in UNAVAILABLE_JOBS:
        await ctx.send(f"{ctx.author.mention}, мест уже нет!")
        return

    if job not in AVAILABLE_JOBS:
        await ctx.send(f"{ctx.author.mention}, такой работы не существует!")
        return

    user_id = str(ctx.author.id)
    ORDERS[user_id] = generate_order()
    priemer_data[user_id] = priemer_data.get(user_id, 0)  # Начальное значение priemer
    save_priemer()

    pickup_list = "\n".join([f"{i+1}. {order['location']} ({order['item']})" for i, order in enumerate(ORDERS[user_id])])

    view = PickingView(user_id)
    message = await ctx.send(
        f"{ctx.author.mention}, вы начали работу на пикинге. Вам выдан заказ из {len(ORDERS[user_id])} позиций. Ваш priemer: {priemer_data[user_id]}\n\n**Пикап лист:**\n{pickup_list}",
        view=view
    )
    ORDER_MESSAGES[user_id] = message.id # Сохраняем ID сообщения  # Сохраняем ID сообщения  # Сохраняем ID сообщения
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
LOANS_FILE = "player_loans.json"


# Функция для расчета возраста пользователя на сервере
def get_user_age_on_server(user_id):
    join_date = player_funds.get(user_id, {}).get('join_date')
    if join_date:
        join_date = datetime.strptime(join_date, "%Y-%m-%d")
        age_on_server = (datetime.now() - join_date).days
        return age_on_server
    return 0


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
    return daily_payment


# Функция для получения процентной ставки
def get_interest_rate(age_on_server):
    if age_on_server > 120:
        return 0.15
    return 0.20


# Функция для оформления кредита
@bot.command()
async def applyloan(ctx, loan_amount: int, loan_term: int):
    user_id = str(ctx.author.id)

    # Проверка, что срок кредита не превышает 7 дней
    if loan_term > 7:
        await ctx.send("Максимальный срок кредита — 7 дней.")
        return

    age_on_server = get_user_age_on_server(user_id)
    max_loan = get_max_loan_amount(age_on_server)

    if loan_amount > max_loan:
        await ctx.send(f"Вы можете взять кредит не более {max_loan}.")
        return

    interest_rate = get_interest_rate(age_on_server)
    daily_payment = calculate_daily_payment(loan_amount, loan_term, interest_rate)

    if user_id not in player_funds:
        player_funds[user_id] = {}

    # Сохраняем информацию о кредите в словарь
    if user_id not in player_loans:
        player_loans[user_id] = []

    due_date = (datetime.now() + timedelta(days=loan_term)).strftime("%Y-%m-%d")
    player_loans[user_id].append({
        "loan_amount": loan_amount,
        "interest_rate": interest_rate,
        "daily_payment": daily_payment,
        "loan_term": loan_term,
        "due_date": due_date,
        "taken_by": ctx.author.name
    })

    save_funds()
    save_loans()

    await ctx.send(
        f"Вы взяли кредит на сумму {loan_amount}. Ежедневный платеж: {daily_payment:.2f}. Дата погашения: {due_date}. Кредит оформил: {ctx.author.name}.")


# Функция для расчета кредита
@bot.command()
async def calculatecredit(ctx, loan_amount: int, loan_term: int):
    age_on_server = get_user_age_on_server(str(ctx.author.id))
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


# Запускаем задачу для отправки предупреждений
send_loan_warnings.start()


# Функция для проверки и обновления погашения кредита
@bot.command()
async def checkloan(ctx):
    user_id = str(ctx.author.id)

    if user_id not in player_loans or not player_loans[user_id]:
        await ctx.send("У вас нет активного кредита.")
        return

    for loan in player_loans[user_id]:
        due_date = datetime.strptime(loan['due_date'], "%Y-%m-%d")

        if datetime.now() > due_date:
            # Просрочка, даем 2 дополнительных дня
            new_due_date = due_date + timedelta(days=2)
            loan['due_date'] = new_due_date.strftime("%Y-%m-%d")
            loan['loan_amount'] *= 2  # Увеличиваем долг в 2 раза
            save_loans()
            await ctx.send(
                f"Просрочка! Вам дано еще 2 дня для погашения. Долг увеличен в 2 раза. Новая дата погашения: {new_due_date.strftime('%Y-%m-%d')}.")
            return

    await ctx.send(f"Ваш кредит еще не просрочен. Дата погашения: {loan['due_date']}.")


# Функция для погашения кредита
@bot.command()
async def payloan(ctx, payment_amount: float):
    user_id = str(ctx.author.id)

    if user_id not in player_loans or not player_loans[user_id]:
        await ctx.send("У вас нет активного кредита.")
        return

    loan = player_loans[user_id][0]
    remaining_balance = loan['loan_amount'] * (1 + loan['interest_rate']) - payment_amount

    if remaining_balance <= 0:
        # Погашение кредита
        player_loans[user_id].remove(loan)
        save_loans()
        await ctx.send(f"Ваш кредит погашен успешно. Баланс: {player_funds[user_id].get('balance', 0)}.")
    else:
        await ctx.send(f"Остаток по кредиту: {remaining_balance:.2f}.")


# Функция для обработки непогашенного кредита
@bot.command()
async def handleunpaidloan(ctx):
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


tax_channel_id = 1350964493055955077   # Укажите свой канал ID


# Функция для списания налога
async def apply_daily_tax():
    # Получаем канал, в который будем отправлять сообщения
    tax_channel = bot.get_channel(tax_channel_id)

    if not tax_channel:
        print("Канал для налога не найден.")
        return

    # Проходим по всем пользователям и списываем налог
    for user_id, balance in player_funds.items():
        # Если у пользователя меньше 37981 денег, налог 19%
        if balance < 37981:
            tax = balance * 0.19
        else:
            # Если больше или равно 37981, налог 25%
            tax = balance * 0.25

        # Списываем налог с баланса
        player_funds[user_id] -= tax
        save_funds()  # Сохраняем изменения

        # Получаем пользователя по ID
        user = await bot.fetch_user(user_id)

        # Отправляем сообщение о списании налога в общий канал
        await tax_channel.send(
            f"{user.mention}, с вашего баланса был списан налог в размере {tax:.2f} денег. Ваш новый баланс: {player_funds[user_id]:.2f}.")

    print("Налоги были успешно списаны.")


# Планируем задачу, которая будет запускаться каждый день в 20:00
scheduler = AsyncIOScheduler()
scheduler.add_job(apply_daily_tax,
                  CronTrigger(hour=20, minute=0))  # Используем CronTrigger для ежедневного запуска в 20:00
scheduler.start()

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
        
        # Отправка помощи в канал
        await self.get_destination().send(help_text)


# Устанавливаем кастомную команду help
bot.help_command = MyHelpCommand()
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
bot.run(TOKEN)
