"""Bad-Wort-Filter: Liste laden + Logging in DB und Bad-Word-Log-Kanal."""
import re
from pathlib import Path
from core.config import BOT_DIR
from core.db import get_db
from core.channelnames import find_channel
from core.logging import logger

import discord

_BAD_WORDS_DEFAULT = [
    'arsch', 'arschloch', 'armleuchter', 'bastard', 'depp',
    'fotze', 'hurensohn', 'hure', 'idiot', 'missgeburt',
    'spast', 'spasti', 'trottel', 'vollidiot',
    'scheiße', 'scheisse', 'scheiss', 'scheiß', 'scheißt', 'scheisst',
    'kacke', 'kacken', 'kackst', 'kackt', 'kack',
    'pisse', 'pissen', 'pisst', 'furz', 'furzt',
    'fick', 'ficken', 'fickt', 'fickst', 'ficke', 'fickte', 'fickend', 'fickende',
    'ficker', 'gefickt', 'wichser', 'wichsen', 'wichst', 'wichs',
    'lutsch', 'lutschen', 'lutscht', 'lutscher', 'blowjob', 'penis', 'schwanz',
    'titten', 'nutte', 'vagina',
    'asshole', 'bitch', 'bitches', 'cunt', 'dick', 'dickhead',
    'moron', 'retard', 'retarded', 'whore', 'slut',
    'shit', 'shitty', 'bullshit', 'piss', 'pissed',
    'fuck', 'fucked', 'fucker', 'fucking', 'motherfucker', 'cock',
    'cocksucker', 'pussy',
    'nigger', 'nigga', 'faggot', 'fag', 'kike', 'spic',
]


def _load_bad_words() -> list:
    """Lädt die Wortliste aus bad_words.txt (eine pro Zeile, # = Kommentar).
    Bei Fehler/Fallback wird die eingebettete Standardliste verwendet."""
    path = BOT_DIR / 'bad_words.txt'
    try:
        words = []
        for raw in path.read_text(encoding='utf-8').splitlines():
            line = raw.strip().lower()
            if not line or line.startswith('#'):
                continue
            words.append(line)
        if words:
            return words
    except FileNotFoundError:
        logger.warning('bad_words.txt nicht gefunden – verwende eingebettete Liste')
    except Exception as e:
        logger.warning(f'bad_words.txt konnte nicht geladen werden ({e}) – verwende eingebettete Liste')
    return list(_BAD_WORDS_DEFAULT)


BAD_WORDS = _load_bad_words()
_BAD_WORD_RE = re.compile(
    r'\b(?:' + '|'.join(re.escape(w) for w in BAD_WORDS) + r')\b',
    re.IGNORECASE,
)


async def _log_bad_word(guild, author, channel, content: str):
    """Loggt eine gefilterte Nachricht in #bad-word-log + DB.
    Bei jedem 5. Bad-Word-Vorfall des Users wird automatisch ein Warn gesetzt."""
    match = _BAD_WORD_RE.search(content)
    word = match.group(0) if match else '?'
    uid = str(author.id)
    gid = str(guild.id)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO bad_word_log (user_id, guild_id, channel, word, content) VALUES (?, ?, ?, ?, ?)',
        (uid, gid, channel.name, word, content[:500]),
    )
    conn.commit()
    cursor.execute('SELECT COUNT(*) FROM bad_word_log WHERE user_id = ? AND guild_id = ?', (uid, gid))
    count = cursor.fetchone()[0]
    conn.close()

    try:
        log_ch = find_channel(guild, 'bad-word-log')
        if log_ch:
            embed = discord.Embed(
                title='🚫 Bad Word gefiltert',
                description=content[:1500],
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
            embed.set_author(name=f'{author} ({author.id})', icon_url=author.display_avatar.url)
            embed.add_field(name='Kanal', value=channel.mention, inline=True)
            embed.add_field(name='Wort', value=f'`{word}`', inline=True)
            embed.add_field(name='Vorfälle', value=str(count), inline=True)
            await log_ch.send(embed=embed)
    except Exception as e:
        logger.warning(f'bad-word-log konnte nicht aktualisiert werden: {e}')

    if count % 5 == 0:
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO user_warns (user_id, guild_id, grund, von) VALUES (?, ?, ?, ?)',
                (uid, gid, f'Auto-Warn: {count}. Bad-Word-Vorfall ({word})', 'Bot (Auto-Warn)'),
            )
            conn.commit()
            conn.close()
            try:
                log_ch = find_channel(guild, 'admin-log')
                if log_ch:
                    await log_ch.send(
                        f'⚠️ **Auto-Warn:** {author.mention} hat **{count}** Bad-Word-Vorfälle – '
                        f'automatisch verwarnet!'
                    )
            except Exception:
                pass
        except Exception as e:
            logger.warning(f'Auto-Warn konnte nicht gesetzt werden: {e}')
