"""Inv: Server-Invite für den Owner - funktioniert in DMs und Servern."""
import discord
from discord import app_commands
from discord.ext import commands


class Inv(commands.Cog):
    """Server-Invite für Owner."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='inv', description='Erstellt einen Server-Invite für dich')
    @app_commands.describe(server='Server-Name (nur in DMs nötig)')
    async def cmd_inv(self, interaction: discord.Interaction, server: str = None):
        from core.config import OWNER_ID
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message('⛔ Nur der Owner.', ephemeral=True)

        # In DMs: find server by name
        if not interaction.guild:
            if not server:
                # List all servers
                guilds = self.bot.guilds
                if not guilds:
                    return await interaction.response.send_message('❌ Bot ist auf keinem Server.', ephemeral=True)

                lines = []
                for g in guilds:
                    lines.append(f'• **{g.name}** (`{g.id}`)')

                embed = discord.Embed(
                    title='📋 Server-Liste',
                    description='\n'.join(lines) + '\n\nNutze `/inv server:Server-Name`',
                    color=discord.Color.blue()
                )
                return await interaction.response.send_message(embed=embed, ephemeral=True)

            # Find server by name
            guild = None
            for g in self.bot.guilds:
                if server.lower() in g.name.lower() or str(g.id) == server:
                    guild = g
                    break

            if not guild:
                return await interaction.response.send_message(f'❌ Server `{server}` nicht gefunden.', ephemeral=True)
        else:
            guild = interaction.guild

        # Generate invite
        channel = guild.system_channel
        if not channel:
            for ch in guild.text_channels:
                channel = ch
                break

        if not channel:
            return await interaction.response.send_message(f'❌ Kein Channel auf **{guild.name}** gefunden.', ephemeral=True)

        try:
            invite = await channel.create_invite(max_age=604800, max_uses=0, reason='Owner-Invite')
            embed = discord.Embed(
                title=f'🔗 {guild.name}',
                description=f'[**Server beitreten**]({invite.url})',
                color=discord.Color.green()
            )
            embed.set_footer(text='Gültig für 7 Tage')
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message(
                f'❌ Bot kann keine Einladungen auf **{guild.name}** erstellen.\n'
                f'Gib mir **"Einladungen erstellen"** Berechtigung.', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'❌ Fehler: {e}', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Inv(bot))
