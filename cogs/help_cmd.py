import discord
from discord.ext import commands
from cogs.help_texts import HELP_TEXTS


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
            except discord.Forbidden:
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
                ("`!casino`",                   "Лобби казино: выплаты, правила, твоя статистика"),
                ("`!bj ставка`",                "Блэкджек на кнопках, можно удвоить (×3 блэкджек / ×2 победа)"),
                ("`!flip ставка [о|р]`",        "Орёл или решка (×2)"),
                ("`!spin ставка`",              "Слоты (×5 джекпот / ×2 два одинаковых)"),
                ("`!dice ставка [1-6]`",        "Угадай кубик (×5)"),
                ("`!roulette ставка [выбор]`",  "Рулетка: red/black/green/число (×2–×35)"),
                ("Ставка",                      "число, `5k`, `1.5m`, `all` или `half`; выбор можно не писать — будут кнопки"),
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
            "📦 Работа на складе GymBeam": [
                ("`!gb [pick|pack]`",   "Смена: пикинг по уличкам или упаковка (без аргумента — случайно)"),
                ("`!priemer [@user]`",  "Приемер: эффективность и вилка оплаты пикинга"),
            ],
            "🍔 Работа в McDonald's": [
                ("`!mc [позиция]`",    "Смена: зал, касса, фри, выдача, сборка, макавто, гриль"),
                ("`!mcstats [@user]`", "Карьера: звание, рейтинг, ошибки в КЛН, открытые позиции"),
                ("`!mchelp`",          "Как устроен ресторан и карьерная лестница"),
            ],
            "📜 Петиции": [
                ("`!petition текст`",   "Создать петицию"),
                ("`!vote номер`",       "Подписать петицию"),
                ("`!petitions`",        "Список активных петиций"),
                ("`!yes номер`",        "🔑 Проголосовать «За» (Admin)"),
                ("`!no номер`",         "🔑 Проголосовать «Против» (Admin)"),
            ],
            "🛡️ Модерация": [
                ("`!mute @user [10m|2h|1d] [причина]`", "🔑 Тайм-аут (по умолчанию 10 минут)"),
                ("`!unmute @user`",                     "🔑 Снять тайм-аут"),
                ("`!ban @user|ID [7d|perm] [причина]`", "🔑 Бан, временный снимается сам"),
                ("`!unban ID`",                         "🔑 Разбанить"),
                ("`!kick @user [причина]`",             "🔑 Кикнуть участника"),
                ("`!warn @user [причина]`",             "🔑 Варн (3 — тайм-аут 1ч, 5 — 1д, 7 — кик)"),
                ("`!warns [@user]`",                    "Посмотреть варны"),
                ("`!delwarn @user N` / `!clearwarn @user`", "🔑 Снять один / все варны"),
                ("`!clear N [@user|bots|links|files]`", "🔑 Удалить сообщения с фильтром"),
                ("`!clearday N` / `!clearuser @user N`", "🔑 Удалить за N дней / от участника"),
                ("`!lock` / `!unlock` / `!slowmode 10s`", "🔑 Закрыть, открыть канал, медленный режим"),
                ("`!lockdown` / `!unlockdown`",         "🔑 Закрыть весь сервер при рейде"),
                ("`!case N` / `!history @user`",        "🔑 Журнал наказаний"),
                ("`!snipe`",                            "🔑 Последнее удалённое сообщение"),
            ],
            "⚙️ Настройка сервера": [
                ("`!setlog #канал`",              "🔑 Логи: удаления, правки, входы, наказания"),
                ("`!automod [on|off]`",           "🔑 Автомод: флуд, инвайты, капс, упоминания"),
                ("`!badword add|remove|list`",    "🔑 Запрещённые слова"),
                ("`!autorole @роль`",             "🔑 Роль для новичков"),
                ("`!welcome #канал текст`",       "🔑 Приветствие новичков"),
                ("`!rolemenu Заголовок | @роли`", "🔑 Кнопки самовыдачи ролей"),
                ("`!nick @user ник` / `!role @user @роль`", "🔑 Ник и роли участника"),
                ("`!botstatus` / `!backup`",      "🔑 Состояние бота / бэкап данных в ЛС"),
                ("`!adminhelp`",                  "Шпаргалка по админ-командам"),
            ],
            "🤖 ИИ и голос": [
                ("`!ask вопрос`",      "Спросить ИИ (в войсе ещё и озвучит)"),
                ("`!aiclear`",         "Очистить память ИИ"),
                ("`!aivoice [голос]`", "Сменить голос озвучки"),
                ("`!join` / `!leave`", "Позвать / выгнать бота из войса"),
                ("`!listen` / `!stoplisten`", "Бот слушает войс и отвечает на «Базарчик, …»"),
                ("🎤 голосовое «Базарчик, …»",  "Ответ на голосовое сообщение в чате"),
                ("🗣️ «Базарчик, сделай …»",    "Джарвис: бот сам выполнит команду — баланс, бонус, казино, работа, "
                                                "модерация (только после «да»)"),
                ("`!jarvis`",                   "Что бот умеет по голосовой команде"),
            ],
            "🕵️ Мафия": [
                ("`!mafia_start`",          "Открыть набор в игру"),
                ("`!mafia_go`",             "Начать игру"),
                ("`!kill` / `!heal` / `!check N`", "Ночные действия (в ЛС бота)"),
                ("`!mafia_vote N`",         "Голосовать днём"),
                ("`!mafia_end_day`",        "Завершить день"),
                ("`!mafia_status`",         "Статус игры"),
                ("`!mafia_stop`",           "Остановить игру"),
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
                emb = discord.Embed(
                    title="📖 Помощь — BAZARCIK_PM",
                    description=(
                        "Полный список команд бота. Префикс: **`!`**\n"
                        "🔑 = только администраторы\n"
                        "Подробнее по команде: **`!help <команда>`**\n\u200b"
                    ),
                    color=discord.Color.blurple()
                )
                first = False
            else:
                emb = discord.Embed(color=discord.Color.blurple())

            lines = "\n".join(f"{cmd} — {desc}" for cmd, desc in commands_list)
            emb.add_field(name=section_name, value=lines, inline=False)
            embeds.append(emb)

        embeds[-1].set_footer(text="Используй !help <команда> для подробной информации по любой команде")

        try:
            for emb in embeds:
                await ctx.author.send(embed=emb)
            if ctx.guild:
                await ctx.send(f"📬 {ctx.author.mention}, справка отправлена тебе в ЛС!", delete_after=8)
        except discord.Forbidden:
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

        embed = discord.Embed(
            title=f"📋 Справка: !{command.name}",
            color=discord.Color.gold()
        )

        if command.brief:
            embed.description = f"_{command.brief}_"

        params = command.signature or ""
        embed.add_field(
            name="📌 Синтаксис",
            value=f"`!{command.name} {params}`".strip(),
            inline=False
        )

        help_text = command.help or HELP_TEXTS.get(command.name)
        if help_text:
            embed.add_field(name="📖 Описание", value=help_text[:1024], inline=False)
        else:
            embed.add_field(name="📖 Описание", value="_Подробное описание отсутствует._", inline=False)

        if command.aliases:
            embed.add_field(
                name="🔀 Псевдонимы",
                value=", ".join(f"`!{a}`" for a in command.aliases),
                inline=False
            )

        for check in command.checks:
            if "has_permissions" in getattr(check, "__qualname__", "") or "is_owner" in getattr(check, "__qualname__", ""):
                embed.add_field(
                    name="🔑 Права",
                    value="Нужны права модератора/администратора сервера",
                    inline=False
                )
                break

        embed.set_footer(text="!help — список всех команд")
        await ctx.send(embed=embed)

    # ── !help <группа> ───────────────────────────────────────
    async def send_group_help(self, group):
        await self.send_command_help(group)

    # ── Команда не найдена ────────────────────────────────────
    def command_not_found(self, string):
        return f"❌ Команда `!{string}` не найдена. Используй `!help` для списка команд."

    async def send_error_message(self, error):
        ctx = self.context
        await ctx.send(error, delete_after=8)
