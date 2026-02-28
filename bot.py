import os
import json
import random
import asyncio
import time
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
import pytz

import nextcord
from nextcord.ext import commands, tasks
from nextcord.ui import View, Button
from dotenv import load_dotenv

# Устанавливаем intents
intents = nextcord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
intents.guilds = True

bot = commands.Bot(command_prefix="!", intents=intents, case_insensitive=True)

# Файлы данных
FUNDS_FILE = "player_funds.json"
BUSINESS_FILE = "player_businesses.json"
ORDERS_COMPLETED_FILE = "orders_completed.json"
PRIEMER_FILE = "priemer_data.json"
LOANS_FILE = "player_loans.json"

# Базовые функции загрузки и сохранения
def load_data(file_path, default_data=None):
    if default_data is None:
        default_data = {}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default_data

def save_data(file_path, data):
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def load_text_lines(filename):
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            return file.read().splitlines()
    except FileNotFoundError:
        return []

# Загрузка данных
jokes = load_text_lines('jokes.txt')
predictions = load_text_lines('predictions.txt')
player_funds = load_data(FUNDS_FILE)
USER_ORDERS_COMPLETED = load_data(ORDERS_COMPLETED_FILE)
priemer_data = load_data(PRIEMER_FILE)
player_loans = load_data(LOANS_FILE)

def save_funds():
    save_data(FUNDS_FILE, player_funds)

def save_loans():
    save_data(LOANS_FILE, player_loans)

def save_priemer():
    save_data(PRIEMER_FILE, priemer_data)

# Карты и масти
card_values = {
    '2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10,
    'J': 10, 'Q': 10, 'K': 10, 'A': 11
}

suits = {
    'hearts': '♥',
    'diamonds': '♦',
    'clubs': '♣',
    'spades': '♠'
}

# --- КОМАНДЫ ДЛЯ ТЕКСТА И МОДЕРАЦИИ ---

@bot.command(name="joke", aliases=["randomjoke", "jokes"])
async def tell_joke(ctx):
    await ctx.message.delete()
    if not jokes:
        await ctx.send("Шутки пока не загружены!")
        return
    joke = random.choice(jokes)
    await ctx.send(f"{ctx.author.mention} {joke}")

@bot.command(name="predict", aliases=["fortune_prophecy"])
async def tell_prediction(ctx):
    await ctx.message.delete()
    if not predictions:
        await ctx.send("Предсказания пока не загружены!")
        return
    prediction = random.choice(predictions)
    await ctx.send(f"{ctx.author.mention} {prediction}")

@bot.command(name="greet")
async def greet_user(ctx, member: nextcord.Member):
    await ctx.message.delete()
    await ctx.send(f"Привет {member.mention} от бота базарчик пм")

@bot.command(name="mute")
@commands.has_permissions(administrator=True)
async def mute(ctx, member: nextcord.Member, mute_time: int):
    await ctx.message.delete()
    await ctx.send(f"{member.mention}, у тебя есть 1 минута на размышление перед тем, как я наложу мут на {mute_time} минут.")
    await asyncio.sleep(60)

    mute_role = nextcord.utils.get(ctx.guild.roles, name="БАН банан🍌")
    if not mute_role:
        mute_role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.text_channels:
            await channel.set_permissions(mute_role, speak=False, send_messages=False)

    await member.add_roles(mute_role)
    await ctx.send(f"{member.mention} был замучен на {mute_time} минут.")
    
    await asyncio.sleep(mute_time * 60)
    await member.remove_roles(mute_role)
    await ctx.send(f"{member.mention} мут был снят.")

@bot.command(name="ban")
@commands.has_permissions(administrator=True)
async def ban_user(ctx, member: nextcord.Member, ban_time: int):
    await ctx.message.delete()
    await ctx.send(f"{member.mention}, у тебя есть 1 минута на размышление перед тем, как я забаню тебя на {ban_time} дней.")
    await asyncio.sleep(60)
    
    await member.ban(reason="Бан на время", delete_message_days=7)
    await ctx.send(f"{member.mention} был забанен на {ban_time} дней.")
    
    await asyncio.sleep(ban_time * 86400)
    await ctx.guild.unban(member)
    await ctx.send(f"{member.mention} разбанен.")

