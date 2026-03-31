import discord
from discord.ext import commands


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

        if command.help:
            embed.add_field(name="📖 Описание", value=command.help, inline=False)
        else:
            embed.add_field(name="📖 Описание", value="_Подробное описание отсутствует._", inline=False)

        if command.aliases:
            embed.add_field(
                name="🔀 Псевдонимы",
                value=", ".join(f"`!{a}`" for a in command.aliases),
                inline=False
            )

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
    def command_not_found(self, string):
        return f"❌ Команда `!{string}` не найдена. Используй `!help` для списка команд."

    async def send_error_message(self, error):
        ctx = self.context
        await ctx.send(error, delete_after=8)
