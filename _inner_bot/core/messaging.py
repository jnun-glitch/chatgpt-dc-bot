"""Message-Filter: Spam-Schutz, Auto-Response und XP-Verarbeitung für on_message."""
import time
import discord
from core.logging import logger
from core.db import _add_xp
from core.channelnames import find_channel
from core.badwords import _BAD_WORD_RE, _log_bad_word
from core.utils import _assign_level_role

_user_message_cache = {}
_spam_threshold = 5
_spam_window = 6
_MAX_CACHED_USERS = 1000


def _prune_message_cache(now):
    """Entfernt User, deren Einträge abgelaufen sind, wenn der Cache zu groß wird."""
    if len(_user_message_cache) <= _MAX_CACHED_USERS:
        return
    cutoff = now - _spam_window
    for k in [k for k, v in _user_message_cache.items() if not v or v[-1] < cutoff]:
        _user_message_cache.pop(k, None)

_auto_response_patterns = {
    'wie geht': 'Nutze `/ask` um eine Frage zu stellen! Der Bot kann dir bei Scratch-Fragen helfen.',
    'was ist scratch': 'Scratch ist eine kostenlose Programmiersprache zum Erlernen von Programmierung. Nutze `/ask` für mehr Infos!',
    'wie mache ich': 'Stelle deine Frage mit `/ask <deine Frage>` und die AI hilft dir!',
    'hilfe': 'Nutze `/help` für eine Übersicht aller Befehle oder `/ask` für Scratch-Fragen!',
    'wie programmier': 'Nutze `/ask` mit deiner Frage - die AI kann dir bei der Programmierung helfen!',
    'was kann ich': 'Nutze `/help` um alle Befehle zu sehen! Du kannst Spiele generieren, Fragen stellen und mehr.',
    'danke': 'Bitte! 😊 Frag gerne wenn du Hilfe brauchst!',
    'hallo': 'Hey! 👋 Nutze `/help` für eine Übersicht oder `/ask` für Fragen!',
    'hi': 'Hey! 👋 Willkommen! Nutze `/help` für eine Übersicht.',
}

_log_channel_cache = {}


async def _rules_gate_blocks(message) -> bool:
    """Löscht Nachrichten von Usern, die das Rules Gate noch nicht akzeptiert haben.
    Liefert True, wenn die Nachricht gelöscht wurde (weitere Verarbeitung stoppen)."""
    try:
        if message.author.bot:
            return False
        if message.author.guild_permissions.administrator:
            return False
        from core.db import get_rules_gate
        gate = get_rules_gate(message.guild.id)
        if not gate or not gate.get('enabled'):
            return False

        member_role = None
        if gate.get('member_role_id'):
            member_role = message.guild.get_role(int(gate['member_role_id']))
        if member_role is None:
            member_role = discord.utils.get(message.guild.roles, name='Member')
        if member_role and member_role in message.author.roles:
            return False

        # Staff-Rollen dürfen auch ohne Member schreiben
        staff_names = {'Admin', 'Moderator', 'Support', 'Manager', 'Owner', 'Bot Manager'}
        if any(role.name in staff_names for role in message.author.roles):
            return False

        # Im Regeln-Kanal selbst nicht blocken (Reaktion auf die Regeln)
        if gate.get('rules_channel_id') and message.channel.id == int(gate['rules_channel_id']):
            return False

        try:
            await message.delete()
        except Exception:
            pass

        try:
            rules_ch = message.guild.get_channel(int(gate['rules_channel_id'])) if gate.get('rules_channel_id') else None
            rules_mention = rules_ch.mention if rules_ch else '#regeln'
            from core.db import format_msg
            verify_title = format_msg(message.guild.id, 'verify_msg',
                                      mention=message.author.mention,
                                      name=message.author.display_name)
            verify_desc = format_msg(message.guild.id, 'verify_desc',
                                     mention=message.author.mention,
                                     name=message.author.display_name,
                                     channel=rules_mention)
            embed = discord.Embed(
                title=verify_title,
                description=verify_desc,
                color=discord.Color.red()
            )
            await message.channel.send(embed=embed, delete_after=8)
        except Exception:
            pass
        return True
    except Exception:
        return False


