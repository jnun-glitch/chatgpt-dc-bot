"""Updates: Git-Changelog lesen und in die updates-Kanäle aller Server posten."""
import asyncio
import subprocess

import discord

from core.config import PROJECT_ROOT
from core.db import get_last_posted_hash, set_last_posted_hash
from core.channelnames import find_channel
from core.logging import logger


def get_latest_commits(count: int = 10):
    """Liest die letzten Commits des Discord-Bots aus git. Liefert Liste von (hash, message)."""
    try:
        result = subprocess.run(
            ['git', 'log', f'-{count}', '--pretty=format:%h|%s', '--', 'discord_bot/'],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            check=True, cwd=PROJECT_ROOT
        )
        if not result.stdout.strip():
            return []
        out = []
        for line in result.stdout.strip().split('\n'):
            parts = line.split('|', 1)
            if len(parts) == 2:
                out.append((parts[0], parts[1]))
        return out
    except Exception as e:
        logger.warning(f'git log fehlgeschlagen: {e}')
        return []


def get_pending_commits(limit: int = 15):
    """Liefert Commits seit dem letzten geposteten Stand (oder die letzten, wenn keiner bekannt)."""
    commits = get_latest_commits(limit)
    if not commits:
        return []
    last = get_last_posted_hash()
    if last:
        for i, (h, _) in enumerate(commits):
            if h == last:
                return commits[:i]
        return []
    return commits


async def get_latest_commits_async(count: int = 10):
    """Blockierenden git-subprocess-Call aus dem Event-Loop auslagern."""
    return await asyncio.to_thread(get_latest_commits, count)


async def get_pending_commits_async(limit: int = 15):
    """Blockierenden git-subprocess-Call aus dem Event-Loop auslagern."""
    return await asyncio.to_thread(get_pending_commits, limit)


def find_updates_channels(bot):
    """Findet alle `updates`-Textkanäle in allen Servern."""
    channels = []
    for guild in bot.guilds:
        ch = find_channel(guild, 'updates')
        if ch and isinstance(ch, discord.TextChannel):
            channels.append(ch)
    return channels


def _embed_from_commits(commits, guild_name):
    lines = []
    for h, msg in commits:
        lines.append(f'`{h}` {msg}')
    embed = discord.Embed(
        title='🆕 Neue Updates',
        description='\n'.join(lines) if lines else 'Keine neuen Änderungen.',
        color=discord.Color.blue()
    )
    embed.set_footer(text=f'Bot-Update · {guild_name}')
    return embed


async def post_updates_to_channels(bot, commits):
    """Postet die Commits in die updates-Kanäle aller Server. Liefert Anzahl der Kanäle."""
    channels = find_updates_channels(bot)
    for ch in channels:
        try:
            embed = _embed_from_commits(commits, ch.guild.name)
            await ch.send(embed=embed)
        except Exception as e:
            logger.warning(f'Update-Post in #{ch.name} ({ch.guild.name}) fehlgeschlagen: {e}')
    if commits:
        set_last_posted_hash(commits[0][0])
    return len(channels)
