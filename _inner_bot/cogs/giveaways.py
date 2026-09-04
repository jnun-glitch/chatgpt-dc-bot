"""Giveaways: Gewinnspiele mit persistentem Button und automatischem Timer."""
import random
import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.db import get_db
from core.logging import logger


class GiveawayJoinButton(discord.ui.Button):
    """Button zum Teilnehmen an einem Gewinnspiel."""

    def __init__(self, giveaway_id: int):
        super().__init__(
            label='Teilnehmen',
            style=discord.ButtonStyle.success,
            emoji='🎉',
            custom_id=f'giveaway_join_{giveaway_id}',
        )
        self.giveaway_id = giveaway_id

    async def callback(self, interaction: discord.Interaction):
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute(
            'SELECT id, ended FROM giveaways WHERE id = ?', (self.giveaway_id,)
        )
        giveaway = cursor.fetchone()
        if not giveaway or giveaway['ended']:
            await interaction.response.send_message(
                'Dieses Gewinnspiel ist bereits beendet.', ephemeral=True
            )
            conn.close()
            return

        user_id = str(interaction.user.id)
        cursor.execute(
            'SELECT 1 FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?',
            (self.giveaway_id, user_id),
        )
        already_joined = cursor.fetchone()

        if already_joined:
            cursor.execute(
                'DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?',
                (self.giveaway_id, user_id),
            )
            cursor.execute(
                'SELECT COUNT(*) as cnt FROM giveaway_entries WHERE giveaway_id = ?',
                (self.giveaway_id,),
            )
            count = cursor.fetchone()['cnt']
            conn.commit()
            conn.close()

            view = GiveawayView(self.giveaway_id, count)
            await interaction.response.edit_message(view=view)
            await interaction.followup.send(
                'Du hast das Gewinnspiel **verlassen**.', ephemeral=True
            )
        else:
            try:
                cursor.execute(
                    'INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)',
                    (self.giveaway_id, user_id),
                )
            except sqlite3.IntegrityError:
                # Doppelklick/doppelte View: Eintrag existiert bereits – kein Fehler,
                # wird wie ein erneuter Klick als "Teilnahme bestätigt" behandelt.
                pass
            cursor.execute(
                'SELECT COUNT(*) as cnt FROM giveaway_entries WHERE giveaway_id = ?',
                (self.giveaway_id,),
            )
            count = cursor.fetchone()['cnt']
            conn.commit()
            conn.close()

            view = GiveawayView(self.giveaway_id, count)
            await interaction.response.edit_message(view=view)
            await interaction.followup.send(
                'Du nimmst am Gewinnspiel **teil**! 🎉', ephemeral=True
            )


class GiveawayView(discord.ui.View):
    """Persistente View für ein aktives Gewinnspiel."""

    def __init__(self, giveaway_id: int, participant_count: int = 0):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        btn = GiveawayJoinButton(giveaway_id)
        btn.label = f'Teilnehmen ({participant_count})'
        self.add_item(btn)


def _get_giveaway(giveaway_id: int):
    """Holt ein Gewinnspiel aus der DB."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM giveaways WHERE id = ?', (giveaway_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def _get_participant_count(giveaway_id: int) -> int:
    """Liefert die Anzahl der Teilnehmer."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT COUNT(*) as cnt FROM giveaway_entries WHERE giveaway_id = ?',
        (giveaway_id,),
    )
    count = cursor.fetchone()['cnt']
    conn.close()
    return count