@bot.command(name="clear")
@commands.has_permissions(administrator=True)
async def clear(ctx, amount: int):
    await ctx.message.delete()
    if amount <= 0 or amount > 100:
        await ctx.send("Количество сообщений должно быть больше 0 и меньше 100.")
        return
    deleted = await ctx.channel.purge(limit=amount)
    await ctx.send(f"Удалено {len(deleted)} сообщений.", delete_after=5)

@bot.command(name="clearday")
@commands.has_permissions(administrator=True)
async def clearday(ctx, days: int):
    await ctx.message.delete()
    if days <= 0:
        await ctx.send("Количество дней должно быть больше 0.")
        return
    
    time_limit = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = await ctx.channel.purge(after=time_limit)
    await ctx.send(f"Удалено {len(deleted)} сообщений за последние {days} дней.", delete_after=5)    

@bot.command(name="clearuser")
@commands.has_permissions(administrator=True)
async def clearuser(ctx, member: nextcord.Member, amount: int):
    await ctx.message.delete()
    if amount <= 0:
        await ctx.send("Количество сообщений должно быть больше 0.")
        return
    
    deleted = await ctx.channel.purge(limit=amount, check=lambda message: message.author == member)
    await ctx.send(f"Удалено {len(deleted)} сообщений от {member.mention}.", delete_after=5)

@bot.command(name="clearuserday")
@commands.has_permissions(administrator=True)
async def clearuserdays(ctx, member: nextcord.Member, days: int):
    await ctx.message.delete()
    if days <= 0:
        await ctx.send("Количество дней должно быть больше 0.")
        return
    
    time_limit = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0
    async for message in ctx.channel.history(limit=200):
        if message.author == member and message.created_at >= time_limit:
            await message.delete()
            deleted += 1
    
    await ctx.send(f"Удалено {deleted} сообщений от {member.mention} за последние {days} дней.", delete_after=5)

@bot.command(name="pick")
async def pick_user(ctx, member: nextcord.Member):
    await ctx.message.delete()
    await ctx.send(f"{member.mention} а ну быстро зашол ато банчик")

@bot.command(name="z")
async def z_user(ctx, member: nextcord.Member):
    await ctx.message.delete()
    await ctx.send(f"{member.mention}! Слухай уважно! Настав час остаточно та безповоротно відмовитися від усього, що пахне московією...")


# --- ИГРЫ И ЭКОНОМИКА ---

def create_deck():
    deck = [(card, suit) for suit in suits for card in card_values]
    random.shuffle(deck)
    return deck

def calculate_hand(hand):
    total = sum(card_values[card] for card, _ in hand)
    aces = sum(1 for card, _ in hand if card == 'A')
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total

async def init_player_funds(ctx):
    if str(ctx.author.id) not in player_funds:
        player_funds[str(ctx.author.id)] = 1000
        save_funds()

def calculate_tax(profit):
    if profit > 20000:
        return int(profit * 0.18)
    return 0

