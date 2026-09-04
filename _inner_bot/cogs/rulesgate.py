"""Rules Gate: Neue User sehen nur den Regeln-Kanal, bis sie die Regeln akzeptieren."""
import discord
from discord import app_commands
from discord.ext import commands
from core.db import get_rules_gate, set_rules_gate
from core.roles import apply_channel_permissions
from core.views import RulesGateView
from core.channelnames import styled_text_name, find_channel
from core.logging import logger

RULES_TEXT = (
    '1. **Sei respektvoll** – Beleidigungen und Mobbing haben hier keinen Platz.\n'
    '2. **Kein Spam** – Keine Werbung, keine Massennachrichten.\n'
    '3. **Kein Griefing/Cheaten** – Griefing, Hack-Client und Duping sind verboten.\n'
    '4. **Keine unangemessenen Inhalte** – Kein NSFW, keine Doxxing.\n'
    '5. **Kein Rassismus/Sexismus** – Null Toleranz.\n'
    '6. **Moderatoren folgen** – Anweisungen von Staff sind bindend.\n'
    '7. **Deutsch/Englisch** – Bitte in einer verständlichen Sprache schreiben.\n'
    '8. **Vernünftig mit Voice umgehen** – Keine Schreianfälle oder Ear-Rape.\n\n'
    '**Konsequenzen:** Verwarnung → Timeout → Kick → Ban (je nach Schwere).'
)


