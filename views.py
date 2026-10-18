"""
views.py — общая основа интерактивных сообщений с кнопками (McDonald's, склад, казино).
"""
import discord
from discord import Interaction
from discord.ui import View, Button

GREY  = discord.ButtonStyle.secondary
GREEN = discord.ButtonStyle.success
BLUE  = discord.ButtonStyle.primary
RED   = discord.ButtonStyle.danger


def progress_bar(done: int, total: int, width: int = 12) -> str:
    filled = round(width * done / total) if total else width
    return "▰" * filled + "▱" * (width - filled)


class OwnedView(View):
    """Кнопки, которые может нажимать только игрок, начавший игру/смену."""
    deny_text = "Это не твоя игра!"

    def __init__(self, user, timeout: float = 180):
        super().__init__(timeout=timeout)
        self.user = user
        self.uid  = str(user.id)

    async def interaction_check(self, interaction: Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(self.deny_text, ephemeral=True)
            return False
        self.message = interaction.message
        return True

    def btn(self, label, cb, style=GREY, row=None, emoji=None, disabled=False):
        b = Button(label=label, style=style, row=row, emoji=emoji, disabled=disabled)
        b.callback = cb
        self.add_item(b)
        return b

    async def push(self, interaction, **kw):
        """Ответ на нажатие, а если ответа нет (фоновый таймер) — правка сообщения."""
        if interaction is not None and not interaction.response.is_done():
            await interaction.response.edit_message(**kw)
        elif self.message is not None:
            await self.message.edit(**kw)
