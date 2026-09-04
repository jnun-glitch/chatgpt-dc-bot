"""Config: Server-Konfiguration mit ALLEN Einstellungen."""
import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from core.db import (
    get_guild_config, set_guild_config, add_suggestion,
    get_automod_config, set_automod_config,
    get_rules_gate, set_rules_gate,
)
from core.images import make_welcome_card


class ServerConfigCog(commands.Cog):
    """Pro-Server-Einstellungen mit ALLEN Optionen."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='config', description='Zeigt die aktuelle Server-Konfiguration')
    async def cmd_config_show(self, interaction: discord.Interaction):
        cfg = get_guild_config(interaction.guild_id)

        def ch(key):
            v = cfg.get(key)
            return f'<#{v}>' if v else 'Nicht gesetzt'

        def rl(key):
            v = cfg.get(key)
            return f'<@&{v}>' if v else 'Nicht gesetzt'

        embed = discord.Embed(title='⚙️ Server-Konfiguration', color=discord.Color.blue())

        embed.add_field(name='--- Willkommen ---', value='\u200b', inline=False)
        embed.add_field(name='Willkommens-Channel', value=ch('welcome_channel_id'), inline=True)
        embed.add_field(name='Auto-Rolle', value=rl('join_role_id'), inline=True)

        embed.add_field(name='--- Tickets ---', value='\u200b', inline=False)
        embed.add_field(name='Ticket-Kategorie', value=ch('ticket_category_id'), inline=True)

        embed.add_field(name='--- Verification ---', value='\u200b', inline=False)
        gate = get_rules_gate(interaction.guild_id)
        embed.add_field(name='Rules Gate', value='Aktiviert' if gate.get('enabled') else 'Deaktiviert', inline=True)
        embed.add_field(name='Rules-Channel', value=ch(gate.get('rules_channel_id')), inline=True)

        embed.add_field(name='--- AutoMod ---', value='\u200b', inline=False)
        automod = get_automod_config(interaction.guild_id)
        embed.add_field(name='Spam-Schutz', value='Aktiviert' if automod.get('spam', {}).get('enabled') else 'Deaktiviert', inline=True)
        embed.add_field(name='Link-Schutz', value='Aktiviert' if automod.get('links', {}).get('enabled') else 'Deaktiviert', inline=True)
        embed.add_field(name='Bad-Word-Filter', value='Aktiviert' if automod.get('badwords', {}).get('enabled') else 'Deaktiviert', inline=True)

        embed.add_field(name='--- Moderation ---', value='\u200b', inline=False)
        embed.add_field(name='Warn-Timeout ab', value=cfg.get('warn_timeout_at') or '3 (Standard)', inline=True)
        embed.add_field(name='Warn-Kick ab', value=cfg.get('warn_kick_at') or '5 (Standard)', inline=True)
        embed.add_field(name='Timeout-Dauer', value=(cfg.get('warn_timeout_minutes') or '60') + ' Min.', inline=True)

        embed.add_field(name='--- Bot ---', value='\u200b', inline=False)
        embed.add_field(name='Bot-Modus', value=cfg.get('mode', 'smp'), inline=True)

        embed.set_footer(text='/config-set <option> <wert> zum Ändern')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='config-set', description='Setzt eine Server-Einstellung')
    @app_commands.describe(option='Welche Einstellung?', wert='Wert (Kanal/Rolle mention oder ID)')
    @app_commands.choices(option=[
        app_commands.Choice(name='Willkommens-Channel', value='welcome_channel_id'),
        app_commands.Choice(name='Auto-Rolle', value='join_role_id'),
        app_commands.Choice(name='Ticket-Kategorie', value='ticket_category_id'),
        app_commands.Choice(name='Rules-Channel', value='rules_channel_id'),
        app_commands.Choice(name='Rules Gate AN', value='rules_gate_enabled_1'),
        app_commands.Choice(name='Rules Gate AUS', value='rules_gate_enabled_0'),
        app_commands.Choice(name='Spam-Schutz AN', value='automod_spam_1'),
        app_commands.Choice(name='Spam-Schutz AUS', value='automod_spam_0'),
        app_commands.Choice(name='Link-Schutz AN', value='automod_links_1'),
        app_commands.Choice(name='Link-Schutz AUS', value='automod_links_0'),
        app_commands.Choice(name='Bad-Word-Filter AN', value='automod_badwords_1'),
        app_commands.Choice(name='Bad-Word-Filter AUS', value='automod_badwords_0'),
        app_commands.Choice(name='Warn-Timeout ab (Anzahl Warns)', value='warn_timeout_at'),
        app_commands.Choice(name='Warn-Kick ab (Anzahl Warns)', value='warn_kick_at'),
        app_commands.Choice(name='Warn-Timeout Dauer (Minuten)', value='warn_timeout_minutes'),
    ])
    async def cmd_config_set(self, interaction: discord.Interaction, option: app_commands.Choice[str], wert: str = None):
        value = option.value

        # Toggle-Optionen (kein Wert nötig)
        if value.endswith('_1') or value.endswith('_0'):
            key = value.rsplit('_', 1)[0]
            enabled = value.endswith('_1')
            guild_id = interaction.guild_id
            if key == 'rules_gate_enabled':
                gate = get_rules_gate(guild_id)
                ok = set_rules_gate(
                    guild_id, enabled=enabled,
                    rules_channel_id=gate.get('rules_channel_id'),
                    rules_message_id=gate.get('rules_message_id'),
                    member_role_id=gate.get('member_role_id'),
                )
            elif key in ('automod_spam', 'automod_links', 'automod_badwords'):
                filter_name = {'automod_spam': 'spam', 'automod_links': 'links', 'automod_badwords': 'badwords'}[key]
                existing = get_automod_config(guild_id).get(filter_name, {})
                ok = set_automod_config(
                    guild_id, filter_name,
                    enabled=enabled,
                    limit_value=existing.get('limit_value', 0),
                )
            else:
                ok = set_guild_config(guild_id, key, '1' if enabled else '0')
            if ok:
                state = 'aktiviert' if enabled else 'deaktiviert'
                await interaction.response.send_message(f'✅ **{option.name}** wurde {state}.')
            else:
                await interaction.response.send_message('❌ Fehler beim Speichern.', ephemeral=True)
            return

        # Numerische Einstellungen (Warn-Schwellen)
        if value in ('warn_timeout_at', 'warn_kick_at', 'warn_timeout_minutes'):
            if not wert:
                return await interaction.response.send_message('Bitte einen Zahlenwert angeben.', ephemeral=True)
            try:
                num = int(wert)
            except ValueError:
                return await interaction.response.send_message('Ungültiger Wert. Bitte eine ganze Zahl angeben.', ephemeral=True)
            if num < 1:
                return await interaction.response.send_message('Wert muss mindestens 1 sein.', ephemeral=True)
            ok = set_guild_config(interaction.guild_id, value, str(num))
            if ok:
                await interaction.response.send_message(f'✅ **{option.name}** wurde auf **{num}** gesetzt.')
            else:
                await interaction.response.send_message('❌ Fehler beim Speichern.', ephemeral=True)
            return

        # Kanal/Rolle-Optionen
        if not wert:
            return await interaction.response.send_message('Bitte einen Wert angeben (Kanal/Rolle mention oder ID).', ephemeral=True)

        target_id = None
        if wert.startswith('<#') and wert.endswith('>'):
            target_id = wert[2:-1]
        elif wert.startswith('<@&') and wert.endswith('>'):
            target_id = wert[3:-1]
        else:
            try:
                target_id = str(int(wert))
            except ValueError:
                return await interaction.response.send_message('Ungültiger Wert. Nutze einen Kanal/Rolle mention oder die ID.', ephemeral=True)

        # Rules-Channel: geht in die rules_gate-Tabelle
        if value == 'rules_channel_id':
            gate = get_rules_gate(interaction.guild_id)
            ok = set_rules_gate(
                interaction.guild_id,
                enabled=bool(gate.get('enabled')),
                rules_channel_id=target_id,
                rules_message_id=gate.get('rules_message_id'),
                member_role_id=gate.get('member_role_id'),
            )
        else:
            ok = set_guild_config(interaction.guild_id, value, target_id)

        if ok:
            await interaction.response.send_message(f'✅ **{option.name}** wurde gesetzt.')
        else:
            await interaction.response.send_message('❌ Fehler beim Speichern.', ephemeral=True)

    @app_commands.command(name='config-reset', description='Setzt eine Einstellung zurück')
    @app_commands.describe(option='Welche Einstellung zurücksetzen?')
    @app_commands.choices(option=[
        app_commands.Choice(name='Willkommens-Channel', value='welcome_channel_id'),
        app_commands.Choice(name='Auto-Rolle', value='join_role_id'),
        app_commands.Choice(name='Ticket-Kategorie', value='ticket_category_id'),
        app_commands.Choice(name='Rules-Channel', value='rules_channel_id'),
    ])
    async def cmd_config_reset(self, interaction: discord.Interaction, option: app_commands.Choice[str]):
        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM guild_config WHERE guild_id = ? AND key = ?',
                       (str(interaction.guild_id), option.value))
        conn.commit()
        conn.close()
        await interaction.response.send_message(f'✅ **{option.name}** wurde zurückgesetzt.')

    @app_commands.command(name='suggestion', description='Schlage eine Verbesserung vor')
    @app_commands.describe(idee='Deine Idee')
    async def cmd_suggest(self, interaction: discord.Interaction, idee: str):
        if len(idee) > 1000:
            return await interaction.response.send_message('Max. 1000 Zeichen.', ephemeral=True)
        if add_suggestion(interaction.guild_id, interaction.user.id, idee):
            embed = discord.Embed(title='💡 Vorschlag', description=idee, color=discord.Color.gold())
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            msg = await interaction.response.send_message(embed=embed)
            await msg.add_reaction('✅')
            await msg.add_reaction('❌')
        else:
            await interaction.response.send_message('❌ Fehler.', ephemeral=True)

    @app_commands.command(name='welcome-preview', description='Zeigt eine Vorschau der Willkommens-Karte')
    async def cmd_welcome_preview(self, interaction: discord.Interaction):
        card = await asyncio.to_thread(make_welcome_card, interaction.user, interaction.guild.member_count, interaction.guild.name)
        if card:
            await interaction.response.send_message(file=discord.File(card, filename='welcome_preview.png'))
        else:
            await interaction.response.send_message('Bild-Generierung nicht verfügbar.', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerConfigCog(bot))
