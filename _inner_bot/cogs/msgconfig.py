"""Message Config: Alle Bot-Nachrichten über Discord anpassbar."""
import discord
from discord import app_commands
from discord.ext import commands

from core.db import get_msg, set_msg, del_msg, get_all_msgs, MESSAGE_DEFAULTS

# Kategorien für /msgconfig
_CATEGORIES = {
    'welcome': {
        'label': 'Willkommen',
        'keys': ['welcome_title', 'welcome_desc', 'welcome_card_title',
                 'welcome_card_sub', 'welcome_card_footer', 'welcome_roles_msg'],
    },
    'moderation': {
        'label': 'Moderation',
        'keys': ['spam_msg', 'badword_msg', 'no_perm_msg', 'error_msg',
                 'cooldown_msg', 'bot_missing_perm_msg'],
    },
    'community': {
        'label': 'Community',
        'keys': ['levelup_msg', 'levelup_role_msg'],
    },
    'verify': {
        'label': 'Verifizierung',
        'keys': ['verify_msg', 'verify_desc'],
    },
    'tickets': {
        'label': 'Tickets',
        'keys': ['ticket_welcome', 'ticket_close', 'ticket_resolve'],
    },
    'autoresponse': {
        'label': 'Auto-Responses',
        'keys': ['autoresponse_hallo', 'autoresponse_danke', 'autoresponse_hilfe',
                 'autoresponse_wie_geht', 'autoresponse_was_ist'],
    },
}


