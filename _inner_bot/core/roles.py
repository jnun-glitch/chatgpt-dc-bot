"""Rollen-Presets, Staff-Kanäle und Kanal-Berechtigungen."""
import discord
from core.logging import logger
from core.channelnames import styled_text_name, base_name, STAFF_EXCLUDED_BASE

# Rollen-Schutz: Werden bei verdächtigen Changes entfernt
PROTECTED_ROLE_NAMES = ['Owner', 'Manager', 'Bot Manager', 'Moderator']

# Staff-Rollen-Hierarchie (höhester Index = höchstest Rolle)
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

# Kanäle, die NICHT automatisch neu berechtigt werden (Staff + Tickets)
# BASIS-Namen – Vergleich via base_name() in apply_channel_permissions
# (alte Kanalnamen werden automatisch erkannt)


async def ensure_standard_roles(guild) -> list:
    """Legt fehlende Standard-Rollen mit den richtigen Rechten an. Liefert Liste der erstellten Rollen."""
    created = []
    for name, cfg in ROLE_PRESETS.items():
        role = discord.utils.get(guild.roles, name=name)
        if not role:
            try:
                await guild.create_role(
                    name=name,
                    permissions=cfg['permissions'],
                    color=cfg['color'],
                    hoist=cfg['hoist'],
                    reason='Auto-Setup: Standard-Rolle'
                )
                created.append(name)
            except Exception as e:
                logger.warning(f'Rolle {name} konnte nicht erstellt werden: {e}')
    return created


async def ensure_bot_role_hierarchy(guild) -> list:
    """Heilt die Rollen-Hierarchie: Der Bot muss ÜBER allen Rollen stehen,
    die er vergeben soll (Member u.a.), sonst scheitert die Rollenvergabe
    mit 403 Missing Permissions. Verschiebt die höchste Bot-Rolle nach oben.
    Liefert Liste der angepassten Rollen."""
    if not guild.me:
        return []
    bot_top = guild.me.top_role
    if bot_top == guild.default_role:
        return []
    try:
        if not bot_top.permissions.manage_roles and not bot_top.permissions.administrator:
            return []
    except Exception:
        return []

    # Rollen, die der Bot vergeben muss – oberste davon bestimmt die Mindestposition
    target_names = {'Member', 'Verified', 'News', 'Dev Updates', 'Events', 'Media', 'VIP', 'Supporter', 'Support'}
    targets = [r for r in guild.roles if r.name in target_names and r != guild.default_role]
    if not targets:
        return []
    # Höchste Ziel-Rolle (nach Position)
    highest_target = max(targets, key=lambda r: r.position)
    if highest_target.position < bot_top.position:
        return []  # Bot steht bereits drüber

    # Bot-Rolle genau einen Rang über der höchsten Ziel-Rolle platzieren
    new_position = highest_target.position + 1
    # Aber nicht über die höchste Server-Rolle hinaus
    max_pos = max((r.position for r in guild.roles if not r.is_bot_managed()), default=0)
    if new_position > max_pos:
        new_position = max_pos
    if new_position <= bot_top.position:
        return []
    try:
        await bot_top.edit(position=new_position, reason='Auto-Heal: Bot-Rolle über vergabefähige Rollen')
        logger.info(f'Bot-Rolle {bot_top.name} auf Position {new_position} verschoben ({guild.name})')
        return [bot_top.name]
    except Exception as e:
        logger.warning(f'Bot-Rollen-Hierarchie konnte nicht repariert werden ({guild.name}): {e}')
        return []


