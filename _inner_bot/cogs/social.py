"""Modular creator alerts for YouTube, Twitch and X.

This implementation is intentionally independent. It uses public feeds/APIs,
persistent deduplication and small provider helpers that are easy to test.
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.db import get_db
from core.logging import logger

POLL_SECONDS = max(30, int(os.environ.get("NOTIFY_POLL_SECONDS", "60")))
TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "").strip()
TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
X_BEARER_TOKEN = os.environ.get("X_BEARER_TOKEN", "").strip()

YOUTUBE_NS = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/yt"}


def normalize_account(provider: str, account: str) -> str:
    value = account.strip()
    if provider == "youtube":
        match = re.search(r"/channel/(UC[a-zA-Z0-9_-]+)", value)
        if match:
            return match.group(1)
        return value.rstrip("/").split("/")[-1].lstrip("@")
    if provider in {"twitch", "x"}:
        return value.rstrip("/").split("/")[-1].lstrip("@").lower()
    raise ValueError("Unbekannter Provider")


def _http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 15) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "ScratchAI/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return int(response.status), response.read().decode("utf-8", errors="replace")


def _http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 15) -> dict:
    status, text = _http_get(url, headers=headers, timeout=timeout)
    if status < 200 or status >= 300:
        raise RuntimeError(f"HTTP {status}: {text[:300]}")
    return json.loads(text)


def resolve_youtube_channel_id(account: str) -> str:
    account = normalize_account("youtube", account)
    if re.fullmatch(r"UC[a-zA-Z0-9_-]{20,}", account):
        return account
    _, text = _http_get(f"https://www.youtube.com/@{urllib.parse.quote(account, safe='')}")
    for pattern in (r'"channelId":"(UC[a-zA-Z0-9_-]+)"', r'"externalId":"(UC[a-zA-Z0-9_-]+)"'):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    raise ValueError("YouTube-Kanal-ID nicht gefunden")


def youtube_feed(channel_id: str) -> list[dict]:
    _, text = _http_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={urllib.parse.quote(channel_id)}")
    root = ET.fromstring(text)
    items: list[dict] = []
    for entry in root.findall("atom:entry", YOUTUBE_NS):
        video_id = entry.findtext("yt:videoId", default="", namespaces=YOUTUBE_NS)
        if not video_id:
            continue
        published = entry.findtext("atom:published", default="", namespaces=YOUTUBE_NS)
        link = entry.find("atom:link", YOUTUBE_NS)
        author = entry.find("atom:author/atom:name", YOUTUBE_NS)
        items.append({
            "id": video_id,
            "title": html.unescape(entry.findtext("atom:title", default="", namespaces=YOUTUBE_NS)),
            "url": link.attrib.get("href") if link is not None else f"https://youtu.be/{video_id}",
            "published": published,
            "updated": entry.findtext("atom:updated", default=published, namespaces=YOUTUBE_NS),
            "creator": author.text if author is not None else "YouTube",
        })
    return items


_twitch_token: tuple[str, float] | None = None


def twitch_app_token() -> str:
    global _twitch_token
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        raise RuntimeError("TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET fehlen")
    if _twitch_token and _twitch_token[1] > time.time() + 30:
        return _twitch_token[0]
    body = urllib.parse.urlencode({"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}).encode()
    req = urllib.request.Request("https://id.twitch.tv/oauth2/token", data=body, method="POST")
    with urllib.request.urlopen(req, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = payload["access_token"]
    _twitch_token = (token, time.time() + int(payload.get("expires_in", 3600)))
    return token


def twitch_stream(login: str) -> dict | None:
    token = twitch_app_token()
    headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
    rows = _http_json(f"https://api.twitch.tv/helix/streams?user_login={urllib.parse.quote(login)}", headers=headers).get("data") or []
    return rows[0] if rows else None


def twitch_user(login: str) -> dict:
    token = twitch_app_token()
    headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
    rows = _http_json(f"https://api.twitch.tv/helix/users?login={urllib.parse.quote(login)}", headers=headers).get("data") or []
    if not rows:
        raise ValueError("Twitch-Kanal nicht gefunden")
    return rows[0]


def x_user(username: str) -> dict:
    if not X_BEARER_TOKEN:
        raise RuntimeError("X_BEARER_TOKEN fehlt")
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}", "User-Agent": "ScratchAI/1.0"}
    data = _http_json(f"https://api.x.com/2/users/by/username/{urllib.parse.quote(username.lstrip('@'))}", headers=headers).get("data")
    if not data:
        raise ValueError("X-User nicht gefunden")
    return data


def x_posts(user_id: str, since_id: str | None = None) -> list[dict]:
    if not X_BEARER_TOKEN:
        raise RuntimeError("X_BEARER_TOKEN fehlt")
    params = {"max_results": "10", "tweet.fields": "created_at,text,attachments", "expansions": "attachments.media_keys", "media.fields": "url,preview_image_url,type"}
    if since_id:
        params["since_id"] = since_id
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}", "User-Agent": "ScratchAI/1.0"}
    payload = _http_json("https://api.x.com/2/users/{}/tweets?{}".format(user_id, urllib.parse.urlencode(params)), headers=headers)
    media = {m.get("media_key"): m for m in payload.get("includes", {}).get("media", [])}
    result = []
    for post in payload.get("data", []):
        keys = post.get("attachments", {}).get("media_keys", [])
        result.append({"id": post["id"], "text": post.get("text", ""), "created_at": post.get("created_at", ""), "media": [media[k] for k in keys if k in media]})
    return result


def latest_unseen(items: list[dict], last_seen: str | None) -> list[dict]:
    """Return each unseen item once, in chronological order.

    When last_seen exists in the provider result, everything before it is already
    acknowledged and must never be reposted. Duplicate IDs in a feed are also
    collapsed defensively.
    """
    ordered = sorted(items, key=lambda item: (item.get("published") or item.get("created_at") or "", item.get("id", "")))
    unique: list[dict] = []
    seen: set[str] = set()
    for item in ordered:
        item_id = str(item.get("id") or "")
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)
        unique.append(item)

    if not last_seen:
        return unique

    for index, item in enumerate(unique):
        if item["id"] == str(last_seen):
            return unique[index + 1 :]

    # Provider feeds can drop old entries. If the persisted marker is no longer
    # present, the safest recoverable behavior is to process the currently
    # available window once rather than silently miss everything.
    return unique


@dataclass(slots=True)
class Subscription:
    id: int
    guild_id: int
    provider: str
    account: str
    channel_id: int
    role_id: int | None
    last_seen: str | None
    state: str | None
    enabled: bool


class SocialCog(commands.Cog):
    group = app_commands.Group(name="notify", description="Creator-Benachrichtigungen")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._init_db()
        self.poll.start()

    def cog_unload(self):
        self.poll.cancel()

    def _init_db(self):
        db = get_db()
        db.execute("""CREATE TABLE IF NOT EXISTS social_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            account TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            role_id TEXT,
            last_seen TEXT,
            state TEXT,
            enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, provider, account)
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_social_notifications_enabled ON social_notifications(enabled, provider)")
        db.commit()

    def subscriptions(self) -> list[Subscription]:
        rows = get_db().execute("SELECT id,guild_id,provider,account,channel_id,role_id,last_seen,state,enabled FROM social_notifications WHERE enabled=1").fetchall()
        return [Subscription(int(r[0]), int(r[1]), r[2], r[3], int(r[4]), int(r[5]) if r[5] else None, r[6], r[7], bool(r[8])) for r in rows]

    def _save(self, sub_id: int, last_seen: str | None = None, state: str | None = None):
        db = get_db()
        db.execute("UPDATE social_notifications SET last_seen=COALESCE(?,last_seen), state=COALESCE(?,state) WHERE id=?", (last_seen, state, sub_id))
        db.commit()

    @group.command(name="add", description="Creator-Alert hinzufügen")
    @app_commands.describe(provider="youtube, twitch oder x", account="Kanal/Login/@Name", channel="Discord-Kanal", role="Optionale Ping-Rolle")
    @app_commands.choices(provider=[app_commands.Choice(name="YouTube", value="youtube"), app_commands.Choice(name="Twitch", value="twitch"), app_commands.Choice(name="X", value="x")])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str, channel: discord.TextChannel, role: discord.Role | None = None):
        p = provider.value
        try:
            account = normalize_account(p, account)
            if p == "youtube":
                account = await asyncio.to_thread(resolve_youtube_channel_id, account)
            elif p == "twitch":
                account = (await asyncio.to_thread(twitch_user, account)).get("login", account).lower()
            else:
                account = (await asyncio.to_thread(x_user, account)).get("username", account).lower()
        except Exception as exc:
            await interaction.response.send_message(f"❌ Prüfung fehlgeschlagen: `{exc}`", ephemeral=True)
            return
        db = get_db()
        try:
            db.execute("INSERT INTO social_notifications(guild_id,provider,account,channel_id,role_id) VALUES(?,?,?,?,?)", (str(interaction.guild_id), p, account, str(channel.id), str(role.id) if role else None))
            db.commit()
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                await interaction.response.send_message("⚠️ Dieser Creator ist bereits eingerichtet.", ephemeral=True)
                return
            raise
        await interaction.response.send_message(f"✅ **{p.upper()}** `{account}` → {channel.mention} eingerichtet.", ephemeral=True)

    @group.command(name="remove", description="Creator-Alert entfernen")
    @app_commands.describe(provider="Provider", account="Kanal/Login/@Name")
    @app_commands.choices(provider=[app_commands.Choice(name="YouTube", value="youtube"), app_commands.Choice(name="Twitch", value="twitch"), app_commands.Choice(name="X", value="x")])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str):
        p = provider.value
        account = normalize_account(p, account)
        if p == "youtube" and not account.startswith("UC"):
            try:
                account = await asyncio.to_thread(resolve_youtube_channel_id, account)
            except Exception:
                pass
        db = get_db()
        cur = db.execute("DELETE FROM social_notifications WHERE guild_id=? AND provider=? AND account=?", (str(interaction.guild_id), p, account))
        db.commit()
        await interaction.response.send_message("🗑️ Entfernt." if cur.rowcount else "⚠️ Nicht gefunden.", ephemeral=True)

    @group.command(name="list", description="Creator-Alerts anzeigen")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_(self, interaction: discord.Interaction):
        rows = get_db().execute("SELECT provider,account,channel_id,role_id,enabled FROM social_notifications WHERE guild_id=? ORDER BY provider,account", (str(interaction.guild_id),)).fetchall()
        if not rows:
            await interaction.response.send_message("📡 Keine Creator-Alerts eingerichtet.", ephemeral=True)
            return
        lines = []
        for p, account, channel_id, role_id, enabled in rows:
            channel = interaction.guild.get_channel(int(channel_id))
            lines.append(f"{'🟢' if enabled else '⏸️'} **{p}** `{account}` → {channel.mention if channel else '#gelöscht'}" + (f" · <@&{role_id}>" if role_id else ""))
        await interaction.response.send_message("📡 **Creator Alerts**\n" + "\n".join(lines), ephemeral=True)

    @group.command(name="test", description="Test-Alert senden")
    @app_commands.describe(provider="Provider", account="Kanal/Login/@Name")
    @app_commands.choices(provider=[app_commands.Choice(name="YouTube", value="youtube"), app_commands.Choice(name="Twitch", value="twitch"), app_commands.Choice(name="X", value="x")])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str):
        p = provider.value
        account = normalize_account(p, account)
        row = get_db().execute("SELECT channel_id,role_id FROM social_notifications WHERE guild_id=? AND provider=? AND account=?", (str(interaction.guild_id), p, account)).fetchone()
        if not row:
            await interaction.response.send_message("❌ Creator nicht eingerichtet.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(int(row[0]))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ Zielkanal nicht gefunden.", ephemeral=True)
            return
        embed = discord.Embed(title=f"📡 {p.upper()} Test", description=f"Alert-System für `{account}` funktioniert.", timestamp=datetime.now(timezone.utc), color=discord.Color.blurple())
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Test in {channel.mention} gesendet.", ephemeral=True)

    @tasks.loop(seconds=POLL_SECONDS)
    async def poll(self):
        for sub in self.subscriptions():
            try:
                if sub.provider == "youtube":
                    await self._youtube(sub)
                elif sub.provider == "twitch":
                    await self._twitch(sub)
                elif sub.provider == "x":
                    await self._x(sub)
            except Exception:
                logger.exception("Social alert failed: %s/%s", sub.provider, sub.account)

    @poll.before_loop
    async def _before_poll(self):
        await self.bot.wait_until_ready()

    async def _send(self, sub: Subscription, embed: discord.Embed):
        channel = self.bot.get_channel(sub.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        role = channel.guild.get_role(sub.role_id) if sub.role_id else None
        await channel.send(content=role.mention if role else None, embed=embed, allowed_mentions=discord.AllowedMentions(roles=bool(role), everyone=False, users=False))

    async def _youtube(self, sub: Subscription):
        items = await asyncio.to_thread(youtube_feed, sub.account)
        unseen = latest_unseen(items, sub.last_seen)
        if not unseen:
            if items and not sub.last_seen:
                self._save(sub.id, last_seen=items[-1]["id"])
            return
        for item in unseen:
            embed = discord.Embed(title="📺 Neues YouTube-Video", description=f"**{item['title']}**\n{item['url']}", url=item["url"], timestamp=datetime.now(timezone.utc), color=discord.Color.red())
            embed.set_footer(text=item.get("creator") or "YouTube")
            await self._send(sub, embed)
        self._save(sub.id, last_seen=unseen[-1]["id"])

    async def _twitch(self, sub: Subscription):
        stream = await asyncio.to_thread(twitch_stream, sub.account)
        if not stream:
            if sub.state != "offline":
                self._save(sub.id, state="offline")
            return
        stream_id = str(stream.get("id", ""))
        if sub.state != stream_id:
            url = f"https://twitch.tv/{sub.account}"
            embed = discord.Embed(title="🔴 Twitch ist live", description=f"**{stream.get('title') or 'Twitch Stream'}**\n🎮 {stream.get('game_name') or 'Unbekannte Kategorie'}\n👀 {stream.get('viewer_count', 0)} Zuschauer\n{url}", url=url, timestamp=datetime.now(timezone.utc), color=discord.Color.purple())
            thumb = stream.get("thumbnail_url")
            if thumb:
                embed.set_image(url=thumb.replace("{width}", "640").replace("{height}", "360"))
            await self._send(sub, embed)
            self._save(sub.id, state=stream_id)

    async def _x(self, sub: Subscription):
        user = await asyncio.to_thread(x_user, sub.account)
        posts = await asyncio.to_thread(x_posts, user["id"], sub.last_seen)
        normalized = [{**post, "published": post.get("created_at")} for post in posts]
        unseen = latest_unseen(normalized, sub.last_seen)
        if not unseen:
            if posts and not sub.last_seen:
                self._save(sub.id, last_seen=posts[-1]["id"])
            return
        for post in unseen:
            url = f"https://x.com/{user.get('username', sub.account)}/status/{post['id']}"
            embed = discord.Embed(title=f"𝕏 Neuer Post von @{user.get('username', sub.account)}", description=f"{(post.get('text') or 'Neuer Post')[:3500]}\n\n{url}", url=url, timestamp=datetime.now(timezone.utc), color=discord.Color.dark_grey())
            for media in post.get("media", [])[:1]:
                preview = media.get("preview_image_url") or media.get("url")
                if preview:
                    embed.set_image(url=preview)
            await self._send(sub, embed)
        self._save(sub.id, last_seen=unseen[-1]["id"])


async def setup(bot: commands.Bot):
    await bot.add_cog(SocialCog(bot))
