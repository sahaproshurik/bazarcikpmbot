import random
import asyncio
import discord
from discord.ext import commands
from data import player_funds, TAX_THRESHOLD, REDS, card_values, suits, save_funds
from cogs.economy import init_player, calculate_tax


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


class GamesCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Blackjack ─────────────────────────────────────────────
    @commands.command(name="bj", brief="Сыграть в Блэкджек")
    async def blackjack(self, ctx, bet: int):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)

        if bet <= 0 or bet > player_funds.get(uid, 0):
            await ctx.send("❌ Неверная ставка!", delete_after=5); return

        player_funds[uid] -= bet
        save_funds()
        deck = create_deck()
        ph   = [deck.pop(), deck.pop()]
        dh   = [deck.pop(), deck.pop()]

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
                msg = await self.bot.wait_for("message", check=check, timeout=60)
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

    # ── Flip ──────────────────────────────────────────────────
    @commands.command(name="flip", brief="Подбросить монетку на ставку")
    async def flip(self, ctx, bet: int, choice: str):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)

        if bet <= 0 or bet > player_funds.get(uid, 0):
            await ctx.send("❌ Неверная ставка!", delete_after=5); return

        orly  = ["о", "орел", "o", "orel"]
        rshka = ["р", "решка", "p", "reshka"]
        cl    = choice.strip().lower()
        if cl not in orly + rshka:
            await ctx.send("Выбери **Орёл** (о) или **Решка** (р).", delete_after=5); return

        chosen = "Орёл" if cl in orly else "Решка"
        player_funds[uid] -= bet
        result = random.choice(["Орёл", "Решка"])

        if result == chosen:
            w   = bet * 2
            tax = calculate_tax(w - bet)
            player_funds[uid] += w - tax
            save_funds()
            await ctx.send(f"🪙 {ctx.author.mention} выпал **{result}**! Выигрыш: **{w-tax:,}** 💰")
        else:
            save_funds()
            await ctx.send(f"🪙 {ctx.author.mention} выпал **{result}**. Проигрыш! Баланс: **{player_funds[uid]:,}** 💰")

    # ── Slots ─────────────────────────────────────────────────
    @commands.command(name="spin", brief="Сыграть в слоты")
    async def spin(self, ctx, bet: int):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
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

    # ── Dice ──────────────────────────────────────────────────
    @commands.command(name="dice", brief="Угадать число на кубике")
    async def dice_game(self, ctx, bet: int, number: int):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
        uid = str(ctx.author.id)

        if not 1 <= number <= 6:
            await ctx.send("Число от 1 до 6!", delete_after=5); return
        if bet <= 0 or bet > player_funds.get(uid, 0):
            await ctx.send("❌ Неверная ставка!", delete_after=5); return

        player_funds[uid] -= bet
        roll  = random.randint(1, 6)
        faces = {1:"⚀",2:"⚁",3:"⚂",4:"⚃",5:"⚄",6:"⚅"}
        save_funds()

        if roll == number:
            w = bet * 5
            player_funds[uid] += w
            save_funds()
            await ctx.send(f"🎲 {ctx.author.mention} выпало **{faces[roll]}** — УГАДАЛ! Выигрыш: **{w:,}** 💰!")
        else:
            await ctx.send(f"🎲 {ctx.author.mention} выпало **{faces[roll]}** (загадал {number}). Проигрыш! Баланс: **{player_funds[uid]:,}**")

    # ── Roulette ──────────────────────────────────────────────
    @commands.command(name="roulette", brief="Сыграть в рулетку")
    async def roulette(self, ctx, bet: int, choice: str):
        await ctx.message.delete()
        await init_player(self.bot, ctx)
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
            if int(ch) == number: won = bet * 35
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


def setup(bot):
    bot.add_cog(GamesCog(bot))
