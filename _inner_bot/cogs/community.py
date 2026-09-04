"""Community: Level, Leaderboard, Poll, Reminder, Help."""
import re as _re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.config import WEBAPP_URL
from core.db import get_db, _get_xp, _get_leaderboard, _xp_for_level, save_reminder, get_user_reminders, cancel_reminder
from core.badwords import find_bad_word
from core.images import make_rank_card_async


class CommunityCog(commands.Cog):
    """XP-Level, Leaderboard, Umfragen und Erinnerungen."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.guild_only()
    @app_commands.command(name='level', description='Zeige dein Level und XP')
    @app_commands.describe(user='User zum Prüfen (optional)')
    async def cmd_level(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        data = _get_xp(str(target.id), str(interaction.guild_id))
        if not data:
            embed = discord.Embed(
                title=f'{target.display_name}',
                description='Noch keine XP gesammelt. Schreib etwas um XP zu verdienen!',
                color=discord.Color.greyple()
            )
            await interaction.response.send_message(embed=embed)
            return

        level = data['level']
        xp = data['xp']
        messages = data['messages']
        needed = _xp_for_level(level)
        progress = min(xp / needed, 1.0)
        bar_len = 20
        filled = int(bar_len * progress)
        bar = '█' * filled + '░' * (bar_len - filled)

        # Platzierung im Leaderboard berechnen
        rank = 1
        try:
            rows = _get_leaderboard(str(interaction.guild_id), limit=10000)
            sorted_rows = sorted(rows, key=lambda r: (r['level'], r['xp']), reverse=True)
            for i, row in enumerate(sorted_rows):
                if str(row['user_id']) == str(target.id):
                    rank = i + 1
                    break
        except Exception:
            pass

        embed = discord.Embed(
            title=f'📊 {target.display_name}',
            color=discord.Color.blurple()
        )
        embed.add_field(name='Level', value=f'**{level}**', inline=True)
        embed.add_field(name='XP', value=f'{xp}/{needed}', inline=True)
        embed.add_field(name='Nachrichten', value=str(messages), inline=True)
        embed.add_field(name='Platzierung', value=f'#{rank}', inline=True)
        embed.add_field(name='Fortschritt', value=f'`{bar}` {progress:.0%}', inline=False)
        embed.set_thumbnail(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

        card = await make_rank_card_async(target, level, xp, needed, rank, len(interaction.guild.members))
        if card:
            await interaction.followup.send(file=discord.File(card, filename='rank.png'))

    @app_commands.command(name='poll', description='Erstelle eine Umfrage')
    @app_commands.describe(
        frage='Die Umfrage-Frage',
        option1='Option 1',
        option2='Option 2',
        option3='Option 3 (optional)',
        option4='Option 4 (optional)'
    )
    async def cmd_poll(
        self,
        interaction: discord.Interaction,
        frage: str,
        option1: str,
        option2: str,
        option3: str = None,
        option4: str = None
    ):
        options = [option1, option2]
        if option3:
            options.append(option3)
        if option4:
            options.append(option4)

        numbers = ['1️⃣', '2️⃣', '3️⃣', '4️⃣']
        desc_lines = []
        for i, opt in enumerate(options):
            desc_lines.append(f'{numbers[i]} {opt}')

        embed = discord.Embed(
            title=f'📊 {frage}',
            description='\n'.join(desc_lines),
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f'Umfrage von {interaction.user.display_name}')

        await interaction.response.send_message(embed=embed)
        msg = await interaction.original_response()
        for i in range(len(options)):
            await msg.add_reaction(numbers[i])

    @app_commands.command(name='remind', description='Erhalte eine Erinnerung per DM')
    @app_commands.describe(
        zeit='Wann? (z.B. "5min", "30min", "1h", "2h")',
        text='Woran soll ich dich erinnern?'
    )
    async def cmd_remind(self, interaction: discord.Interaction, zeit: str, text: str):
        user_id = str(interaction.user.id)
        channel_id = str(interaction.channel_id)

        # Bad-Wort-Filter auf den Erinnerungstext
        if find_bad_word(text):
            await interaction.response.send_message(
                '🚫 Der Erinnerungstext enthält unangemessene Sprache und wurde abgelehnt.',
                ephemeral=True
            )
            return

        # Zeit parsen
        match = _re.match(r'^(\d+)\s*(min|m|h|stunden|sek|s)$', zeit.lower().strip())
        if not match:
            embed = discord.Embed(title='Ungültiges Format', description='Nutze z.B. `5min`, `30min`, `1h`, `2h`', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        amount = int(match.group(1))
        unit = match.group(2)

        if unit in ('min', 'm'):
            seconds = amount * 60
        elif unit in ('h', 'stunden'):
            seconds = amount * 3600
        elif unit in ('sek', 's'):
            seconds = amount
        else:
            seconds = amount * 60

        if seconds < 30:
            embed = discord.Embed(title='Zu kurz', description='Mindestens 30 Sekunden.', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if seconds > 86400:
            embed = discord.Embed(title='Zu lang', description='Maximal 24 Stunden.', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        remind_at = (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime('%Y-%m-%d %H:%M:%S')
        save_reminder(user_id, channel_id, remind_at, text)

        human_time = f'{amount} Minuten' if unit in ('min', 'm') else f'{amount} Stunden' if unit in ('h', 'stunden') else f'{amount} Sekunden'
        embed = discord.Embed(
            title='⏰ Erinnerung gespeichert!',
            description=f'Ich erinnere dich in **{human_time}** per DM:\n> {text}',
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='remind-list', description='Zeige deine ausstehenden Erinnerungen')
    async def cmd_remind_list(self, interaction: discord.Interaction):
        reminders = get_user_reminders(str(interaction.user.id))
        if not reminders:
            embed = discord.Embed(title='Keine Erinnerungen', description='Du hast keine ausstehenden Erinnerungen.', color=discord.Color.greyple())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        lines = []
        for r in reminders:
            lines.append(f'**#{r["id"]}** — {r["remind_at"][:16]}\n> {r["message"][:80]}')
        embed = discord.Embed(
            title=f'Deine Erinnerungen ({len(reminders)})',
            description='\n\n'.join(lines[:10]),
            color=discord.Color.blue()
        )
        embed.set_footer(text='Nutze /remind-cancel <id> zum Abbrechen')
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='remind-cancel', description='Breche eine Erinnerung ab')
    @app_commands.describe(id='ID der Erinnerung (aus /remind-list)')
    async def cmd_remind_cancel(self, interaction: discord.Interaction, id: int):
        if cancel_reminder(id, str(interaction.user.id)):
            embed = discord.Embed(title='Erinnerung abgebrochen', description=f'Erinnerung #{id} wurde geloescht.', color=discord.Color.green())
        else:
            embed = discord.Embed(title='Nicht gefunden', description=f'Erinnerung #{id} wurde nicht gefunden oder gehoert dir nicht.', color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CommunityCog(bot))