class MsgConfig(commands.Cog):
    """Alle Bot-Nachrichten über Discord anpassbar."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    msgconfig = app_commands.Group(
        name='msgconfig',
        description='Bot-Nachrichten anpassen',
    )

    @msgconfig.command(name='list', description='Zeigt alle konfigurierbaren Nachrichten')
    @app_commands.describe(kategorie='Nachrichten-Kategorie (optional)')
    @app_commands.choices(kategorie=[
        app_commands.Choice(name='Alle', value='all'),
        app_commands.Choice(name='Willkommen', value='welcome'),
        app_commands.Choice(name='Moderation', value='moderation'),
        app_commands.Choice(name='Community', value='community'),
        app_commands.Choice(name='Verifizierung', value='verify'),
        app_commands.Choice(name='Tickets', value='tickets'),
        app_commands.Choice(name='Auto-Responses', value='autoresponse'),
    ])
    async def cmd_list(self, interaction: discord.Interaction, kategorie: str = 'all'):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message('⛔ Nur Admins.', ephemeral=True)

        guild_id = interaction.guild_id
        all_msgs = get_all_msgs(guild_id)

        if kategorie != 'all' and kategorie in _CATEGORIES:
            cat = _CATEGORIES[kategorie]
            keys = cat['keys']
            title = cat['label']
        else:
            keys = list(MESSAGE_DEFAULTS.keys())
            title = 'Alle'

        embed = discord.Embed(
            title=f'📝 Nachrichten — {title}',
            color=discord.Color.blurple()
        )

        for key in keys:
            val = all_msgs.get(key, '')
            default = MESSAGE_DEFAULTS.get(key, '')
            is_custom = val != default
            status = '✏️' if is_custom else '📌'
            preview = val[:80] + ('...' if len(val) > 80 else '')
            embed.add_field(
                name=f'{status} `{key}`',
                value=f'```{preview}```',
                inline=False
            )

        embed.set_footer(text='✏️ = angepasst | 📌 = Standard | /msgconfig set <key> <text>')
        await interaction.response.send_message(embed=embed)

    @msgconfig.command(name='set', description='Setzt eine Nachricht')
    @app_commands.describe(
        key='Nachricht-Key (aus /msgconfig list)',
        text='Neuer Text (Platzhalter: {name}, {mention}, {server}, {level}, {role}, {count}, {channel}, {number}, {subject}, {category}, {mod}, {seconds})'
    )
    async def cmd_set(self, interaction: discord.Interaction, key: str, text: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message('⛔ Nur Admins.', ephemeral=True)

        if key not in MESSAGE_DEFAULTS:
            available = ', '.join(sorted(MESSAGE_DEFAULTS.keys()))
            return await interaction.response.send_message(
                f'❌ Unbekannter Key `{key}`.\nVerfügbare Keys:\n`{available}`',
                ephemeral=True
            )

        set_msg(interaction.guild_id, key, text)
        preview = text.format(
            name='Max', mention='@User', server='MeinServer',
            level='5', role='Member', count='42',
            channel='#regeln', number='001',
            subject='Hilfe', category='Support', mod='Admin',
            seconds='30'
        )[:200]
        embed = discord.Embed(
            title='✅ Nachricht aktualisiert',
            description=f'**Key:** `{key}`\n**Neuer Text:**\n```{text}```\n**Vorschau:**\n{preview}',
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @msgconfig.command(name='get', description='Zeigt eine einzelne Nachricht')
    @app_commands.describe(key='Nachricht-Key')
    async def cmd_get(self, interaction: discord.Interaction, key: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message('⛔ Nur Admins.', ephemeral=True)

        if key not in MESSAGE_DEFAULTS:
            return await interaction.response.send_message(f'❌ Unbekannter Key `{key}`.', ephemeral=True)

        val = get_msg(interaction.guild_id, key)
        default = MESSAGE_DEFAULTS.get(key, '')
        is_custom = val != default

        embed = discord.Embed(
            title=f'{"✏️" if is_custom else "📌"} `{key}`',
            description=f'```{val}```',
            color=discord.Color.blurple() if is_custom else discord.Color.greyple()
        )
        if is_custom:
            embed.add_field(name='Standard', value=f'```{default}````', inline=False)
            embed.set_footer(text='/msgconfig reset <key> um auf Standard zurückzusetzen')
        await interaction.response.send_message(embed=embed)

    @msgconfig.command(name='reset', description='Setzt eine Nachricht auf den Standard zurück')
    @app_commands.describe(key='Nachricht-Key')
    async def cmd_reset(self, interaction: discord.Interaction, key: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message('⛔ Nur Admins.', ephemeral=True)

        if key not in MESSAGE_DEFAULTS:
            return await interaction.response.send_message(f'❌ Unbekannter Key `{key}`.', ephemeral=True)

        del_msg(interaction.guild_id, key)
        embed = discord.Embed(
            title='✅ Zurückgesetzt',
            description=f'`{key}` wurde auf den Standard zurückgesetzt:\n```{MESSAGE_DEFAULTS[key]}```',
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @msgconfig.command(name='resetall', description='Setzt ALLE Nachrichten auf Standard zurück')
    async def cmd_resetall(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message('⛔ Nur Admins.', ephemeral=True)

        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM message_config WHERE guild_id = ?', (str(interaction.guild_id),))
        conn.commit()
        conn.close()

        embed = discord.Embed(
            title='✅ Alle zurückgesetzt',
            description=f'**{len(MESSAGE_DEFAULTS)}** Nachrichten wurden auf Standard zurückgesetzt.',
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=embed)

    @msgconfig.command(name='preview', description='Zeigt eine Vorschau der Nachricht mit Platzhaltern')
    @app_commands.describe(key='Nachricht-Key')
    async def cmd_preview(self, interaction: discord.Interaction, key: str):
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message('⛔ Nur Admins.', ephemeral=True)

        if key not in MESSAGE_DEFAULTS:
            return await interaction.response.send_message(f'❌ Unbekannter Key `{key}`.', ephemeral=True)

        val = get_msg(interaction.guild_id, key)
        preview = val.format(
            name=interaction.user.display_name,
            mention=interaction.user.mention,
            server=interaction.guild.name,
            level='5',
            role='Scratcher',
            count=str(interaction.guild.member_count or 0),
            channel='#regeln',
            number='001',
            subject='Hilfe',
            category='Support',
            mod=interaction.user.display_name,
            seconds='30'
        )

        embed = discord.Embed(
            title=f'👁️ Vorschau: `{key}`',
            description=preview,
            color=discord.Color.blurple()
        )
        embed.set_footer(text='Platzhalter: {name} {mention} {server} {level} {role} {count} {channel}')
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(MsgConfig(bot))
