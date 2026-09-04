"""Server: /leave löscht alle Bot-Nachrichten und verlässt den Server."""
import discord
from discord import app_commands
from discord.ext import commands


class Server(commands.Cog):
    """Server-Management: leave."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='leave', description='Löscht alle Bot-Nachrichten und verlässt den Server')
    async def cmd_leave(self, interaction: discord.Interaction):
        from core.config import OWNER_ID
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message('⛔ Nur der Owner.', ephemeral=True)

        await interaction.response.send_message('🔄 Lösche alle Bot-Nachrichten...', ephemeral=True)
        msg = await interaction.original_response()

        deleted_msgs = 0
        for ch in interaction.guild.text_channels:
            try:
                async for message in ch.history(limit=200):
                    if message.author.bot:
                        try:
                            await message.delete()
                            deleted_msgs += 1
                        except Exception:
                            pass
            except Exception:
                pass

        try:
            await msg.edit(content=f'✅ **{deleted_msgs}** Bot-Nachrichten gelöscht.\n👋 Bot verlässt den Server in 5 Sekunden...')
        except Exception:
            pass

        import asyncio
        await asyncio.sleep(5)
        await interaction.guild.leave()


async def setup(bot: commands.Bot):
    await bot.add_cog(Server(bot))