@bot.command(name="bj")
async def blackjack(ctx, bet: int):
    await ctx.message.delete()
    await init_player_funds(ctx)
    user_id = str(ctx.author.id)

    if bet <= 0:
        await ctx.send("Ставка должна быть положительным числом.")
        return
    if bet > player_funds.get(user_id, 0):
        await ctx.send("У вас недостаточно денег для этой ставки.")
        return

    player_funds[user_id] -= bet
    save_funds()
    deck = create_deck()
    player_hand = [deck.pop(), deck.pop()]
    dealer_hand = [deck.pop(), deck.pop()]

    await ctx.send(f"{ctx.author.mention} начал игру в Блэкджек. Ставка: {bet}")
    await ctx.send(f"Ваши карты: {', '.join([f'{c[0]}{suits[c[1]]}' for c in player_hand])} (Сумма: {calculate_hand(player_hand)})")
    await ctx.send(f"Карты дилера: {dealer_hand[0][0]}{suits[dealer_hand[0][1]]} и скрытая карта.")

    if calculate_hand(player_hand) == 21:
        winnings = bet * 3
        player_funds[user_id] += winnings
        tax = calculate_tax(winnings - bet)
        if tax > 0:
            player_funds[user_id] -= tax
            await ctx.send(f"Налог с выигрыша: {tax} денег.")
        save_funds()
        await ctx.send(f"Поздравляем, у {ctx.author.mention} Блэкджек! Вы выиграли {winnings} денег! Теперь у вас {player_funds[user_id]} денег.")
        return

    while calculate_hand(player_hand) < 21:
        await ctx.send("Хотите взять еще карту? Введите !hit для добора или !stand для завершения.")

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and m.content.lower() in ['!hit', '!stand']

        try:
            msg = await bot.wait_for('message', check=check, timeout=60.0)
            await msg.delete()
            if msg.content.lower() == '!hit':
                player_hand.append(deck.pop())
                await ctx.send(f"Вы взяли {player_hand[-1][0]}{suits[player_hand[-1][1]]}. (Сумма: {calculate_hand(player_hand)})")
                if calculate_hand(player_hand) > 21:
                    await ctx.send(f"{ctx.author.mention} проиграл! Вы превысили 21!")
                    return
            elif msg.content.lower() == '!stand':
                break
        except asyncio.TimeoutError:
            await ctx.send(f"{ctx.author.mention}, время вышло! Игра завершена (stand).")
            break

    while calculate_hand(dealer_hand) < 17:
        dealer_hand.append(deck.pop())

    await ctx.send(f"Карты дилера: {', '.join([f'{c[0]}{suits[c[1]]}' for c in dealer_hand])}. (Сумма: {calculate_hand(dealer_hand)})")

    player_total = calculate_hand(player_hand)
    dealer_total = calculate_hand(dealer_hand)

    if player_total > 21:
        await ctx.send("Вы проиграли, так как превысили 21!")
    elif dealer_total > 21 or player_total > dealer_total:
        winnings = bet * 2
        player_funds[user_id] += winnings
        tax = calculate_tax(winnings - bet)
        if tax > 0:
            player_funds[user_id] -= tax
            await ctx.send(f"Налог с выигрыша: {tax} денег.")
        save_funds()
        await ctx.send(f"{ctx.author.mention} выиграл! Ваш выигрыш: {winnings} денег. Теперь у вас {player_funds[user_id]} денег.")
    elif player_total < dealer_total:
        await ctx.send(f"{ctx.author.mention} проиграл! Теперь у вас {player_funds[user_id]} денег.")
    else:
        player_funds[user_id] += bet
        save_funds()
        await ctx.send(f"Ничья {ctx.author.mention}! Ваша ставка возвращена. У вас {player_funds[user_id]} денег.")


@bot.command()
async def flip(ctx, bet: int, choice: str):
    await ctx.message.delete()
    await init_player_funds(ctx)
    user_id = str(ctx.author.id)

    if bet > player_funds.get(user_id, 0):
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
    player_funds[user_id] -= bet
    
    result = random.choice(["о", "р"])
    result_str = "Орел" if result == "о" else "Решка"

    if result_str == choice_result:
        winnings = bet * 2
        player_funds[user_id] += winnings
        tax = calculate_tax(winnings - bet)
        if tax > 0:
            player_funds[user_id] -= tax
            await ctx.send(f"Налог с выигрыша: {tax} денег.")
        save_funds()
        await ctx.send(f"{ctx.author.mention} выиграл! Выпал {result_str}. Выигрыш: {winnings} денег. У вас {player_funds[user_id]} денег.")
    else:
        save_funds()
        await ctx.send(f"{ctx.author.mention} проиграл. Выпал {result_str}. У вас {player_funds[user_id]} денег.")


