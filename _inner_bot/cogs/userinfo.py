"""Userinfo / Avatar: Detaillierte User-Informationen."""
import discord
from discord import app_commands
from discord.ext import commands


class Userinfo(commands.Cog):
    """Userinfo und Avatar (Slash Commands)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='userinfo', description='Zeigt Infos über einen User')
    @app_commands.describe(user='User (optional, standard: du)')
    async def cmd_userinfo(self, interaction: discord.Interaction, user: discord.Member = None):
        if user is None:
            user = interaction.user

        embed = discord.Embed(
            title=f'👤 {user.display_name}',
            color=user.color if user.color != discord.Color.default() else discord.Color.blue()
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name='Username', value=user.name, inline=True)
        embed.add_field(name='Nickname', value=user.nick or 'Kein Nickname', inline=True)
        embed.add_field(name='ID', value=user.id, inline=True)
        embed.add_field(name='Erstellt am', value=f'<t:{int(user.created_at.timestamp())}:R>', inline=True)
        embed.add_field(name='Beigetreten am',
                        value=f'<t:{int(user.joined_at.timestamp())}:R>' if user.joined_at else 'Unbekannt', inline=True)

        status_emoji = {
            discord.Status.online: '🟢 Online', discord.Status.idle: '🟡 Idle',
            discord.Status.dnd: '🔴 DnD', discord.Status.offline: '⚫ Offline'
        }
        embed.add_field(name='Status', value=status_emoji.get(user.status, 'Unbekannt'), inline=True)

        roles = [r.mention for r in user.roles[1:]]
        if roles:
            role_text = ', '.join(roles[:20])
            if len(roles) > 20:
                role_text += f' +{len(roles) - 20} weitere'
            embed.add_field(name=f'Rollen ({len(roles)})', value=role_text, inline=False)

        top_role = user.top_role
        if top_role.name != '@everyone':
            embed.add_field(name='Top-Rolle', value=top_role.mention, inline=True)

        if user.joined_at:
            member_count = sum(1 for m in interaction.guild.members if m.joined_at and m.joined_at <= user.joined_at)
            embed.set_footer(text=f'Mitglied #{member_count}')

        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='avatar', description='Zeigt den Avatar eines Users')
    @app_commands.describe(user='User (optional)')
    async def cmd_avatar(self, interaction: discord.Interaction, user: discord.Member = None):
        if user is None:
            user = interaction.user

        embed = discord.Embed(
            title=f'🖼️ Avatar von {user.display_name}',
            color=user.color if user.color != discord.Color.default() else discord.Color.blue()
        )
        embed.set_image(url=user.display_avatar.url)

        view = discord.ui.View()
        view.add_item(discord.ui.Button(label='Avatar öffnen', url=user.display_avatar.url, style=discord.ButtonStyle.link))
        await interaction.response.send_message(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Userinfo(bot))