class RulesGateCog(commands.Cog):
    """Rules Gate: Regeln akzeptieren → Member-Rolle → Kanäle sichtbar."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _require_admin(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message('Nur Admins können das Rules Gate verwalten.', ephemeral=True)
            return False
        return True

    @app_commands.command(name='rules-gate', description='Rules Gate: Neue User müssen Regeln akzeptieren, bevor sie schreiben können')
    @app_commands.describe(
        aktion='Aktion: setup (aktivieren) oder disable (deaktivieren)',
        kanal='Kanal mit den Regeln (Standard: #regeln)',
    )
    @app_commands.choices(aktion=[
        app_commands.Choice(name='🔒 Setup (aktivieren)', value='setup'),
        app_commands.Choice(name='🔓 Disable (deaktivieren)', value='disable'),
        app_commands.Choice(name='ℹ️ Status', value='status'),
    ])
    @app_commands.default_permissions(administrator=True)
    async def cmd_rules_gate(self, interaction: discord.Interaction,
                             aktion: app_commands.Choice[str],
                             kanal: discord.TextChannel = None):
        if not await self._require_admin(interaction):
            return
        if aktion.value == 'status':
            await self._status(interaction)
            return
        if aktion.value == 'disable':
            await self._disable(interaction)
            return
        await self._setup(interaction, kanal)

    async def _status(self, interaction: discord.Interaction):
        gate = get_rules_gate(interaction.guild_id)
        if not gate or not gate.get('enabled'):
            await interaction.response.send_message(
                embed=discord.Embed(title='⚙️ Rules Gate', description='Das Rules Gate ist **deaktiviert**.', color=discord.Color.greyple()),
                ephemeral=True
            )
            return
        ch = interaction.guild.get_channel(int(gate['rules_channel_id'])) if gate.get('rules_channel_id') else None
        role = interaction.guild.get_role(int(gate['member_role_id'])) if gate.get('member_role_id') else None
        embed = discord.Embed(title='⚙️ Rules Gate', description='Das Rules Gate ist **aktiv**.', color=discord.Color.green())
        embed.add_field(name='Regeln-Kanal', value=ch.mention if ch else 'Unbekannt', inline=True)
        embed.add_field(name='Member-Rolle', value=role.mention if role else 'Member', inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def _disable(self, interaction: discord.Interaction):
        set_rules_gate(interaction.guild_id, enabled=False)
        await interaction.response.defer(ephemeral=True)
        try:
            changed = await apply_channel_permissions(interaction.guild)
            embed = discord.Embed(
                title='🔓 Rules Gate deaktiviert',
                description=f'Berechtigungen zurückgesetzt ({len(changed)} Kanäle). Alle sehen wieder alle Kanäle.',
                color=discord.Color.green()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as e:
            logger.warning(f'Rules Gate disable: Berechtigungen fehlgeschlagen: {e}')
            await interaction.followup.send('Rules Gate deaktiviert, aber Berechtigungen konnten nicht zurückgesetzt werden.', ephemeral=True)

    async def _setup(self, interaction: discord.Interaction, kanal: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        result = await setup_rules_gate(interaction.guild, kanal)
        if not result['ok']:
            await interaction.followup.send(result['error'], ephemeral=True)
            return
        embed = discord.Embed(
            title='🔒 Rules Gate aktiviert',
            description=(
                f'Neue User sehen nur noch **{result["rules_ch"].mention}**.\n'
                f'Wer dort **"Regeln akzeptieren"** klickt, bekommt die Rolle **{result["member_role"].mention}** '
                f'und sieht alle Kanäle.\n'
                f'Bis dahin werden Nachrichten außerhalb des Regeln-Kanals automatisch gelöscht.'
            ),
            color=discord.Color.green()
        )
        if result['changed']:
            embed.add_field(name='Berechtigungen', value=f'{len(result["changed"])} Kanäle gesperrt', inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        logger.info(f'Rules Gate aktiviert in {interaction.guild.name} (Kanal {result["rules_ch"].name})')


async def setup_rules_gate(guild, kanal: discord.TextChannel = None) -> dict:
    """Aktiviert das Rules Gate für einen Server (wiederverwendet von /rules-gate und /setup-smp).
    Liefert {'ok', 'rules_ch', 'member_role', 'changed', 'error'}."""
    # Regeln-Kanal bestimmen (Standard: #regeln, sonst erstellen)
    rules_ch = kanal or find_channel(guild, 'regeln')
    if rules_ch is None:
        info_cat = discord.utils.get(guild.categories, name='INFORMATIONEN')
        try:
            rules_ch = await guild.create_text_channel(
                styled_text_name('regeln'),
                category=info_cat,
                topic='Serverregeln – bitte akzeptieren, bevor du schreibst',
            )
        except Exception as e:
            return {'ok': False, 'error': f'Regeln-Kanal konnte nicht erstellt werden: {e}'}

    # Member-Rolle bestimmen
    member_role = discord.utils.get(guild.roles, name='Member')
    if member_role is None:
        try:
            member_role = await guild.create_role(name='Member', reason='Rules Gate: Member-Rolle')
        except Exception as e:
            return {'ok': False, 'error': f'Member-Rolle konnte nicht erstellt werden: {e}'}

    # Regeln-Nachricht posten (falls noch keine Rules-Gate-Nachricht da ist)
    gate = get_rules_gate(guild.id)
    msg = None
    if gate.get('rules_message_id'):
        try:
            msg = await rules_ch.fetch_message(int(gate['rules_message_id']))
        except Exception:
            msg = None
    if msg is None:
        embed = discord.Embed(
            title='📜 Serverregeln',
            description=RULES_TEXT,
            color=discord.Color.orange()
        )
        embed.set_footer(text='Akzeptiere die Regeln unten, um die Member-Rolle zu erhalten.')
        try:
            msg = await rules_ch.send(embed=embed, view=RulesGateView())
        except Exception as e:
            return {'ok': False, 'error': f'Regeln-Nachricht konnte nicht gesendet werden: {e}'}

    set_rules_gate(guild.id, enabled=True, rules_channel_id=rules_ch.id, rules_message_id=msg.id, member_role_id=member_role.id)

    # Selbst-Heilung: Bot-Rolle über die Member-Rolle (sonst 403 bei Rollenvergabe)
    try:
        from core.roles import ensure_bot_role_hierarchy
        await ensure_bot_role_hierarchy(guild)
    except Exception:
        pass

    # Berechtigungen anwenden: @everyone sieht nur noch den Regeln-Kanal
    try:
        changed = await apply_channel_permissions(guild)
    except Exception as e:
        logger.warning(f'Rules Gate setup: Berechtigungen fehlgeschlagen: {e}')
        changed = []

    return {'ok': True, 'rules_ch': rules_ch, 'member_role': member_role, 'changed': changed}


async def setup(bot: commands.Bot):
    await bot.add_cog(RulesGateCog(bot))