async def handle_message(bot, message):
    """Kern-Logik von on_message: Spam, Bad Words, Auto-Response, XP, Admin-Log."""
    if message.author.bot:
        return
    # DM-Guard: keine Verarbeitung außerhalb von Servern
    if not message.guild:
        return

    # Text-Commands verarbeiten (Prefix-Commands wie !afk, !tag, !lock-mute ...)
    try:
        ctx = await bot.get_context(message)
        if ctx.valid:
            await bot.invoke(ctx)
            return
    except Exception:
        pass

    # Rules Gate: nicht-verifizierte User dürfen außerhalb des Regeln-Kanals nicht schreiben
    if await _rules_gate_blocks(message):
        return

    # Ticket-Channels: nur Commands erlauben
    if (hasattr(message.channel, 'category') and message.channel.category
            and message.channel.category.name == 'Tickets'):
        await bot.process_commands(message)
        return

    # Spam-Schutz
    user_id = str(message.author.id)
    now = time.time()
    _prune_message_cache(now)
    _user_message_cache.setdefault(user_id, []).append(now)
    _user_message_cache[user_id] = [t for t in _user_message_cache[user_id] if now - t < _spam_window]
    if len(_user_message_cache[user_id]) > _spam_threshold:
        try:
            await message.delete()
            from core.db import format_msg
            spam_text = format_msg(message.guild.id, 'spam_msg',
                                   mention=message.author.mention,
                                   name=message.author.display_name)
            await message.channel.send(spam_text, delete_after=6)
            log_ch = find_channel(message.guild, 'admin-log')
            if log_ch:
                await log_ch.send(f'⚠️ **Spam** von {message.author} in {message.channel.mention}')
        except Exception:
            pass
        _user_message_cache[user_id] = []
        return

    # Bad-Wort-Filter
    if _BAD_WORD_RE.search(message.content):
        try:
            await message.delete()
            from core.db import format_msg
            bw_text = format_msg(message.guild.id, 'badword_msg',
                                 mention=message.author.mention,
                                 name=message.author.display_name)
            await message.channel.send(bw_text, delete_after=6)
            await _log_bad_word(message.guild, message.author, message.channel, message.content)
        except Exception:
            pass
        return

    # Auto-Response
    content_check = message.content.lower().strip()
    bot_mentioned = bot.user in message.mentions
    if not bot_mentioned:
        words = content_check.split()
        bot_mentioned = any(w in ['bot', 'scratchai'] for w in words)
    if bot_mentioned and not message.content.startswith('/') and len(message.content) > 5:
        for pattern, response in _auto_response_patterns.items():
            if pattern in content_check and len(content_check) < 80:
                try:
                    await message.reply(response, delete_after=30)
                except Exception:
                    pass
                break

    # XP System + Level-Up
    new_level = _add_xp(message.author.id, message.guild.id)
    if new_level:
        embed = discord.Embed(
            title=f'Level Up! 🎉',
            description=f'{message.author.mention} ist jetzt **Level {new_level}**!',
            color=discord.Color.gold()
        )
        try:
            await message.channel.send(embed=embed, delete_after=10)
        except Exception:
            pass
        await _assign_level_role(message.author, message.guild, new_level)

    # Admin-Log
    try:
        gid = message.guild.id
        log_ch = _log_channel_cache.get(gid)
        if log_ch is None or log_ch.guild != message.guild:
            log_ch = find_channel(message.guild, 'admin-log')
            _log_channel_cache[gid] = log_ch
        if log_ch is None:
            return

        embed = discord.Embed(
            description=message.content[:2000] if message.content else '(kein Text)',
            color=discord.Color.blurple(),
            timestamp=message.created_at
        )
        embed.set_author(
            name=f'{message.author.display_name} ({message.author})',
            icon_url=message.author.display_avatar.url
        )
        embed.add_field(name='Channel', value=f'{message.channel.mention}', inline=True)
        if message.attachments:
            att = ', '.join(a.filename for a in message.attachments[:5])
            embed.add_field(name='Anhänge', value=att, inline=True)
        embed.set_footer(text=f'ID: {message.author.id}')

        await log_ch.send(embed=embed)
    except Exception:
        pass
