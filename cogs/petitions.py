import json
import discord
from discord.ext import commands


class PetitionsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def _load(self):
        try:
            with open("petitions.json", "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save(self, data):
        with open("petitions.json", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)

    @commands.command(name="petition", brief="Создать петицию")
    async def petition(self, ctx, *, text: str = None):
        await ctx.message.delete()
        if not text:
            await ctx.send("❗ `!petition <текст>`", delete_after=10); return

        petitions = self._load()
        pid      = len(petitions) + 1
        required = max(1, int(ctx.guild.member_count * 0.1) - 1)
        data = {
            "id": pid, "author": ctx.author.id, "text": text,
            "votes": 0, "voters": [], "status": "active",
            "message_id": None, "required_votes": required,
            "reviews": {"yes": [], "no": []},
        }
        petitions.append(data)
        self._save(petitions)

        msg = await ctx.send(
            f"📜 **Петиция №{pid}**\n{text}\n\n"
            f"Автор: <@{ctx.author.id}>\nПодписей: 0/{required}\n👮 Голоса: 0/3\n\n"
            f"✍️ `!vote {pid}`")
        data["message_id"] = msg.id
        self._save(petitions)

    @commands.command(name="vote", brief="Подписать петицию")
    async def vote_petition(self, ctx, petition_id: int = None):
        await ctx.message.delete()
        if petition_id is None:
            await ctx.send("❗ `!vote <номер>`", delete_after=10); return

        petitions = self._load()
        p = next((x for x in petitions if x["id"] == petition_id), None)
        if not p:
            await ctx.send("Петиция не найдена.", delete_after=5); return
        if p["status"] != "active":
            await ctx.send("Петиция закрыта.", delete_after=5); return
        if str(ctx.author.id) in [str(v) for v in p["voters"]]:
            await ctx.send("Ты уже подписал.", delete_after=5); return

        p["votes"] += 1
        p["voters"].append(str(ctx.author.id))
        self._save(petitions)

        av      = len(p.get("reviews",{}).get("yes",[])) + len(p.get("reviews",{}).get("no",[]))
        content = (f"📜 **Петиция №{p['id']}**\n{p['text']}\n\n"
                   f"Автор: <@{p['author']}>\nПодписей: **{p['votes']}/{p['required_votes']}**\n"
                   f"👮 Голоса: {av}/3\n\n"
                   f"{'🔔 Ожидает решения админов!' if p['votes'] >= p['required_votes'] else f'✍️ `!vote {p[chr(105)+chr(100)]}`'}")
        try:
            msg = await ctx.channel.fetch_message(p["message_id"])
            await msg.edit(content=content)
        except Exception: pass
        await ctx.send("✅ Подпись принята!", delete_after=5)

    @commands.command(name="yes", brief="[Админ] Одобрить петицию")
    async def yes_petition(self, ctx, petition_id: int):
        await self._handle_admin_vote(ctx, petition_id, "yes")

    @commands.command(name="no", brief="[Админ] Отклонить петицию")
    async def no_petition(self, ctx, petition_id: int):
        await self._handle_admin_vote(ctx, petition_id, "no")

    async def _handle_admin_vote(self, ctx, petition_id: int, vote_type: str):
        await ctx.message.delete()
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("Только администратор!", delete_after=5); return

        petitions = self._load()
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

                self._save(petitions)
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

    @commands.command(name="petitions", brief="Список активных петиций")
    async def list_petitions(self, ctx):
        await ctx.message.delete()
        petitions = self._load()
        active = [p for p in petitions if p["status"] == "active"]
        if not active:
            await ctx.send("Нет активных петиций.", delete_after=5); return
        embed = discord.Embed(title="📜 Активные петиции", color=discord.Color.blue())
        for p in active[:10]:
            embed.add_field(
                name=f"#{p['id']}: {p['text'][:60]}{'...' if len(p['text'])>60 else ''}",
                value=f"Подписей: {p['votes']}/{p['required_votes']}",
                inline=False)
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(PetitionsCog(bot))
