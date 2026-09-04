"""Rollen-Presets, Staff-Kanäle und sichere Kanal-Berechtigungen."""
import discord
from core.logging import logger
from core.channelnames import styled_text_name, base_name, STAFF_EXCLUDED_BASE

# Rollen-Schutz: Diese Rollen werden von der allgemeinen Kanal-Vergabe nicht überschrieben.
PROTECTED_ROLE_NAMES = {'Owner', 'Manager', 'Bot Manager', 'Moderator'}

# Staff-Rollen-Hierarchie (höchster Eintrag = höchste Zielrolle).
STAFF_ROLE_HIERARCHY = [
    'Owner',
    'Manager',
    'Bot Manager',
    'Admin',
    'Moderator',
    'Supporter',
    'Media',
    'VIP',
    'Member',
    'Verified',
    'neue Rolle',
    'PowerBot',
    'ScratchAI Bot',
    'GalaxyBot',
]

ROLE_PRESETS = {
    'Admin': {
        'permissions': discord.Permissions(administrator=True),
        'color': 0xFF0000,
        'hoist': True,
    },
    'Moderator': {
        'permissions': discord.Permissions(
            view_channel=True,
            send_messages=True,
            manage_messages=True,
            moderate_members=True,
            kick_members=True,
            ban_members=True,
            manage_nicknames=True,
            embed_links=True,
            attach_files=True,
            mention_everyone=True,
        ),
        'color': 0x00FF00,
        'hoist': True,
    },
    'Support': {
        'permissions': discord.Permissions(
            view_channel=True,
            send_messages=True,
            manage_messages=True,
            embed_links=True,
            attach_files=True,
        ),
        'color': 0x00BFFF,
        'hoist': True,
    },
    'Member': {
        'permissions': discord.Permissions(
            view_channel=True,
            send_messages=True,
            read_message_history=True,
            embed_links=True,
            attach_files=True,
            add_reactions=True,
        ),
        'color': 0x99AAB5,
        'hoist': True,
    },
    'Verified': {
        'permissions': discord.Permissions(),
        'color': 0x2ECC71,
        'hoist': False,
    },
    'News': {
        'permissions': discord.Permissions(),
        'color': 0x3498DB,
        'hoist': False,
    },
    'Dev Updates': {
        'permissions': discord.Permissions(),
        'color': 0x9B59B6,
        'hoist': False,
    },
    'Events': {
        'permissions': discord.Permissions(),
        'color': 0xE67E22,
        'hoist': False,
    },
}


async def ensure_standard_roles(guild) -> list:
    """Legt Standard-Rollen an und heilt ihre Server-Berechtigungen.

    Bestehende Rollen werden bewusst auf das Preset zurückgesetzt. Dadurch kann eine
    versehentlich oder absichtlich aufgebohrte Member-/Support-/News-Rolle keine
    gefährlichen Zusatzrechte wie `manage_channels`, `manage_roles` oder `administrator`
    behalten.
    """
    created = []
    repaired = []
    for name, cfg in ROLE_PRESETS.items():
        role = discord.utils.get(guild.roles, name=name)
        if role is None:
            try:
                role = await guild.create_role(
                    name=name,
                    permissions=cfg['permissions'],
                    color=cfg['color'],
                    hoist=cfg['hoist'],
                    reason='Auto-Setup: Standard-Rolle',
                )
                created.append(name)
            except Exception as e:
                logger.warning(f'Rolle {name} konnte nicht erstellt werden: {e}')
            continue

        if role.is_default() or role.managed:
            continue

        # Nur die serverweiten Rollenrechte erzwingen. Das verhindert, dass
        # bestehende Standardrollen unbemerkt zu Admin-/Mod-Rollen werden.
        try:
            if role.permissions != cfg['permissions']:
                await role.edit(
                    permissions=cfg['permissions'],
                    reason='Auto-Setup: Standard-Rollenrechte repariert',
                )
                repaired.append(name)
        except Exception as e:
            logger.warning(f'Rolle {name} konnte nicht repariert werden: {e}')

    return created + [f'{name} (Rechte repariert)' for name in repaired]


async def ensure_bot_role_hierarchy(guild) -> list:
    """Prüft die Bot-Rollen-Hierarchie und versucht eine Reparatur.

    Discord lässt einen Bot nicht zuverlässig über seine eigene höchste Rolle
    hinaus arbeiten. Deshalb meldet diese Funktion vor allem einen fehlenden
    Spielraum anstatt still falsche Sicherheit vorzutäuschen.
    """
    me = guild.me
    if not me or me.top_role == guild.default_role:
        return []

    targets = [
        r for r in guild.roles
        if r.name in {'Member', 'Verified', 'News', 'Dev Updates', 'Events', 'Support'}
        and not r.is_default()
        and not r.managed
    ]
    blocked = [r.name for r in targets if r.position >= me.top_role.position]
    if not blocked:
        return []

    logger.warning(
        'Bot-Rolle steht zu niedrig auf %s; diese Rollen können ggf. nicht vergeben werden: %s',
        guild.name,
        ', '.join(blocked),
    )
    return [f'Bot-Rolle zu niedrig: {name}' for name in blocked]


