"""Reaction Roles: Reaktionen auf Nachrichten zuweisen und Rollen vergeben."""
import discord
from discord import app_commands
from discord.ext import commands

from core.db import get_db
from core.logging import logger


def _parse_emoji(emoji_str: str):
    """Parst einen Emoji-String und liefert ein discord.PartialEmoji zurück."""
    return discord.PartialEmoji.from_str(emoji_str)


def _get_reaction_roles(guild_id: int):
    """Lädt alle Reaction-Roles für einen Server aus der DB."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM reaction_roles WHERE guild_id = ?',
        (str(guild_id),)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_reaction_role(guild_id: int, channel_id: int, message_id: int, emoji: str):
    """Prüft ob eine Reaction-Role existiert."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT * FROM reaction_roles WHERE guild_id = ? AND channel_id = ? AND message_id = ? AND emoji = ?',
        (str(guild_id), str(channel_id), str(message_id), emoji)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def _add_reaction_role(guild_id: int, channel_id: int, message_id: int, emoji: str, role_id: int):
    """Fügt eine neue Reaction-Role hinzu."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO reaction_roles (guild_id, channel_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?, ?)',
        (str(guild_id), str(channel_id), str(message_id), emoji, str(role_id))
    )
    conn.commit()
    conn.close()


def _remove_reaction_role(guild_id: int, channel_id: int, message_id: int, emoji: str):
    """Entfernt eine Reaction-Role."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'DELETE FROM reaction_roles WHERE guild_id = ? AND channel_id = ? AND message_id = ? AND emoji = ?',
        (str(guild_id), str(channel_id), str(message_id), emoji)
    )
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