@bot.command()
async def spin(ctx, bet: int):
    await ctx.message.delete()
    await init_player_funds(ctx)
    user_id = str(ctx.author.id)

    if bet > player_funds.get(user_id, 0) or bet <= 0:
        await ctx.send("Некорректная ставка или недостаточно денег.")
        return

    player_funds[user_id] -= bet
    symbols = ["🍒", "🍋", "🍉", "🍇", "🍊", "🍍"]
    spin_result = [random.choice(symbols) for _ in range(3)]

    await ctx.send(f"{ctx.author.mention} крутит слоты... | Результат: {' | '.join(spin_result)}")

    unique_symbols = len(set(spin_result))
    if unique_symbols == 1:
        winnings = bet * 5
        msg = "Все символы совпали!"
    elif unique_symbols == 2:
        winnings = bet * 2
        msg = "Два символа совпали!"
    else:
        winnings = 0
        msg = "Проигрыш."

    if winnings > 0:
        player_funds[user_id] += winnings
        tax = calculate_tax(winnings - bet)
        if tax > 0:
            player_funds[user_id] -= tax
            await ctx.send(f"Налог: {tax} денег.")
        await ctx.send(f"{ctx.author.mention} выиграл! {msg} Выигрыш: {winnings} денег. Баланс: {player_funds[user_id]}.")
    else:
        await ctx.send(f"{ctx.author.mention} {msg} У вас теперь {player_funds[user_id]} денег.")
    
    save_funds()


# --- РАБОТЫ (Пикинг и Баление) ---

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

ORDERS = {}
ORDER_MESSAGES = {}
order_history = {}

def generate_order():
    num_positions = random.randint(1, 30)
    positions = []
    for _ in range(num_positions):
        brand = random.choice(list(SPORT_ITEMS_WITH_BRANDS.keys()))
        item = random.choice(SPORT_ITEMS_WITH_BRANDS[brand])
        location = f"3{random.choice('BC')}{random.randint(1, 56)}{random.choice('ABCDEFGHJ')}{random.randint(1, 4)}"
        positions.append({"location": location, "item": f"{brand} - {item}", "status": "не выполнено"})
    return positions

@tasks.loop(minutes=1)
async def update_priemer():
    for user_id in priemer_data:
        orders = order_history.get(user_id, [])
        if orders:
            avg_orders_per_min = len(orders)
            avg_positions_per_order = sum(orders) / avg_orders_per_min
            increase = (avg_orders_per_min * avg_positions_per_order) / 10
            priemer_data[user_id] = int(min(150, priemer_data[user_id] + increase))
        else:
            priemer_data[user_id] = int(max(0, priemer_data[user_id] - 1))
    save_priemer()
    order_history.clear()

@bot.command()
async def priemer(ctx):
    await ctx.message.delete()
    user_id = str(ctx.author.id)
    if user_id in priemer_data:
        await ctx.send(f"Priemer {ctx.author.mention}: {priemer_data[user_id]}")
    else:
        await ctx.send("Вы еще не начали работать!")

