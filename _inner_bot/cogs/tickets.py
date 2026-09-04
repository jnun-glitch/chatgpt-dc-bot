"""Tickets: /ticket Command + TicketView + Auto-Close + Stats."""
import asyncio
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands, tasks
from core.db import get_next_ticket_number, save_ticket, get_open_tickets, get_ticket_stats, close_ticket_db
from core.views import TicketView
from core.tickets import send_ticket_to_n8n_async, notify_owner_ticket, save_ticket_transcript
from core.logging import logger


KATEGORIEN = ['Bug', 'Feature Request', 'Support', 'Ban Appeal', 'Sonstiges']


class TicketCog(commands.Cog):
    """Privates Support-Ticket-System."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_close_loop.start()

    def cog_unload(self):
        self.auto_close_loop.cancel()

    @tasks.loop(hours=1)
    async def auto_close_loop(self):
        """Schließt Tickets automatisch nach 24h Inaktivität."""
        try:
            open_tickets = get_open_tickets()
            now = datetime.utcnow()
            
            for ticket in open_tickets:
                try:
                    channel_id = ticket['channel_id']
                    created_at = datetime.fromisoformat(ticket['created_at'])
                    
                    channel = self.bot.get_channel(int(channel_id))
                    if not channel:
                        close_ticket_db(channel_id)
                        continue
                    
                    last_message = None
                    async for msg in channel.history(limit=1):
                        last_message = msg
                    
                    if last_message:
                        inactive_time = now - last_message.created_at.replace(tzinfo=None)
                    else:
                        inactive_time = now - created_at
                    
                    if inactive_time >= timedelta(hours=24):
                        transcript_path = await save_ticket_transcript(channel_id, channel.guild)
                        close_ticket_db(channel_id)
                        
                        embed = discord.Embed(
                            title='Ticket automatisch geschlossen',
                            description=f'Ticket wurde nach 24h Inaktivität automatisch geschlossen.\n'
                                       f'📝 Transcript gespeichert.' if transcript_path else '',
                            color=discord.Color.greyple()
                        )
                        try:
                            await channel.send(embed=embed)
                            await asyncio.sleep(5)
                            await channel.delete(reason='Auto-close: 24h Inaktivität')
                        except Exception:
                            pass
                        
                        logger.info(f'Ticket #{ticket["ticket_number"]:04d} automatisch geschlossen (24h Inaktivität)')
                except Exception as e:
                    logger.error(f'Auto-Close Fehler für Ticket {ticket.get("ticket_number")}: {e}')
        except Exception as e:
            logger.error(f'Auto-Close Loop Fehler: {e}')

    @auto_close_loop.before_loop
    async def before_auto_close(self):
        await self.bot.wait_until_ready()

    ticket_group = app_commands.Group(name='ticket', description='Ticket-System Commands')

    @ticket_group.command(name='create', description='Erstelle ein privates Ticket für Support oder Fragen')
    @app_commands.describe(
        betreff='Worum geht es?',
        kategorie='Kategorie des Tickets'
    )
    @app_commands.choices(kategorie=[
        app_commands.Choice(name=k, value=k) for k in KATEGORIEN
    ])
    @app_commands.checks.cooldown(1, 300.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_ticket(self, interaction: discord.Interaction, betreff: str = 'Kein Betreff', kategorie: str = 'Sonstiges'):
        ticket_number = get_next_ticket_number()

        guild = interaction.guild
        user = interaction.user

        admin_role = discord.utils.get(guild.roles, name='Admin')
        mod_role = discord.utils.get(guild.roles, name='Moderator')
        support_role = discord.utils.get(guild.roles, name='Support')

        ticket_cat = discord.utils.get(guild.categories, name='Tickets')
        if not ticket_cat:
            try:
                ticket_cat = await guild.create_category('Tickets', overwrites={
                    guild.default_role: discord.PermissionOverwrite(read_messages=False),
                    guild.me: discord.PermissionOverwrite(read_messages=True, manage_channels=True),
                })
                logger.info('Tickets-Kategorie erstellt')
            except Exception as e:
                logger.warning(f'Tickets-Kategorie konnte nicht erstellt werden: {e}')

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_messages=True),
        }
        if admin_role:
            overwrites[admin_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if mod_role:
            overwrites[mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        channel_name = f'ticket-{user.name}-{ticket_number:04d}'
        try:
            channel = await guild.create_text_channel(
                channel_name,
                category=ticket_cat,
                topic=f'Ticket von {user} | {betreff} | Kategorie: {kategorie}',
                overwrites=overwrites,
                reason=f'Ticket #{ticket_number} by {user}'
            )
        except discord.Forbidden:
            embed = discord.Embed(
                title='Fehler',
                description='Keine Berechtigung um Channel zu erstellen.',
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await asyncio.sleep(0.5)

        save_ticket(ticket_number, str(channel.id), str(user.id), user.display_name, betreff, kategorie)

        support_mention = support_role.mention if support_role else '@Admin'

        welcome = discord.Embed(
            title=f'Ticket #{ticket_number:04d}',
            description=(
                f'Hallo {user.mention}! {support_role.mention if support_role else ""}\n\n'
                f'**Betreff:** {betreff}\n'
                f'**Kategorie:** {kategorie}\n\n'
                f'Schreib hier deine Frage oder dein Problem rein. '
                f'Ein Member des Support-Teams wird sich bei dir melden.\n\n'
                f'**Buttons:** 🔍 AI-Analyse | ✅ Als gelöst | 🔒 Schließen'
            ),
            color=discord.Color.blurple()
        )
        welcome.set_footer(text=f'Ticket Channel: {channel.name}')

        view = TicketView(channel.id, ticket_number)
        await channel.send(embed=welcome, view=view)

        embed = discord.Embed(
            title='Ticket erstellt',
            description=(
                f'Dein Ticket wurde erstellt: {channel.mention}\n\n'
                f'**Betreff:** {betreff}\n'
                f'**Kategorie:** {kategorie}\n'
                f'{support_role.name if support_role else "Admin"} wurden benachrichtigt.\n'
                f'🔍 AI-Analyse prüft dein Ticket automatisch.'
            ),
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(f'Ticket #{ticket_number:04d} created by {user} in guild {guild.name}')

        await send_ticket_to_n8n_async(ticket_number, str(channel.id), str(user.id), user.display_name, betreff, betreff)
        await notify_owner_ticket(guild, ticket_number, channel.id, betreff)

    @ticket_group.command(name='stats', description='Zeigt Statistiken über alle Tickets')
    @app_commands.checks.cooldown(1, 60.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_ticket_stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        stats = get_ticket_stats()
        
        categories_text = '\n'.join([f'  {k}: **{v}**' for k, v in stats['categories'].items()]) if stats['categories'] else '  Keine Daten'
        
        embed = discord.Embed(
            title='📊 Ticket Statistiken',
            color=discord.Color.blue()
        )
        embed.add_field(name='Gesamt', value=str(stats['total']), inline=True)
        embed.add_field(name='Offen', value=str(stats['open']), inline=True)
        embed.add_field(name='Geschlossen', value=str(stats['closed']), inline=True)
        embed.add_field(
            name='Ø Schließzeit', 
            value=f'{stats["avg_close_hours"]} Stunden' if stats['avg_close_hours'] > 0 else 'Keine Daten',
            inline=True
        )
        embed.add_field(name='Nach Kategorien', value=categories_text, inline=False)
        
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketCog(bot))