async def ensure_staff_channels(guild) -> list:
    """Legt fehlende Staff-Kanäle an (staff-movements + bad-word-log).
    Benennt bestehende Kanäle mit Basis-Namen automatisch in den Emoji-Stil um.
    Liefert Liste der erstellten/umbenannten Kanäle."""
    from core.channelnames import find_channel as _find_channel
    created = []

    staff_plan = [
        ('staff-movements', 'Rollen-Änderungen und Beförderungen (automatisch)'),
        ('bad-word-log', 'Gefilterte Nachrichten (Bad Words) – nur für Admins'),
        ('audit-log', 'Vollständiges Audit-Logging – ALLE Nachrichten, Commands, Änderungen'),
    ]
    for base, topic in staff_plan:
        styled = styled_text_name(base)
        ch = _find_channel(guild, base)
        if ch is None:
            try:
                admin_role = discord.utils.get(guild.roles, name='Admin')
                mod_role = discord.utils.get(guild.roles, name='Moderator')
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                }
                if admin_role:
                    overwrites[admin_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
                if mod_role:
                    overwrites[mod_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True)
                await guild.create_text_channel(
                    styled,
                    topic=topic,
                    overwrites=overwrites,
                    reason='Auto-Setup: Staff-Kanal'
                )
                created.append(styled)
            except Exception as e:
                logger.warning(f'{styled} Kanal konnte nicht erstellt werden: {e}')
        elif ch.name != styled:
            try:
                await ch.edit(name=styled)
                created.append(f'{styled} (umbenannt)')
            except Exception as e:
                logger.warning(f'{ch.name} konnte nicht in {styled} umbenannt werden: {e}')
    return created


def _staff_overwrite(guild, extra: dict | None = None) -> dict:
    """Overwrites für Staff-Rollen (Admin, Moderator, Support) in normalen Kanälen."""
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


async def apply_channel_permissions(guild, channel=None):
    """Berechtigt Kanäle konsistent: @everyone sieht, nur Member schreibt,
    Alle nicht-geschützten Rollen (Admin, Supporter, Media, VIP, etc.) haben volle Rechte.
    Staff-/Ticket-Kanäle werden übersprungen.
    Ist das Rules Gate aktiv, sieht @everyone nur den Regeln-Kanal.
    Liefert Liste der angepassten Kanäle."""
    targets = [channel] if channel else list(guild.channels)
    changed = []

    member_role = discord.utils.get(guild.roles, name='Member')

    # Rules Gate: @everyone auf die übrigen Kanäle sperren
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

    # Geschützte Rollen (keine Rechte-Vergabe): Owner, Manager, Bot Manager, Moderator + Bot-Rollen
    protected_names = {'Owner', 'Manager', 'Bot Manager', 'Moderator'}
    protected_roles = set()
    for r in guild.roles:
        if r.name in protected_names or r.is_bot_managed():
            protected_roles.add(r)

    for ch in targets:
        if isinstance(ch, discord.CategoryChannel):
            continue
        if base_name(ch.name) in STAFF_EXCLUDED_BASE:
            continue
        if (hasattr(ch, 'category') and ch.category and ch.category.name == 'Tickets'):
            continue

        is_rules_channel = rules_gate_active and ch.id == rules_channel_id
        is_voice = isinstance(ch, discord.VoiceChannel)

        if rules_gate_active:
            everyone_view = is_rules_channel
        else:
            everyone_view = True

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=everyone_view,
                send_messages=False,
                read_message_history=everyone_view,
                use_application_commands=False,
            ),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_messages=True),
        }
        if member_role:
            member_perm = {
                'view_channel': True,
                'send_messages': True,
                'read_message_history': True,
                'add_reactions': True,
                'embed_links': True,
                'attach_files': True,
                'use_application_commands': True,
            }
            if is_voice:
                member_perm['connect'] = True
                member_perm['speak'] = True
            overwrites[member_role] = discord.PermissionOverwrite(**member_perm)

        staff = {'view_channel': True, 'send_messages': True, 'read_message_history': True,
                 'use_application_commands': True, 'embed_links': True, 'attach_files': True,
                 'manage_messages': True}
        if is_voice:
            staff['connect'] = True
            staff['speak'] = True
            staff['move_members'] = True

        # Alle nicht-geschützten Rollen mit vollen Rechten
        for role in guild.roles:
            if role in protected_roles or role == guild.default_role:
                continue
            if role in overwrites:
                continue  # bereits gesetzt (Member, Bot)
            overwrites[role] = discord.PermissionOverwrite(**staff)

        try:
            await ch.edit(overwrites=overwrites)
            changed.append(ch.name)
        except Exception as e:
            logger.warning(f'Berechtigungen für #{ch.name} fehlgeschlagen: {e}')

    return changed
