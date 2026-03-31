from datetime import datetime, timedelta
import pytz
import discord
from discord.ext import commands, tasks
from data import player_funds, player_loans, save_funds, save_loans


async def get_user_age_on_server(ctx, user_id):
    try:
        member = await ctx.guild.fetch_member(user_id)
        if not member or not member.joined_at: return None
        return (datetime.now(pytz.utc) - member.joined_at.astimezone(pytz.utc)).days
    except Exception:
        return None


def get_max_loan(age):
    if age < 30:  return 0
    if age < 60:  return 100_000
    if age < 90:  return 300_000
    if age < 120: return 500_000
    return 1_000_000


def get_loan_rate(age): return 0.15 if age > 120 else 0.20


def calc_daily_payment(amount, term, rate): return int(amount * (1 + rate) / term)


class LoansCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.send_loan_warnings.start()

    def cog_unload(self):
        self.send_loan_warnings.cancel()

    @commands.command(name="applyloan", brief="Оформить кредит")
    async def applyloan(self, ctx, loan_amount: int, loan_term: int):
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

        player_loans[uid] = [{"loan_amount": loan_amount, "interest_rate": rate,
                               "daily_payment": daily, "loan_term": loan_term,
                               "due_date": due, "paid_amount": 0}]
        player_funds[uid] = player_funds.get(uid, 0) + loan_amount
        save_funds(); save_loans()

        embed = discord.Embed(title="✅ Кредит оформлен", color=discord.Color.green())
        embed.add_field(name="Сумма",       value=f"{loan_amount:,} 💰")
        embed.add_field(name="Ставка",      value=f"{int(rate*100)}%")
        embed.add_field(name="Срок",        value=f"{loan_term} дней")
        embed.add_field(name="Ежедн.",      value=f"{daily:,} 💰")
        embed.add_field(name="Погасить до", value=due)
        embed.add_field(name="Баланс",      value=f"{player_funds[uid]:,} 💰")
        await ctx.send(ctx.author.mention, embed=embed)

    @commands.command(name="calculatecredit", brief="Рассчитать кредит до оформления")
    async def calc_credit(self, ctx, loan_amount: int, loan_term: int):
        await ctx.message.delete()
        age   = await get_user_age_on_server(ctx, ctx.author.id) or 0
        rate  = get_loan_rate(age)
        daily = calc_daily_payment(loan_amount, loan_term, rate)
        total = int(loan_amount * (1 + rate))
        await ctx.send(
            f"📊 Кредит **{loan_amount:,}** на **{loan_term}** дней\n"
            f"Ставка: **{int(rate*100)}%** | Итого: **{total:,}** | Ежедневно: **{daily:,}** 💰")

    @commands.command(name="checkloan", brief="Посмотреть статус своего кредита")
    async def check_loan(self, ctx):
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

        embed = discord.Embed(title=f"💳 Кредит {ctx.author.display_name}", color=discord.Color.red())
        embed.add_field(name="Сумма",    value=f"{loan['loan_amount']:,}")
        embed.add_field(name="Ставка",   value=f"{int(loan['interest_rate']*100)}%")
        embed.add_field(name="Итого",    value=f"{total:,}")
        embed.add_field(name="Оплачено", value=f"{paid:,}")
        embed.add_field(name="Остаток",  value=f"{remaining:,}")
        embed.add_field(name="Дней",     value=str(days_left))
        embed.add_field(name="Срок",     value=loan["due_date"])
        await ctx.send(embed=embed)

    @commands.command(name="payloan", brief="Погасить кредит (частично или полностью)")
    async def pay_loan(self, ctx, amount: int):
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

        player_funds[uid]   -= amount
        loan["paid_amount"] += amount

        if loan["paid_amount"] >= total:
            player_loans[uid].pop(0)
            await ctx.send(f"✅ {ctx.author.mention}, кредит погашен! Баланс: **{player_funds[uid]:,}** 💰")
        else:
            await ctx.send(f"💳 {ctx.author.mention}, внесено **{amount:,}** 💰. Остаток: **{remaining-amount:,}** 💰. Баланс: **{player_funds[uid]:,}**")
        save_funds(); save_loans()

    @tasks.loop(hours=1)
    async def send_loan_warnings(self):
        now = datetime.now()
        for uid, loans in list(player_loans.items()):
            for loan in loans:
                due  = datetime.strptime(loan["due_date"], "%Y-%m-%d")
                diff = due - now
                user = self.bot.get_user(int(uid))
                if not user: continue
                try:
                    if timedelta(days=2, hours=23) < diff <= timedelta(days=3):
                        await user.send(f"⚠️ Кредит истекает через **3 дня** ({loan['due_date']})!")
                    elif timedelta(hours=23) < diff <= timedelta(days=1):
                        await user.send(f"⚠️ Кредит истекает завтра ({loan['due_date']})!")
                except Exception:
                    pass


async def setup(bot):
    await bot.add_cog(LoansCog(bot))
