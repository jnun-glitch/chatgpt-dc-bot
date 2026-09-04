"""Kanal-Namen: emoji-stilisierte Namen (Emoji-Name) + Namens-Auflösung (Base ↔ Styled)."""
import discord

_TEXT_STYLES = {
    # SMP-Öffentliche Kanäle
    'regeln': '📜',
    'willkommen': '👋',
    'ankündigungen': '📣',
    'updates': '🆕',
    'support': '🛟',
    'chat': '💬',
    'mc-chat': '⛏️',
    'bauen': '🏗️',
    'screenshots': '📸',
    'schematics': '🧩',
    # Staff / Log
    'staff-movements': '🛡️',
    'bad-word-log': '🚫',
    'admin-log': '📋',
    'audit-log': '📝',
    # Community
    'clips': '🎬',
    'team-chat': '🗣️',
    'Allgemein': '🌐',
}

_VOICE_STYLES = {
    'minecraft': '🎮',
    'musik': '🎵',
    'flüsterzimmer': '🤫',
    'allgemein': '🌐',
    'team-talk': '🗣️',
}

# Exakte Basis-Namen für Berechtigungs-Ausnahme-Logik (Staff-Kanäle)
STAFF_EXCLUDED_BASE = {'staff-movements', 'bad-word-log', 'admin-log', 'audit-log'}


def styled_text_name(base: str) -> str:
    """Stilisierter Textkanal-Name, z. B. regeln → 📜-regeln."""
    emoji = _TEXT_STYLES.get(base)
    return f'{emoji}-{base}' if emoji else base


def styled_voice_name(base: str) -> str:
    """Stilisierter Voice-Kanal-Name, z. B. Minecraft → 🎮 Minecraft."""
    emoji = _VOICE_STYLES.get(base.lower())
    return f'{emoji} {base}' if emoji else base


def base_name(name: str) -> str:
    """Mappt einen (ggf. emoji-stilisierten) Kanalnamen zurück auf den Basis-Namen.
    Erkennt das '-'-, das 'I'- und das I-Trennzeichen-Format."""
    for base, emoji in _TEXT_STYLES.items():
        if (
            name == base
            or name.lower() == base.lower()
            or name == f'{emoji}-{base}'
            or name.lower() == f'{emoji}-{base}'.lower()
            or name == f'{emoji}I{base}'
            or name.lower() == f'{emoji}I{base}'.lower()
            or name == f'{emoji}I {base}'
            or name.lower() == f'{emoji}I {base}'.lower()
        ):
            return base
    for base, emoji in _VOICE_STYLES.items():
        if name.lower() == base.lower() or name.lower() == f'{emoji} {base}'.lower():
            return base
    return name


def find_channel(guild, base: str):
    """Findet einen Kanal über den Basis-Namen – egal ob stilisiert ('-'/'I'), pur oder case-insensitive."""
    for name in (styled_text_name(base), base):
        # Exakter Treffer
        ch = discord.utils.get(guild.channels, name=name)
        if ch is not None:
            return ch
    # Case-insensitive Fallback für Text-Kanäle
    styled = styled_text_name(base).lower()
    base_lower = base.lower()
    for ch in guild.channels:
        if ch.name.lower() == styled or ch.name.lower() == base_lower:
            return ch
    # Alt-Formate ('I', 'I ') Case-insensitive
    for base_b, emoji in _TEXT_STYLES.items():
        if base_b.lower() == base_lower:
            for old in (f'{emoji}I{base_b}', f'{emoji}I {base_b}'):
                old_lower = old.lower()
                for ch in guild.channels:
                    if ch.name.lower() == old_lower:
                        return ch
            break
    # Voice
    voice_styled = styled_voice_name(base)
    ch = discord.utils.get(guild.channels, name=voice_styled)
    if ch is not None:
        return ch
    return None


def find_all_channels(guild, base: str):
    """Findet ALLE Kanäle, die zum Basis-Namen passen (Text + Voice, alle Formate)."""
    base_lower = base.lower()
    result = []
    for ch in guild.channels:
        if isinstance(ch, discord.CategoryChannel):
            continue
        bn = base_name(ch.name)
        if bn.lower() == base_lower:
            result.append(ch)
    return result
