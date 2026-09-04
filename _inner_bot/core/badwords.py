"""Bad-Wort-Filter: Liste laden + Logging in DB und Bad-Word-Log-Kanal."""
import re
import unicodedata
from pathlib import Path
from core.config import BOT_DIR
from core.db import get_db
from core.channelnames import find_channel
from core.logging import logger

import discord

_BAD_WORDS_DEFAULT = [
    'arsch', 'arschloch', 'armleuchter', 'bastard', 'depp', 'dummkopf', 'dumm',
    'trottel', 'vollidiot', 'idiot', 'idiotin', 'schwachkopf', 'drecksack',
    'penner', 'versager', 'nichtsnutz', 'affe', 'hirni', 'widerling', 'ekel',
    'fotze', 'hurensohn', 'hure', 'missgeburt', 'spast', 'spasti', 'spacken',
    'scheiße', 'scheisse', 'scheiss', 'scheiß', 'scheißt', 'scheisst',
    'kacke', 'kacken', 'kackst', 'kackt', 'kack', 'pisse', 'pissen', 'pisst',
    'furz', 'furzt', 'stinke', 'stinken', 'verpiss', 'verpissen', 'verpisst',
    'fick', 'ficken', 'fickt', 'fickst', 'ficke', 'fickte', 'fickend', 'ficker',
    'gefickt', 'wichser', 'wichsen', 'wichst', 'lutsch', 'lutschen', 'lutscher',
    'blasen', 'penis', 'schwanz', 'titten', 'titte', 'nutte', 'vagina', 'muschi',
    'pussy', 'dildo', 'analsex', 'sperma', 'masturbieren', 'vögeln', 'vögelt',
    'bumsen', 'poppen', 'sex', 'vergewaltigung', 'vergewaltigen',
    'asshole', 'bitch', 'bitches', 'cunt', 'dick', 'dickhead', 'douchebag',
    'jackass', 'jerk', 'moron', 'retard', 'retarded', 'whore', 'slut', 'scumbag',
    'loser', 'pathetic', 'dumbass', 'stupid', 'shit', 'shitty', 'bullshit',
    'piss', 'pissed', 'crap', 'fuck', 'fucked', 'fucker', 'fucking',
    'motherfucker', 'cock', 'cocksucker', 'pussy', 'rape', 'rapist',
    'nigger', 'nigga', 'faggot', 'fag', 'kike', 'spic', 'chink', 'gook',
]


def _load_bad_words() -> list:
    """Lädt die Wortliste aus bad_words.txt (eine pro Zeile, # = Kommentar)."""
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

# Mehr Varianten als nur \b...\b: Satzzeichen und typische Schreibvarianten
# zwischen Buchstaben werden erkannt, ohne normale Wörter unnötig zu blockieren.
_NORMALIZE_TRANSLATION = str.maketrans({
    '0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '@': 'a',
    '$': 's',
})

def _normalize_text(text: str) -> str:
    text = unicodedata.normalize('NFKC', text).lower().translate(_NORMALIZE_TRANSLATION)
    text = text.replace('ß', 'ss')
    # Trenner zwischen Buchstaben entfernen, damit z.B. Schreibweisen mit
    # Leerzeichen/Punkten nicht einfach am Filter vorbeikommen.
    return re.sub(r'[\W_]+', '', text, flags=re.UNICODE)


def _build_patterns(words: list[str]):
    patterns = []
    for word in words:
        clean = _normalize_text(word)
        if not clean:
            continue
        # Einzelne Begriffe als Wortbestandteil erkennen; sehr kurze Begriffe
        # (<=3) bleiben bei der normalen Wortgrenze, um False Positives zu reduzieren.
        if len(clean) <= 3:
            patterns.append(re.compile(r'(?<!\w)' + re.escape(clean) + r'(?!\w)', re.IGNORECASE))
        else:
            patterns.append(re.compile(re.escape(clean), re.IGNORECASE))
    return patterns


_BAD_WORD_PATTERNS = _build_patterns(BAD_WORDS)


def find_bad_word(content: str) -> str | None:
    normalized = _normalize_text(content)
    for pattern, original in zip(_BAD_WORD_PATTERNS, BAD_WORDS):
        if pattern.search(normalized):
            return original
    return None


async def _log_bad_word(guild, author, channel, content: str):
    """Loggt eine gefilterte Nachricht in #bad-word-log + DB.
    Bei jedem 5. Bad-Word-Vorfall des Users wird automatisch ein Warn gesetzt."""
    word = find_bad_word(content) or '?'
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
