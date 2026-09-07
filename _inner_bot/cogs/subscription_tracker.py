"""Subscriber-count tracking for configured YouTube/Twitch creators.

This is intentionally separate from creator upload/live alerts. It tracks the
public/authorized subscriber count and posts a small Discord notification when
the count changes.

YouTube note: the public subscriberCount is rounded to three significant
figures by the YouTube API, so this is count-change tracking, not exact
per-subscriber tracking.

Twitch note: subscriber totals require a user access token with
channel:read:subscriptions, and the token must belong to the broadcaster being
tracked. No Discord user credentials are ever requested.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import discord
from discord.ext import commands, tasks

from core.db import get_db
from core.logging import logger


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        logger.warning("Env-Variable %s ist keine gültige Zahl (%r) – Default %s verwendet.", name, raw, default)
        return default


POLL_SECONDS = _env_int("SOCIAL_SUBSCRIBER_POLL_SECONDS", 300, 60)
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "").strip()
TWITCH_USER_ACCESS_TOKEN = os.environ.get("TWITCH_USER_ACCESS_TOKEN", "").strip()


def subscriber_delta(previous: int | None, current: int | None) -> int:
    """Return the signed count change; zero means no usable change."""
    if previous is None or current is None:
        return 0
    return int(current) - int(previous)


def should_announce(previous: int | None, current: int | None) -> bool:
    return previous is not None and current is not None and previous != current


def youtube_subscriber_count(channel_id: str) -> int:
    if not YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY ist nicht konfiguriert")
    params = urllib.parse.urlencode({
        "part": "statistics",
        "id": channel_id,
        "key": YOUTUBE_API_KEY,
    })
    req = urllib.request.Request(
        f"https://www.googleapis.com/youtube/v3/channels?{params}",
        headers={"User-Agent": "ScratchAI/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YouTube API HTTP {exc.code}: {text[:250]}") from exc
    rows = payload.get("items") or []
    if not rows:
        raise RuntimeError("YouTube-Kanal für Subscriber-Tracking nicht gefunden")
    value = rows[0].get("statistics", {}).get("subscriberCount")
    if value is None:
        raise RuntimeError("YouTube liefert keine Subscriber-Zahl für diesen Kanal")
    return int(value)


def twitch_subscriber_count(broadcaster_id: str) -> int:
    if not TWITCH_CLIENT_ID or not TWITCH_USER_ACCESS_TOKEN:
        raise RuntimeError("Twitch Subscriber-Tracking ist nicht konfiguriert")
    params = urllib.parse.urlencode({"broadcaster_id": broadcaster_id, "first": "1"})
    req = urllib.request.Request(
        f"https://api.twitch.tv/helix/subscriptions?{params}",
        headers={
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {TWITCH_USER_ACCESS_TOKEN}",
            "User-Agent": "ScratchAI/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Twitch API HTTP {exc.code}: {text[:250]}") from exc
    return int(payload.get("total") or 0)


def make_count_embed(provider: str, account: str, previous: int, current: int) -> discord.Embed:
    delta = subscriber_delta(previous, current)
    if delta > 0:
        icon = "📈"
        change = f"+{delta:,}"
    else:
        icon = "📉"
        change = f"{delta:,}"
    platform = "YouTube" if provider == "youtube" else "Twitch"
    embed = discord.Embed(
        title=f"{icon} {platform}-Abozahl geändert",
        description=f"**{account}** hat jetzt **{current:,}** Abos.\nÄnderung: **{change}**",
        color=discord.Color.green() if delta > 0 else discord.Color.orange(),
    )
    embed.set_footer(text="ScratchAI Subscriber Tracking")
    return embed


class SubscriptionTrackerCog(commands.Cog):
    """Poll configured creator subscriptions without adding slash commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._init_db()
        self.poll.start()

    def cog_unload(self):
        self.poll.cancel()

    def _init_db(self):
        db = get_db()
        db.execute("""CREATE TABLE IF NOT EXISTS social_subscriber_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            account TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            last_count INTEGER,
            enabled BOOLEAN DEFAULT TRUE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, provider, account)
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_social_sub_tracking_enabled ON social_subscriber_tracking(enabled, provider)")
        db.commit()

    def _configured_sources(self) -> list[tuple[int, str, str, str, int]]:
        rows = get_db().execute(
            "SELECT id,guild_id,provider,account,channel_id FROM social_notifications "
            "WHERE enabled=1 AND provider IN ('youtube','twitch')"
        ).fetchall()
        return [(int(r[0]), str(r[1]), str(r[2]), str(r[3]), int(r[4])) for r in rows]

    def _get_previous(self, guild_id: str, provider: str, account: str) -> int | None:
        row = get_db().execute(
            "SELECT last_count FROM social_subscriber_tracking WHERE guild_id=? AND provider=? AND account=?",
            (guild_id, provider, account),
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None

    def _save_count(self, guild_id: str, provider: str, account: str, channel_id: int, count: int):
        db = get_db()
        db.execute(
            """INSERT INTO social_subscriber_tracking(guild_id,provider,account,channel_id,last_count)
               VALUES(?,?,?,?,?)
               ON CONFLICT(guild_id,provider,account) DO UPDATE SET
                 channel_id=excluded.channel_id,last_count=excluded.last_count,
                 enabled=1,updated_at=CURRENT_TIMESTAMP""",
            (guild_id, provider, account, str(channel_id), count),
        )
        db.commit()

    async def _send_change(self, channel_id: int, provider: str, account: str, previous: int, current: int):
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"Zielkanal {channel_id} nicht gefunden")
        await channel.send(embed=make_count_embed(provider, account, previous, current))

    async def _track(self, guild_id: str, provider: str, account: str, channel_id: int):
        if provider == "youtube":
            current = await asyncio.to_thread(youtube_subscriber_count, account)
        else:
            # Twitch's subscription endpoint requires the broadcaster to match
            # the authorized user behind TWITCH_USER_ACCESS_TOKEN.
            from cogs.social import twitch_user
            user = await asyncio.to_thread(twitch_user, account)
            broadcaster_id = str(user["id"])
            current = await asyncio.to_thread(twitch_subscriber_count, broadcaster_id)

        previous = self._get_previous(guild_id, provider, account)
        self._save_count(guild_id, provider, account, channel_id, current)
        if should_announce(previous, current):
            await self._send_change(channel_id, provider, account, previous, current)

    @tasks.loop(seconds=POLL_SECONDS)
    async def poll(self):
        for _, guild_id, provider, account, channel_id in self._configured_sources():
            try:
                await self._track(guild_id, provider, account, channel_id)
            except Exception as exc:
                logger.warning("Subscriber tracking failed for %s/%s: %s", provider, account, exc)

    @poll.before_loop
    async def _before_poll(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(SubscriptionTrackerCog(bot))