class ReactionRolesCog(commands.Cog):
    """Reaction Roles: Reaktionen auf Nachrichten zuweisen und Rollen vergeben."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Fügt beim Start alle gespeicherten Reaktionen zu den Nachrichten hinzu."""
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT DISTINCT guild_id, channel_id, message_id, emoji FROM reaction_roles'
            )
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                guild = self.bot.get_guild(int(row['guild_id']))
                if not guild:
                    continue
                channel = guild.get_channel(int(row['channel_id']))
                if not channel:
                    continue
                try:
                    message = await channel.fetch_message(int(row['message_id']))
                    emoji = _parse_emoji(row['emoji'])
                    await message.add_reaction(emoji)
                except discord.NotFound:
                    logger.warning(f'Reaction-Role-Nachricht nicht gefunden: {row["message_id"]}')
                except discord.HTTPException as e:
                    logger.warning(f'Reaktion hinzufügen fehlgeschlagen: {e}')
        except Exception as e:
            logger.error(f'Reaction-Roles beim Start fehlgeschlagen: {e}')

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Weist eine Rolle zu wenn ein User reagiert."""
        if payload.member.bot:
            return

        emoji = str(payload.emoji)
        rr = _get_reaction_role(payload.guild_id, payload.channel_id, payload.message_id, emoji)
        if not rr:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        role = guild.get_role(int(rr['role_id']))
        if not role:
            return

        try:
            await payload.member.add_roles(role, reason='Reaction-Role')
        except discord.HTTPException as e:
            logger.warning(f'Reaction-Role Rollenvergabe fehlgeschlagen: {e}')

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Entfernt eine Rolle wenn ein User die Reaktion entfernt."""
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        emoji = str(payload.emoji)
        rr = _get_reaction_role(payload.guild_id, payload.channel_id, payload.message_id, emoji)
        if not rr:
            return

        role = guild.get_role(int(rr['role_id']))
        if not role:
            return

        try:
            await member.remove_roles(role, reason='Reaction-Role entfernt')
        except discord.HTTPException as e:
            logger.warning(f'Reaction-Role Rollenentfernung fehlgeschlagen: {e}')

    reactionroles_group = app_commands.Group(
        name='reactionroles', description='Reaction Roles verwalten'
    )

    @reactionroles_group.command(name='create', description='Erstelle eine neue Reaction-Role')
    @app_commands.describe(
        kanal='Der Kanal der Nachricht',
        nachricht_id='Die ID der Nachricht',
        emoji='Der Emoji der Reaktion (z.B. 👍 oder custom:123456)',
        rolle='Die Rolle die vergeben werden soll',
    )
    @app_commands.default_permissions(administrator=True)
    async def cmd_reactionroles_create(
        self,
        interaction: discord.Interaction,
        kanal: discord.TextChannel,
        nachricht_id: str,
        emoji: str,
        rolle: discord.Role,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                'Nur Admins können Reaction Roles erstellen.', ephemeral=True
            )
            return

        try:
            message_id = int(nachricht_id)
        except ValueError:
            await interaction.response.send_message(
                'Ungültige Nachrichten-ID.', ephemeral=True
            )
            return

        try:
            message = await kanal.fetch_message(message_id)
        except discord.NotFound:
            await interaction.response.send_message(
                'Nachricht nicht gefunden.', ephemeral=True
            )
            return
        except discord.HTTPException:
            await interaction.response.send_message(
                'Nachricht konnte nicht abgerufen werden.', ephemeral=True
            )
            return

        emoji_parsed = _parse_emoji(emoji)
        if emoji_parsed is None:
            await interaction.response.send_message(
                'Ungültiger Emoji.', ephemeral=True
            )
            return

        existing = _get_reaction_role(
            interaction.guild_id, kanal.id, message_id, str(emoji_parsed)
        )
        if existing:
            await interaction.response.send_message(
                'Diese Reaction-Role existiert bereits.', ephemeral=True
            )
            return

        try:
            await message.add_reaction(emoji_parsed)
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f'Reaktion konnte nicht hinzugefügt werden: {e}', ephemeral=True
            )
            return

        _add_reaction_role(
            interaction.guild_id, kanal.id, message_id, str(emoji_parsed), rolle.id
        )

        embed = discord.Embed(
            title='Reaction-Role erstellt',
            description=(
                f'**Emoji:** {emoji}\n'
                f'**Rolle:** {rolle.mention}\n'
                f'**Nachricht:** [Link](https://discord.com/channels/{interaction.guild_id}/{kanal.id}/{message_id})'
            ),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reactionroles_group.command(name='remove', description='Entferne eine Reaction-Role')
    @app_commands.describe(
        kanal='Der Kanal der Nachricht',
        nachricht_id='Die ID der Nachricht',
        emoji='Der Emoji der Reaktion',
    )
    @app_commands.default_permissions(administrator=True)
    async def cmd_reactionroles_remove(
        self,
        interaction: discord.Interaction,
        kanal: discord.TextChannel,
        nachricht_id: str,
        emoji: str,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                'Nur Admins können Reaction Roles entfernen.', ephemeral=True
            )
            return

        try:
            message_id = int(nachricht_id)
        except ValueError:
            await interaction.response.send_message(
                'Ungültige Nachrichten-ID.', ephemeral=True
            )
            return

        emoji_parsed = _parse_emoji(emoji)
        if emoji_parsed is None:
            await interaction.response.send_message(
                'Ungültiger Emoji.', ephemeral=True
            )
            return

        removed = _remove_reaction_role(
            interaction.guild_id, kanal.id, message_id, str(emoji_parsed)
        )
        if not removed:
            await interaction.response.send_message(
                'Keine passende Reaction-Role gefunden.', ephemeral=True
            )
            return

        try:
            message = await kanal.fetch_message(message_id)
            await message.remove_reaction(emoji_parsed, self.bot.user)
        except (discord.NotFound, discord.HTTPException):
            pass

        embed = discord.Embed(
            title='Reaction-Role entfernt',
            description=f'**Emoji:** {emoji}',
            color=discord.Color.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @reactionroles_group.command(name='list', description='Zeige alle Reaction-Roles dieses Servers')
    @app_commands.default_permissions(administrator=True)
    async def cmd_reactionroles_list(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                'Nur Admins können die Liste anzeigen.', ephemeral=True
            )
            return

        rows = _get_reaction_roles(interaction.guild_id)
        if not rows:
            embed = discord.Embed(
                title='Reaction-Roles',
                description='Es sind keine Reaction-Roles konfiguriert.',
                color=discord.Color.greyple(),
            )
            await interaction.response.send_message(embed=embed)
            return

        lines = []
        for rr in rows:
            emoji = rr['emoji']
            role = interaction.guild.get_role(int(rr['role_id']))
            role_name = role.mention if role else f'Unbekannt ({rr["role_id"]})'
            link = f'https://discord.com/channels/{rr["guild_id"]}/{rr["channel_id"]}/{rr["message_id"]}'
            lines.append(f'{emoji} → {role_name} [Nachricht]({link})')

        embed = discord.Embed(
            title=f'Reaction-Roles ({len(rows)})',
            description='\n'.join(lines),
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(ReactionRolesCog(bot))