class PackingView(View):
    def __init__(self, user_id: str, order_size: int):
        super().__init__()
        self.user_id = user_id
        self.order_size = order_size
        self.remaining_items = order_size
        self.selected_box = None

        self.exit_button = Button(label="Выйти с работы", style=nextcord.ButtonStyle.red, disabled=True)
        self.exit_button.callback = self.exit_job

        box_sizes = {"A": range(1, 7), "B": range(7, 13), "C": range(13, 19), "D": range(19, 25), "E": range(25, 31)}

        for box in box_sizes.keys():
            btn = Button(label=f"Коробка {box}", style=nextcord.ButtonStyle.blurple)
            btn.callback = self.create_box_callback(box, box_sizes[box])
            self.add_item(btn)

        self.collect_button = Button(label="Собрать товар", style=nextcord.ButtonStyle.green, disabled=True)
        self.collect_button.callback = self.collect_item
        self.add_item(self.collect_button)
        self.add_item(self.exit_button)

    def create_box_callback(self, box: str, size_range):
        async def callback(interaction: nextcord.Interaction):
            if str(interaction.user.id) != self.user_id:
                await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
                return
            if self.order_size not in size_range:
                await interaction.response.send_message(f"Эта коробка не подходит!", ephemeral=True)
                return
            
            self.selected_box = box
            self.collect_button.disabled = False
            await interaction.message.edit(content=f"{interaction.user.mention}, выбрана коробка {box}. Осталось: {self.remaining_items}.", view=self)
        return callback

    async def collect_item(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return

        if self.remaining_items > 0:
            self.remaining_items -= random.randint(1, min(5, self.remaining_items))
            if self.remaining_items > 0:
                await interaction.message.edit(content=f"{interaction.user.mention}, осталось собрать: {self.remaining_items}.", view=self)
            else:
                await self.complete_order(interaction)

    async def complete_order(self, interaction: nextcord.Interaction):
        earnings = random.randint(50, 10000)
        player_funds[self.user_id] = player_funds.get(self.user_id, 0) + earnings
        save_funds()

        self.clear_items()
        self.exit_button.disabled = False
        new_order_button = Button(label="Начать новый заказ", style=nextcord.ButtonStyle.green)
        new_order_button.callback = self.start_new_order
        self.add_item(new_order_button)
        self.add_item(self.exit_button)

        await interaction.message.edit(content=f"Заказ завершен! Заработано: {earnings}.\nХотите новый?", view=self)

    async def start_new_order(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id: return
        new_order_size = random.randint(1, 30)
        new_view = PackingView(self.user_id, new_order_size)
        await interaction.message.edit(content=f"Новый заказ: {new_order_size} товаров. Выберите коробку.", view=new_view)

    async def exit_job(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id: return
        await interaction.message.edit(content=f"{interaction.user.mention}, вы вышли с работы.", view=None)


class PickingView(View):
    def __init__(self, user_id: str):
        super().__init__()
        self.user_id = user_id
        self.pick_button = Button(label="Skenovat' produkt", style=nextcord.ButtonStyle.green)
        self.pick_button.callback = self.pick_positions
        self.exit_button = Button(label="Выйти с работы", style=nextcord.ButtonStyle.red, disabled=True)
        self.exit_button.callback = self.exit_job
        self.add_item(self.pick_button)
        self.add_item(self.exit_button)
        self.disabled_btn = False

    async def pick_positions(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Это не ваш заказ!", ephemeral=True)
            return
        
        if self.disabled_btn:
            await interaction.response.send_message("Подождите перед следующим нажатием!", ephemeral=True)
            return

        positions = [p for p in ORDERS.get(self.user_id, []) if p["status"] == "не выполнено"]
        if not positions:
            await self.switch_to_finish_button(interaction)
            return

        if random.random() < 0.03:
            self.pick_button.disabled = True
            self.disabled_btn = True
            wait_time = random.randint(5, 15)  # Уменьшил для играбельности, поменяй обратно на 60-300 если нужно
            await interaction.message.edit(content=f"{interaction.user.mention}, ошибка сканера. Ожидание {wait_time}с...", view=self)
            await asyncio.sleep(wait_time)
            self.pick_button.disabled = False
            self.disabled_btn = False
            await interaction.message.edit(content=f"{interaction.user.mention}, можно продолжать.", view=self)
            return

        num_to_pick = random.randint(1, 5)
        for _ in range(min(num_to_pick, len(positions))):
            positions[0]["status"] = "выполнено"
            positions.pop(0)

        incomplete, completed = [], []
        for i, p in enumerate(ORDERS[self.user_id]):
            if p["status"] == "не выполнено":
                incomplete.append(f"{i+1}. {p['location']} ({p['item']})")
            else:
                completed.append(f"✅~~{i+1}. {p['location']} ({p['item']})~~✅")

        pickup_list = "\n".join(completed) + "\n\n" + "\n".join(incomplete)
        await interaction.message.edit(content=f"{interaction.user.mention}, обновленный лист:\n{pickup_list}")

        if not positions:
            await self.switch_to_finish_button(interaction)

    async def switch_to_finish_button(self, interaction: nextcord.Interaction):
        self.clear_items()
        finish_button = Button(label="Odoslat' objednavku", style=nextcord.ButtonStyle.blurple)
        finish_button.callback = self.finish_order
        self.add_item(finish_button)
        self.exit_button.disabled = False
        self.add_item(self.exit_button)
        await interaction.message.edit(view=self)

    async def finish_order(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id: return
        
        num_positions = len(ORDERS.get(self.user_id, []))
        priemer = priemer_data.get(self.user_id, 0)

        if self.user_id not in order_history:
            order_history[self.user_id] = []
        order_history[self.user_id].append(num_positions)

        if priemer < 60: earnings = random.randint(50, 10000)
        elif priemer < 80: earnings = random.randint(10000, 20000)
        elif priemer < 120: earnings = random.randint(20000, 50000)
        else: earnings = random.randint(50000, 100000)

        tax = 0.07 if earnings <= 47000 else 0.19
        tax_amount = int(earnings * tax)
        final_earnings = earnings - tax_amount

        player_funds[self.user_id] = player_funds.get(self.user_id, 0) + final_earnings
        save_funds()
        ORDERS.pop(self.user_id, None)

        await interaction.message.edit(content=f"Заказ завершен! Заработок: {earnings}. Налог: {tax_amount}. Итого: {final_earnings}. Ваш priemer: {priemer}", view=None)
        await self.show_new_order_button(interaction)

    async def show_new_order_button(self, interaction: nextcord.Interaction):
        self.clear_items()
        btn = Button(label="Начать новый заказ", style=nextcord.ButtonStyle.green)
        btn.callback = self.start_new_order
        self.add_item(btn)
        self.add_item(self.exit_button)
        await interaction.message.edit(view=self)

    async def start_new_order(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id: return
        ORDERS[self.user_id] = generate_order()
        pickup_list = "\n".join([f"{i+1}. {o['location']} ({o['item']})" for i, o in enumerate(ORDERS[self.user_id])])
        view = PickingView(self.user_id)
        await interaction.channel.send(f"Новый заказ из {len(ORDERS[self.user_id])} позиций.\n\n**Лист:**\n{pickup_list}", view=view)
        await interaction.message.delete()

    async def exit_job(self, interaction: nextcord.Interaction):
        if str(interaction.user.id) != self.user_id: return
        ORDERS.pop(self.user_id, None)
        await interaction.message.edit(content=f"{interaction.user.mention}, вы вышли с работы.", view=None)

@bot.command(name="gb")
async def start_job(ctx):
    await ctx.message.delete()
    job = random.choice(["пикинг", "баление"])
    user_id = str(ctx.author.id)

    if job == "пикинг":
        ORDERS[user_id] = generate_order()
        priemer_data[user_id] = priemer_data.get(user_id, 0)
        save_priemer()
        pickup_list = "\n".join([f"{i+1}. {o['location']} ({o['item']})" for i, o in enumerate(ORDERS[user_id])])
        view = PickingView(user_id)
        await ctx.send(f"{ctx.author.mention}, пикинг. {len(ORDERS[user_id])} позиций.\n**Лист:**\n{pickup_list}", view=view)
    elif job == "баление":
        order_size = random.randint(1, 30)
        view = PackingView(user_id, order_size)
        await ctx.send(f"{ctx.author.mention}, баление. Выберите коробку для {order_size} товаров.", view=view)


# --- ФИНАНСЫ И ПЕРЕВОДЫ ---

@bot.command(name="pay")
async def pay(ctx, member: nextcord.Member, amount: int):
    await ctx.message.delete()
    sender_id, receiver_id = str(ctx.author.id), str(member.id)

    if amount <= 0:
        await ctx.send(f"{ctx.author.mention}, сумма должна быть положительной!")
        return
    if player_funds.get(sender_id, 0) < amount:
        await ctx.send(f"{ctx.author.mention}, недостаточно средств!")
        return

    player_funds[sender_id] -= amount
    player_funds[receiver_id] = player_funds.get(receiver_id, 0) + amount
    save_funds()
    await ctx.send(f"{ctx.author.mention} перевел {amount} денег {member.mention}!")

@bot.command(name="money")
async def check_funds(ctx):
    await ctx.message.delete()
    await init_player_funds(ctx)
    await ctx.send(f"{ctx.author.mention}, у вас {player_funds[str(ctx.author.id)]} денег.")

# --- КРЕДИТЫ ---

async def get_user_age_on_server(ctx, user_id):
    member = await ctx.guild.fetch_member(user_id)
    if not member or not member.joined_at: return None
    return (datetime.now(timezone.utc) - member.joined_at).days

def get_max_loan_amount(age_on_server):
    if age_on_server < 30: return 0
    elif age_on_server < 60: return 100000
    elif age_on_server < 90: return 300000
    elif age_on_server < 120: return 500000
    return 1000000

@bot.command()
async def applyloan(ctx, loan_amount: int, loan_term: int):
    await ctx.message.delete()
    user_id = str(ctx.author.id)

    if user_id in player_loans and player_loans[user_id]:
        await ctx.send("У вас уже есть активный кредит.")
        return
    if loan_term > 7:
        await ctx.send("Максимальный срок кредита — 7 дней.")
        return

    age_on_server = await get_user_age_on_server(ctx, ctx.author.id)
    if age_on_server is None: return

    max_loan = get_max_loan_amount(age_on_server)
    if loan_amount > max_loan:
        await ctx.send(f"Ваш лимит кредита: {max_loan}.")
        return

    interest_rate = 0.15 if age_on_server > 120 else 0.20
    daily_payment = int((loan_amount * (1 + interest_rate)) / loan_term)
    due_date = (datetime.now() + timedelta(days=loan_term)).strftime("%Y-%m-%d")

    player_loans[user_id] = [{
        "loan_amount": loan_amount,
        "interest_rate": interest_rate,
        "daily_payment": daily_payment,
        "loan_term": loan_term,
        "due_date": due_date,
        "paid_amount": 0
    }]
    player_funds[user_id] = player_funds.get(user_id, 0) + loan_amount
    save_funds()
    save_loans()

    await ctx.send(f"{ctx.author.mention} взял кредит на {loan_amount}. Платеж: {daily_payment}/день. Дата: {due_date}.")

@tasks.loop(minutes=60)
async def send_loan_warnings():
    for user_id, loans in player_loans.items():
        for loan in loans:
            due_date = datetime.strptime(loan['due_date'], "%Y-%m-%d")
            diff = due_date - datetime.now()
            user = bot.get_user(int(user_id))
            if not user: continue
            
            if diff.days == 3: await user.send(f"Кредит истекает через 3 дня ({loan['due_date']}).")
            elif diff.days == 1: await user.send(f"Кредит истекает через 1 день ({loan['due_date']}).")

@bot.command()
async def handleunpaidloan(ctx):
    await ctx.message.delete()
    user_id = str(ctx.author.id)

    if not player_loans.get(user_id):
        await ctx.send("У вас нет кредита.")
        return

    loan = player_loans[user_id][0]
    due_date = datetime.strptime(loan['due_date'], "%Y-%m-%d")

    if datetime.now() > due_date:
        if (datetime.now() - due_date).days > 2:
            player_funds[user_id] -= loan['loan_amount'] * 10
            player_loans[user_id].remove(loan)
            save_funds()
            save_loans()
            await ctx.send(f"Кредит просрочен. Списано {loan['loan_amount'] * 10}.")
        else:
            await ctx.send(f"У вас еще есть время, долг увеличен вдвое. Дата: {loan['due_date']}.")
    else:
        await ctx.send("Ваш кредит еще не просрочен.")

# --- ПЕТИЦИИ ---

async def handle_admin_vote(ctx, petition_id: int, vote_type: str):
    await ctx.message.delete()
    if not ctx.author.guild_permissions.administrator:
        await ctx.send("Только для админов.", delete_after=5)
        return

    try:
        with open("petitions.json", "r", encoding="utf-8") as f:
            petitions = json.load(f)
    except:
        return await ctx.send("Нет активных петиций.", delete_after=5)

    for petition in petitions:
        if petition["id"] == petition_id:
            if petition["status"] != "active":
                return await ctx.send("Петиция закрыта.", delete_after=5)
            if petition["votes"] < petition["required_votes"]:
                return await ctx.send("Мало голосов.", delete_after=5)

            if ctx.author.id in petition["reviews"]["yes"] or ctx.author.id in petition["reviews"]["no"]:
                return await ctx.send("Вы уже голосовали.", delete_after=5)

            petition["reviews"][vote_type].append(ctx.author.id)
            total_votes = len(petition["reviews"]["yes"]) + len(petition["reviews"]["no"])
            
            if total_votes >= 3:
                if len(petition["reviews"]["yes"]) > len(petition["reviews"]["no"]):
                    petition["status"] = "approved"
                else:
                    petition["status"] = "rejected"

            with open("petitions.json", "w", encoding="utf-8") as f:
                json.dump(petitions, f, indent=4)

            try:
                msg = await ctx.channel.fetch_message(petition["message_id"])
                content = f"**Петиция №{petition['id']}**\n{petition['text']}\n\nПодписей: {petition['votes']}/{petition['required_votes']}\n👮 Голоса админов: {total_votes}/3"
                if petition["status"] != "active":
                    status_text = "✅ Одобрена" if petition["status"] == "approved" else "❌ Отклонена"
                    content += f"\n\n{status_text} большинством голосов администраторов."
                await msg.edit(content=content)
            except: pass

            await ctx.send(f"Голос засчитан. Проголосовало {total_votes}/3 админов.", delete_after=5)
            return
    await ctx.send("Петиция не найдена.", delete_after=5)

@bot.command()
async def petition(ctx, *, text=None):
    await ctx.message.delete()
    if not text:
        return await ctx.send("Укажи текст петиции!", delete_after=5)

    try:
        with open("petitions.json", "r", encoding="utf-8") as f:
            petitions = json.load(f)
    except: petitions = []

    req_votes = max(1, int(ctx.guild.member_count * 0.1)) - 1
    p_id = len(petitions) + 1

    p_data = {
        "id": p_id, "author": ctx.author.id, "text": text,
        "votes": 0, "voters": [], "status": "active",
        "required_votes": req_votes,
        "reviews": {"yes": [], "no": []}
    }
    petitions.append(p_data)

    msg = await ctx.send(f"**Петиция №{p_id}**\n{text}\n\nПодписей: 0/{req_votes}\n👮 Голоса админов: 0/3\n\n📢 Подпиши: `!vote {p_id}`")
    p_data["message_id"] = msg.id

    with open("petitions.json", "w", encoding="utf-8") as f:
        json.dump(petitions, f, indent=4)

@bot.command()
async def vote(ctx, petition_id: int):
    await ctx.message.delete()
    try:
        with open("petitions.json", "r", encoding="utf-8") as f:
            petitions = json.load(f)
    except: return

    for p in petitions:
        if p["id"] == petition_id:
            if p["status"] != "active": return await ctx.send("Петиция закрыта.", delete_after=5)
            if str(ctx.author.id) in p["voters"]: return await ctx.send("Ты уже подписал.", delete_after=5)

            p["votes"] += 1
            p["voters"].append(str(ctx.author.id))
            with open("petitions.json", "w", encoding="utf-8") as f:
                json.dump(petitions, f, indent=4)

            try:
                msg = await ctx.channel.fetch_message(p["message_id"])
                content = f"**Петиция №{p['id']}**\n{p['text']}\n\nПодписей: {p['votes']}/{p['required_votes']}\n👮 Голоса админов: {len(p['reviews']['yes']) + len(p['reviews']['no'])}/3"
                if p["votes"] >= p["required_votes"]:
                    content += "\n\n🔔 Ожидает решения от администраторов (`!yes ID` / `!no ID`)."
                await msg.edit(content=content)
            except: pass
            return await ctx.send("✅ Ты подписал петицию.", delete_after=5)
    await ctx.send("Петиция не найдена.", delete_after=5)

@bot.command()
async def yes(ctx, petition_id: int):
    await handle_admin_vote(ctx, petition_id, "yes")

@bot.command()
async def no(ctx, petition_id: int):
    await handle_admin_vote(ctx, petition_id, "no")

# --- СОБЫТИЯ И СТАРТ ---

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    send_loan_warnings.start()
    update_priemer.start()

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
if TOKEN:
    bot.run(TOKEN)
else:
    print("Ошибка: Токен бота не найден! Проверьте файл .env")
