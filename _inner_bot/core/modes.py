"""Bot-Modi pro Server + globaler Command-Check."""
import discord
from core.db import get_guild_mode, set_guild_mode
from core.logging import logger

BOT_MODES = {
    'all': {
        'label': '🔀 Alles',
        'desc': 'Alle Commands verfügbar (Standard).',
        'commands': None,
    },
    'smp': {
        'label': '⛏️ SMP',
        'desc': 'Minecraft-SMP: Kanäle, Rollen, Berechtigungen, Moderation.',
        'commands': {
            'setup-smp', 'slowmode', 'lock', 'unlock', 'permissions', 'permissions-reset',
            'role', 'role-create', 'role-delete', 'role-color', 'role-list',
            'announce', 'embed', 'serverinfo', 'userinfo', 'auditlog',
            'ban', 'unban', 'kick', 'timeout', 'untimeout', 'warn', 'warnings', 'warn-clear',
            'nick', 'nick-reset', 'purge', 'purge-user', 'deafen', 'undeafen', 'voice-kick',
            'remind', 'remind-list', 'remind-cancel', 'poll',
            'schematics', 'unpack',
            'config', 'config-set', 'config-reset',
            'msgconfig',
            'help', 'status', 'bot', 'test',
        },
    },
    'scratch-ai': {
        'label': '🤖 Scratch-AI',
        'desc': 'AI-Spiele-Generator: generate, refine, ask, verify u.a.',
        'commands': {
            'generate', 'refine', 'analyze', 'ai', 'ask', 'tip', 'suggest',
            'verify', 'verified', 'verify-link', 'verify-unlink', 'verify-check',
            'level', 'leaderboard', 'xp-reset', 'translate', 'changelog',
            'cloud-save', 'backup', 'dashboard', 'ticket',
            'train', 'train-status', 'reload',
            'help', 'status', 'bot', 'test',
        },
    },
    'moderation': {
        'label': '🛡️ Moderation',
        'desc': 'Nur Moderations-Commands.',
        'commands': {
            'ban', 'unban', 'kick', 'timeout', 'untimeout', 'warn', 'warnings', 'warn-clear',
            'nick', 'nick-reset', 'purge', 'purge-user', 'deafen', 'undeafen', 'voice-kick',
            'slowmode', 'lock', 'unlock', 'permissions', 'permissions-reset',
            'auditlog', 'serverinfo', 'userinfo', 'announce', 'embed',
            'admin-stats',
            'help', 'status', 'bot', 'test',
        },
    },
}

# Commands die IMMER erlaubt sind, egal welcher Modus
_ALWAYS_ALLOWED = {
    'help', 'status', 'bot', 'test', 'ticket', 'setup-smp',
    'level', 'remind', 'remind-list', 'remind-cancel', 'leave',
}


def _mode_allows(mode: str, command_name: str) -> bool:
    """Prüft ob ein Command im aktiven Modus erlaubt ist."""
    if mode == 'all' or mode not in BOT_MODES:
        return True
    if command_name in _ALWAYS_ALLOWED:
        return True
    allowed = BOT_MODES[mode]['commands']
    return command_name in allowed


async def _mode_check(interaction: discord.Interaction) -> bool:
    """Globaler Check: blockt Commands die im Server-Modus nicht erlaubt sind."""
    if not interaction.guild:
        return True
    if interaction.type is discord.InteractionType.autocomplete:
        return True
    mode = get_guild_mode(interaction.guild.id)
    if mode == 'all':
        return True
    cmd_name = None
    data = interaction.data or {}
    if isinstance(data, dict):
        cmd_name = data.get('name')
    if cmd_name is None:
        cmd_name = interaction.command.name if interaction.command else None
    if not cmd_name or _mode_allows(mode, cmd_name):
        return True
    if cmd_name in ('modus', 'test', 'bot-test'):
        return True
    embed = discord.Embed(
        title='Command im aktuellen Modus nicht verfügbar',
        description=f'Dieser Server läuft im Modus **{BOT_MODES.get(mode, {}).get("label", mode)}**.\n'
                    f'`/{cmd_name}` ist dort deaktiviert.\n'
                    f'Admin kann den Modus mit `/bot modus` ändern.',
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
    return False