async def ensure_staff_channels(guild) -> list:
    """Legt Staff-Kanäle an und setzt ihre privaten Berechtigungen auch bei vorhandenen Kanälen."""
    from core.channelnames import find_channel as _find_channel
    changed = []

    channel_plan = {
        'staff-movements': {
            'topic': 'Rollen-Änderungen und Beförderungen (automatisch)',
            'allow': ('Admin', 'Moderator'),
        },
        'bad-word-log': {
            'topic': 'Gefilterte Nachrichten (Bad Words) – nur für Admins',
            'allow': ('Admin',),
        },
        'audit-log': {
            'topic': 'Audit-Logging – Änderungen und Moderationsereignisse',
            'allow': ('Admin',),
        },
    }

    bot_member = guild.me
    for base, cfg in channel_plan.items():
        styled = styled_text_name(base)
        ch = _find_channel(guild, base)
        try:
            admin_role = discord.utils.get(guild.roles, name='Admin')
            mod_role = discord.utils.get(guild.roles, name='Moderator')
            support_role = discord.utils.get(guild.roles, name='Support')

            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=False,
                    send_messages=False,
                    read_message_history=False,
                    connect=False,
                    speak=False,
                )
            }
            for role, allowed in ((admin_role, 'Admin'), (mod_role, 'Moderator'), (support_role, 'Support')):
                if role and allowed in cfg['allow']:
                    overwrites[role] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        read_message_history=True,
                        use_application_commands=True,
                    )
            if bot_member:
                overwrites[bot_member] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                    manage_messages=True,
                    manage_channels=True,
                )

            if ch is None:
                ch = await guild.create_text_channel(
                    styled,
                    topic=cfg['topic'],
                    overwrites=overwrites,
                    reason='Auto-Setup: Staff-Kanal',
                )
                changed.append(styled)
            else:
                edits = {}
                if ch.name != styled:
                    edits['name'] = styled
                if ch.topic != cfg['topic']:
                    edits['topic'] = cfg['topic']
                edits['overwrites'] = overwrites
                await ch.edit(**edits, reason='Auto-Setup: Staff-Berechtigungen repariert')
                changed.append(f'{styled} (Berechtigungen geprüft)')
        except Exception as e:
            logger.warning(f'{styled} Kanal-Setup fehlgeschlagen: {e}')

    return changed


def _staff_overwrite(guild, extra: dict | None = None) -> dict:
    """Overwrites für echte Staff-Rollen. Niemals Manage Channels für Member-/Fun-Rollen vergeben."""
    ow = {
        'view_channel': True,
        'send_messages': True,
        'read_message_history': True,
        'use_application_commands': True,
    }
    if extra:
        ow.update(extra)
    result = {}
    for name in ('Admin', 'Moderator', 'Support'):
        role = discord.utils.get(guild.roles, name=name)
        if role:
            result[role] = discord.PermissionOverwrite(**ow)
    return result


def _member_overwrite(is_voice: bool = False) -> discord.PermissionOverwrite:
    """Sicheres Standardprofil für normale Mitglieder – ohne Kanal-/Rollenverwaltung."""
    values = {
        'view_channel': True,
        'send_messages': True,
        'read_message_history': True,
        'add_reactions': True,
        'embed_links': True,
        'attach_files': True,
        'use_application_commands': True,
        'manage_channels': False,
        'manage_permissions': False,
        'manage_webhooks': False,
    }
    if is_voice:
        values.update(connect=True, speak=True)
    return discord.PermissionOverwrite(**values)


async def apply_channel_permissions(guild, channel=None):
    """Setzt ein konservatives Kanal-Sicherheitsprofil.

    @everyone darf keine Nachrichten senden und keine Slash-Commands ausführen.
    Member/Verified bekommen nur normale Community-Rechte.
    Nur Admin/Moderator/Support erhalten Moderationsrechte.
    Beliebige Custom-Rollen werden NICHT mehr automatisch zu Moderatoren gemacht.
    """
    targets = [channel] if channel else list(guild.channels)
    changed = []

    member_role = discord.utils.get(guild.roles, name='Member')

    rules_gate_active = False
    rules_channel_id = None
    try:
        from core.db import get_rules_gate
        gate = get_rules_gate(guild.id)
        rules_gate_active = bool(gate.get('enabled'))
        if gate.get('rules_channel_id'):
            rules_channel_id = int(gate['rules_channel_id'])
        if gate.get('member_role_id'):
            member_role = guild.get_role(int(gate['member_role_id'])) or member_role
    except Exception:
        pass

    staff_roles = {
        name: discord.utils.get(guild.roles, name=name)
        for name in ('Admin', 'Moderator', 'Support')
    }

    for ch in targets:
        if isinstance(ch, discord.CategoryChannel):
            continue
        if base_name(ch.name) in STAFF_EXCLUDED_BASE:
            continue
        if hasattr(ch, 'category') and ch.category and ch.category.name == 'Tickets':
            continue

        is_rules_channel = rules_gate_active and ch.id == rules_channel_id
        is_voice = isinstance(ch, discord.VoiceChannel)
        everyone_view = is_rules_channel if rules_gate_active else True

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=everyone_view,
                send_messages=False,
                read_message_history=everyone_view,
                use_application_commands=False,
                manage_channels=False,
                manage_permissions=False,
                manage_webhooks=False,
            )
        }

        if guild.me:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
                manage_channels=True,
                manage_permissions=True,
                manage_webhooks=True,
                use_application_commands=True,
            )

        if member_role:
            overwrites[member_role] = _member_overwrite(is_voice)

        staff_perm = {
            'view_channel': True,
            'send_messages': True,
            'read_message_history': True,
            'use_application_commands': True,
            'embed_links': True,
            'attach_files': True,
            'manage_messages': True,
            'manage_channels': False,
            'manage_permissions': False,
            'manage_webhooks': False,
        }
        if is_voice:
            staff_perm.update(connect=True, speak=True, move_members=True)

        for role in staff_roles.values():
            if role:
                overwrites[role] = discord.PermissionOverwrite(**staff_perm)

        try:
            await ch.edit(overwrites=overwrites, reason='Auto-Setup: sichere Kanal-Berechtigungen')
            changed.append(ch.name)
        except Exception as e:
            logger.warning(f'Berechtigungen für #{getattr(ch, "name", "?")} fehlgeschlagen: {e}')

    return changed