def _get_participants(giveaway_id: int) -> list[str]:
    """Liefert alle Teilnehmer-IDs als Liste."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?', (giveaway_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [row['user_id'] for row in rows]


async def _end_giveaway(bot: commands.Bot, giveaway_id: int):
    """Beendet ein Gewinnspiel und kündigt den Gewinner an."""
    giveaway = _get_giveaway(giveaway_id)
    if not giveaway or giveaway['ended']:
        return

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE giveaways SET ended = TRUE WHERE id = ?', (giveaway_id,)
    )
    conn.commit()
    conn.close()

    participants = _get_participants(giveaway_id)

    guild = bot.get_guild(int(giveaway['guild_id']))
    if not guild:
        return

    channel = guild.get_channel(int(giveaway['channel_id']))
    if not channel:
        return

    try:
        message = await channel.fetch_message(int(giveaway['message_id']))
    except (discord.NotFound, discord.HTTPException):
        return

    prize = giveaway['prize']
    description = giveaway.get('description') or ''

    if not participants:
        embed = discord.Embed(
            title=f'🎉 Gewinnspiel beendet!',
            description=(
                f'**Preis:** {prize}\n'
                f'{description + chr(10) if description else ""}'
                f'\n**Teilnehmer:** 0\n\n'
                f'❌ Keine Teilnehmer – kein Gewinner.'
            ),
            color=discord.Color.greyple(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text='Gewinnspiel beendet')
        await message.edit(embed=embed, view=None)
        return

    winner_id = random.choice(participants)
    winner = guild.get_member(int(winner_id))
    winner_mention = winner.mention if winner else f'<@{winner_id}>'

    embed = discord.Embed(
        title=f'🎉 Gewinnspiel beendet!',
        description=(
            f'**Preis:** {prize}\n'
            f'{description + chr(10) if description else ""}'
            f'\n**Teilnehmer:** {len(participants)}\n\n'
            f'🏆 **Gewinner:** {winner_mention}'
        ),
        color=discord.Color.gold(),
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text='Gewinnspiel beendet')
    await message.edit(embed=embed, view=None)

    conn2 = get_db()
    cursor2 = conn2.cursor()
    cursor2.execute(
        'UPDATE giveaways SET winner_id = ? WHERE id = ?',
        (winner_id, giveaway_id),
    )
    conn2.commit()
    conn2.close()

    await channel.send(
        f'🎉 **{winner.mention if winner else winner_id}** hat **{prize}** gewonnen! '
        f'Herzlichen Glückwunsch!',
    )


class GiveawaysCog(commands.Cog):
    """Gewinnspiele mit /giveaway start, reroll und list."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._check_giveaways.start()

    def cog_unload(self):
        self._check_giveaways.cancel()

    @tasks.loop(seconds=30)
    async def _check_giveaways(self):
        """Prüft alle 30s auf abgelaufene Gewinnspiele."""
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM giveaways WHERE ended = FALSE AND end_time <= datetime('now')"
            )
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                await _end_giveaway(self.bot, row['id'])
        except Exception as e:
            logger.error(f'Giveaway-Check Fehler: {e}')

    @_check_giveaways.before_loop
    async def _before_check(self):
        await self.bot.wait_until_ready()

    giveaway_group = app_commands.Group(
        name='giveaway', description='Gewinnspiele verwalten'
    )

    @giveaway_group.command(name='start', description='Starte ein Gewinnspiel')
    @app_commands.describe(
        preis='Der Preis des Gewinnspiels',
        dauer='Dauer in Minuten (z.B. 60)',
        beschreibung='Optionale Beschreibung',
    )
    async def cmd_giveaway_start(
        self,
        interaction: discord.Interaction,
        preis: str,
        dauer: int,
        beschreibung: str = None,
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                'Nur Admins können Gewinnspiele starten.', ephemeral=True
            )
            return

        if dauer < 1 or dauer > 43200:
            await interaction.response.send_message(
                'Dauer muss zwischen 1 und 43200 Minuten (30 Tage) liegen.',
                ephemeral=True,
            )
            return

        end_time = datetime.now(timezone.utc) + timedelta(minutes=dauer)
        end_timestamp = int(end_time.timestamp())

        embed = discord.Embed(
            title=f'🎉 Gewinnspiel: {preis}',
            description=(
                f'{beschreibung + chr(10) if beschreibung else ""}'
                f'\n**Endet:** <t:{end_timestamp}:R> (<t:{end_timestamp}:f>)\n'
                f'**Gestartet von:** {interaction.user.mention}\n\n'
                f'Klicke auf den Button um teilzunehmen!'
            ),
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_footer(text=f'Dauer: {dauer} Minuten')

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            (
                'INSERT INTO giveaways '
                '(guild_id, channel_id, message_id, prize, description, host_id, end_time, ended) '
                'VALUES (?, ?, ?, ?, ?, ?, ?, FALSE)'
            ),
            (
                str(interaction.guild_id),
                str(interaction.channel_id),
                str(msg.id),
                preis,
                beschreibung or '',
                str(interaction.user.id),
                end_time.strftime('%Y-%m-%d %H:%M:%S'),
            ),
        )
        giveaway_id = cursor.lastrowid
        conn.commit()
        conn.close()

        view = GiveawayView(giveaway_id, 0)
        await msg.edit(view=view)

        logger.info(
            f'Giveaway #{giveaway_id} gestartet von {interaction.user} in {interaction.guild}'
        )

    @giveaway_group.command(name='reroll', description='Wähle einen neuen Gewinner aus')
    @app_commands.describe(id='ID des Gewinnspiels (optional, letztes wenn leer)')
    async def cmd_giveaway_reroll(
        self, interaction: discord.Interaction, id: int = None
    ):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                'Nur Admins können Gewinnspiele neu auslosen.', ephemeral=True
            )
            return

        conn = get_db()
        cursor = conn.cursor()

        if id:
            cursor.execute(
                'SELECT * FROM giveaways WHERE id = ? AND ended = TRUE', (id,)
            )
        else:
            cursor.execute(
                'SELECT * FROM giveaways WHERE guild_id = ? AND ended = TRUE ORDER BY id DESC LIMIT 1',
                (str(interaction.guild_id),),
            )
        giveaway = cursor.fetchone()
        conn.close()

        if not giveaway:
            await interaction.response.send_message(
                'Kein beendetes Gewinnspiel gefunden.', ephemeral=True
            )
            return

        giveaway = dict(giveaway)
        participants = _get_participants(giveaway['id'])

        # Bisherigen Gewinner ausschließen, damit beim Reroll eine andere Person gewinnt
        if giveaway.get('winner_id') and giveaway['winner_id'] in participants:
            participants = [p for p in participants if p != giveaway['winner_id']]

        if not participants:
            await interaction.response.send_message(
                'Keine anderen Teilnehmer für dieses Gewinnspiel.', ephemeral=True
            )
            return

        new_winner_id = random.choice(participants)
        guild = interaction.guild
        winner = guild.get_member(int(new_winner_id)) if guild else None
        winner_mention = winner.mention if winner else f'<@{new_winner_id}>'

        conn2 = get_db()
        cursor2 = conn2.cursor()
        cursor2.execute(
            'UPDATE giveaways SET winner_id = ? WHERE id = ?',
            (new_winner_id, giveaway['id']),
        )
        conn2.commit()
        conn2.close()

        embed = discord.Embed(
            title='🔄 Neuer Gewinner!',
            description=(
                f'**Preis:** {giveaway["prize"]}\n\n'
                f'🏆 **Neuer Gewinner:** {winner_mention}\n'
                f'**Teilnehmer:** {len(participants)}'
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed)

        try:
            channel = guild.get_channel(int(giveaway['channel_id']))
            if channel:
                await channel.send(
                    f'🔄 **{winner_mention}** hat **{giveaway["prize"]}** beim Reroll gewonnen! '
                    f'Herzlichen Glückwunsch!'
                )
        except Exception:
            pass

    @giveaway_group.command(
        name='list', description='Zeige alle aktiven Gewinnspiele'
    )
    async def cmd_giveaway_list(self, interaction: discord.Interaction):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT * FROM giveaways WHERE guild_id = ? AND ended = FALSE ORDER BY end_time ASC',
            (str(interaction.guild_id),),
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            embed = discord.Embed(
                title='🎉 Aktive Gewinnspiele',
                description='Es gibt derzeit keine aktiven Gewinnspiele.',
                color=discord.Color.greyple(),
            )
            await interaction.response.send_message(embed=embed)
            return

        lines = []
        for row in rows:
            g = dict(row)
            participants = _get_participant_count(g['id'])
            end_dt = datetime.strptime(g['end_time'], '%Y-%m-%d %H:%M:%S').replace(
                tzinfo=timezone.utc
            )
            end_ts = int(end_dt.timestamp())
            desc_part = f' — {g["description"][:50]}' if g.get('description') else ''
            lines.append(
                f'**#{g["id"]}** {g["prize"]}{desc_part}\n'
                f'  Teilnehmer: {participants} · Endet: <t:{end_ts}:R>\n'
                f'  [Nachricht](https://discord.com/channels/{g["guild_id"]}/{g["channel_id"]}/{g["message_id"]})'
            )

        embed = discord.Embed(
            title=f'🎉 Aktive Gewinnspiele ({len(rows)})',
            description='\n\n'.join(lines),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(GiveawaysCog(bot))
