"""
data.py — все глобальные данные, константы, save/load функции.
Импортируется во все cog-модули.
"""
import json
import time

# ── File paths ────────────────────────────────────────────────
FUNDS_FILE      = "player_funds.json"
LOANS_FILE      = "player_loans.json"
BUSINESS_FILE   = "player_businesses.json"
PRIEMER_FILE    = "priemer_data.json"
ORDERS_FILE     = "orders_completed.json"
XP_FILE         = "player_xp.json"
INVENTORY_FILE  = "player_inventory.json"
DAILY_FILE      = "player_daily.json"
BANK_FILE       = "player_bank.json"
SERVER_EFF_FILE = "server_effects.json"
WARNS_FILE      = "player_warns.json"


# ── JSON helpers ──────────────────────────────────────────────
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


# ── Player data ───────────────────────────────────────────────
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


# ── Save functions ────────────────────────────────────────────
def save_funds():       save_json(FUNDS_FILE,      player_funds)
def save_loans():       save_json(LOANS_FILE,      player_loans)
def save_businesses():  save_json(BUSINESS_FILE,   player_businesses)
def save_priemer():     save_json(PRIEMER_FILE,     priemer_data)
def save_xp():          save_json(XP_FILE,          player_xp)
def save_inventory():   save_json(INVENTORY_FILE,  player_inventory)
def save_daily():       save_json(DAILY_FILE,       player_daily)
def save_bank():        save_json(BANK_FILE,        player_bank)
def save_server_eff():  save_json(SERVER_EFF_FILE,  server_effects)
def save_warns():       save_json(WARNS_FILE,       player_warns)


# ── Mafia state ───────────────────────────────────────────────
MAFIA_DATA: dict = {
    "is_running":  False,
    "phase":       "waiting",   # waiting | night | day
    "players":     {},          # {user_id: {"role", "is_alive", "name"}}
    "actions":     {"kill": None, "heal": None, "check": None},
    "votes":       {},          # {voter_id: target_id}
    "night_count": 0,
    "channel_id":  None,
    "guild_id":    None,
}

# ── In-memory cooldowns & state ───────────────────────────────
ROB_CD:   dict = {}
CRIME_CD: dict = {}
FISH_CD:  dict = {}
XP_CD:    dict = {}

LOTTO_POOL:    dict = {}
LOTTO_RUNNING: dict = {}

ORDERS:         dict = {}
ORDER_MESSAGES: dict = {}
order_history:  dict = {}

# ── Economy constants ─────────────────────────────────────────
TAX_THRESHOLD = 20_000
DAILY_REWARDS = [500, 750, 1000, 1250, 1500, 2000, 3000]

# ── Roulette reds ─────────────────────────────────────────────
REDS = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}

# ── Shop items ────────────────────────────────────────────────
SHOP_ITEMS: dict = {
    "lucky_charm":    {"name": "🍀 Амулет удачи",     "price": 5000,  "desc": "+10% к выигрышу в играх (1 день)"},
    "pickaxe":        {"name": "⛏ Кирка",             "price": 3000,  "desc": "+20% к заработку на работе (1 день)"},
    "shield":         {"name": "🛡 Щит",               "price": 4000,  "desc": "Защита от ограбления (1 раз)"},
    "vip_pass":       {"name": "⭐ VIP пропуск",       "price": 50000, "desc": "+50% к ежедневному бонусу (7 дней)"},
    "fishing_rod":    {"name": "🎣 Удочка",            "price": 2000,  "desc": "Открывает команду !fish"},
    "bomb":           {"name": "💣 Бомба",             "price": 8000,  "desc": "Украсть от 10% до 30% денег у цели"},
    "lottery_ticket": {"name": "🎟 Лотерейный билет", "price": 500,   "desc": "Использовать !lotto для розыгрыша"},
}

# ── Fishing table ─────────────────────────────────────────────
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

# ── Work / GymBeam ────────────────────────────────────────────
SPORT_ITEMS_WITH_BRANDS: dict = {
    "GymBeam":           ["Протеиновый батончик", "Креатин", "BCAA", "Коллаген"],
    "BeastPink":         ["Лосины", "Спортивные шорты", "Шейкер"],
    "VanaVita":          ["Гейнер", "Витамины B", "Коллаген для суставов"],
    "XBEAM":             ["Ремни для жима", "Фитнес-трекеры", "Протеиновые батончики"],
    "STRIX":             ["Энергетические гели", "Силовые тренажеры"],
    "BSN":               ["Гейнер", "Креатин моногидрат", "БЦАА"],
    "Muscletech":        ["Гейнер", "Креатин моногидрат", "Протеиновые батончики"],
    "NOW Foods":         ["Омега-3", "Витамин C", "Л-карнитин"],
    "The Protein Works": ["Протеиновый коктейль", "Шейкер", "Гейнер"],
    "Universal":         ["Гейнер", "Протеиновый коктейль", "Креатин"],
}

# ── Business data ─────────────────────────────────────────────
business_types: dict = {
    "Киоск с едой":       {"base_cost":200,  "base_profit":20, "taxes":10, "service_cost":5,  "upgrade_cost":100, "repair_cost":0.20},
    "Автомойка":          {"base_cost":300,  "base_profit":25, "taxes":8,  "service_cost":7,  "upgrade_cost":120, "repair_cost":0.25},
    "Лотерейный магазин": {"base_cost":400,  "base_profit":30, "taxes":12, "service_cost":6,  "upgrade_cost":150, "repair_cost":0.30},
    "Офис IT-услуг":      {"base_cost":500,  "base_profit":40, "taxes":15, "service_cost":10, "upgrade_cost":200, "repair_cost":0.35},
    "Фитнес-клуб":        {"base_cost":350,  "base_profit":28, "taxes":5,  "service_cost":8,  "upgrade_cost":140, "repair_cost":0.15},
}

unique_items_biz: dict = {
    "Киоск с едой":       {"item_name": "Фирменный фургон",   "effect": "increase_speed",          "duration": 86400, "description": "Скорость операций +10% на 24ч."},
    "Автомойка":          {"item_name": "Промо-карты",        "effect": "double_profit",            "duration": 3600,  "description": "2× прибыль для всех на 1ч."},
    "Лотерейный магазин": {"item_name": "Золотой билет",      "effect": "increase_item_chance",     "duration": 86400, "description": "Шанс редких предметов +10% на 24ч."},
    "Офис IT-услуг":      {"item_name": "Виртуальный сервер", "effect": "speed_up_upgrades",        "duration": 86400, "description": "Улучшения ×1.2 скорее на 24ч."},
    "Фитнес-клуб":        {"item_name": "Персональный тренер","effect": "increase_event_frequency", "duration": 86400, "description": "Событий +10% на 24ч."},
}

# ── Blackjack helpers ─────────────────────────────────────────
card_values: dict = {
    "2":2,"3":3,"4":4,"5":5,"6":6,"7":7,"8":8,"9":9,"10":10,
    "J":10,"Q":10,"K":10,"A":11,
}
suits: dict = {"hearts":"♥","diamonds":"♦","clubs":"♣","spades":"♠"}

# ── Voice / Auto-channels ─────────────────────────────────────
AUTO_CHANNELS: dict = {
    1402746822191218749: 1402733375986466816,
    1402746847713296526: 1402732822375960676,
    1402746870773584062: 1402732572206960661,
    1472756792491643031: 1402748456883454097,
}
YOUR_USER_ID = 878322259469688832

# ── XP constants ──────────────────────────────────────────────
XP_PER_MESSAGE = (2, 8)
