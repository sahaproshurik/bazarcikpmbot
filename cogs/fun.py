import random
import discord
from discord.ext import commands


def _load_text_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return [line for line in f.read().splitlines() if line.strip()]
    except FileNotFoundError:
        return ["Файл не найден."]


class FunCog(commands.Cog):
    def __init__(self, bot):
        self.bot    = bot
        self.jokes  = _load_text_file("jokes.txt")
        self.predictions = _load_text_file("predictions.txt")

    @commands.command(name="joke", aliases=["randomjoke", "jokes"], brief="Случайная шутка")
    async def tell_joke(self, ctx):
        await ctx.message.delete()
        await ctx.send(f"{ctx.author.mention} {random.choice(self.jokes)}")

    @commands.command(name="predict", aliases=["fortune", "prophecy"], brief="Случайное предсказание")
    async def tell_prediction(self, ctx):
        await ctx.message.delete()
        await ctx.send(f"{ctx.author.mention} {random.choice(self.predictions)}")

    @commands.command(name="greet", brief="Поприветствовать участника")
    async def greet_user(self, ctx, member: discord.Member):
        await ctx.message.delete()
        await ctx.send(f"Привет {member.mention} от бота базарчик пм")

    @commands.command(name="pick", brief="Позвать участника на сервер")
    async def pick_user(self, ctx, member: discord.Member):
        await ctx.message.delete()
        await ctx.send(f"{member.mention} а ну быстро зашол ато банчик")

    @commands.command(name="z", brief="Напомнить об украинском языке")
    async def z_user(self, ctx, member: discord.Member):
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

    @commands.command(name="random", brief="Случайный «невезучий» игрок дня")
    async def fortune_random(self, ctx):
        await ctx.message.delete()
        fortune_list = ["Игрок NIKUSA","Игрок REOSTISLAV","Игрок TANCHIK","Игрок STROLEKOFK"]
        await ctx.send(f"🎉 Сегодня удача не на стороне: **{random.choice(fortune_list)}**!")

    @commands.command(name="8ball", brief="Магический шар — ответ на любой вопрос")
    async def magic_8ball(self, ctx, *, question: str = None):
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
        embed = discord.Embed(color=discord.Color.dark_blue())
        embed.add_field(name="❓ Вопрос", value=question, inline=False)
        embed.add_field(name="🎱 Ответ",  value=random.choice(answers), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="rate", brief="Оценить что-либо по шкале 0-100")
    async def rate_something(self, ctx, *, thing: str = None):
        await ctx.message.delete()
        if not thing:
            await ctx.send("❗ `!rate <что-то>`", delete_after=5); return
        score    = random.randint(0, 100)
        bar_fill = score // 5
        bar      = "█" * bar_fill + "░" * (20 - bar_fill)
        await ctx.send(f"⭐ **{thing}**\n`[{bar}]` **{score}/100**")

    @commands.command(name="coinflip", aliases=["cf"], brief="Подбросить монетку (без ставки)")
    async def coinflip(self, ctx):
        await ctx.message.delete()
        result = random.choice(["🦅 Орёл", "🍀 Решка"])
        await ctx.send(f"🪙 {ctx.author.mention} бросил монетку — **{result}**!")

    @commands.command(name="hug", brief="Обнять участника")
    async def hug(self, ctx, member: discord.Member):
        await ctx.message.delete()
        msgs = [
            f"🤗 {ctx.author.mention} крепко обнимает {member.mention}!",
            f"💛 {ctx.author.mention} тепло обнял {member.mention}!",
            f"🤗 {member.mention} получает уютные объятия от {ctx.author.mention}!",
        ]
        await ctx.send(random.choice(msgs))

    @commands.command(name="slap", brief="Дать пощёчину участнику")
    async def slap(self, ctx, member: discord.Member):
        await ctx.message.delete()
        await ctx.send(f"👋 {ctx.author.mention} дал пощёчину {member.mention}!")

    @commands.command(name="kiss", brief="Поцеловать участника")
    async def kiss(self, ctx, member: discord.Member):
        await ctx.message.delete()
        await ctx.send(f"💋 {ctx.author.mention} поцеловал {member.mention}!")

    @commands.command(name="avatar", brief="Показать аватар участника")
    async def get_avatar(self, ctx, member: discord.Member = None):
        await ctx.message.delete()
        if member is None: member = ctx.author
        embed = discord.Embed(title=f"🖼️ Аватар {member.display_name}", color=discord.Color.blue())
        embed.set_image(url=member.display_avatar.url)
        await ctx.send(embed=embed)

    @commands.command(name="say", brief="[Админ] Написать от имени бота")
    @commands.has_permissions(administrator=True)
    async def say(self, ctx, *, text: str):
        await ctx.message.delete()
        await ctx.send(text)

    @commands.command(name="embed", brief="[Админ] Отправить красивый embed")
    @commands.has_permissions(administrator=True)
    async def embed_cmd(self, ctx, title: str, *, text: str):
        await ctx.message.delete()
        embed = discord.Embed(title=title, description=text, color=discord.Color.blurple())
        await ctx.send(embed=embed)

    @commands.command(name="announce", brief="[Админ] Сделать объявление с @here")
    @commands.has_permissions(administrator=True)
    async def announce(self, ctx, *, text: str):
        await ctx.message.delete()
        embed = discord.Embed(title="📢 Объявление", description=text, color=discord.Color.red())
        embed.set_footer(text=f"От {ctx.author.display_name}")
        await ctx.send("@here", embed=embed)


def setup(bot):
    bot.add_cog(FunCog(bot))
