"""Creator-/Social-Notifications für YouTube, Twitch und X.

Bewusst eigenständig implementiert: keine Übernahme von Red-Code.
- YouTube: RSS + öffentliche Kanalauflösung
- Twitch: offizielle Helix API (Client-Credentials)
- X: offizielle API v2 (Bearer Token)

Die Cog pollt mit einem konservativen Intervall, dedupliziert persistent
und postet neue Inhalte als Discord-Embeds in den konfigurierten Kanal.
"""
from __future__ import annotations

import asyncio
import html
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

YOUTUBE_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/yt",
}


def _http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 15) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "ScratchAI/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return int(response.status), response.read().decode("utf-8", errors="replace")


def _http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 15) -> dict:
    status, text = _http_get(url, headers=headers, timeout=timeout)
    if status < 200 or status >= 300:
        raise RuntimeError(f"HTTP {status}: {text[:300]}")
    import json
    return json.loads(text)


def _normalize_account(provider: str, account: str) -> str:
    value = account.strip()
    if provider == "youtube":
        match = re.search(r"(?:channel/|@)(UC[a-zA-Z0-9_-]{20,})", value)
        if match and match.group(1).startswith("UC"):
            return match.group(1)
        match = re.search(r"channel/(UC[a-zA-Z0-9_-]+)", value)
        if match:
            return match.group(1)
    if provider == "twitch":
        value = value.rstrip("/").split("/")[-1]
    if provider == "x":
        value = value.rstrip("/").split("/")[-1].lstrip("@")
    return value


def _resolve_youtube_channel_id(account: str) -> str:
    account = account.strip()
    if re.fullmatch(r"UC[a-zA-Z0-9_-]{20,}", account):
        return account
    encoded = urllib.parse.quote(account.lstrip("@"), safe="")
    url = f"https://www.youtube.com/@{encoded}"
    _, text = _http_get(url)
    patterns = [
        r'"channelId":"(UC[a-zA-Z0-9_-]+)"',
        r'"externalId":"(UC[a-zA-Z0-9_-]+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    raise ValueError("YouTube-Kanal-ID konnte nicht gefunden werden. Nutze am besten die UC... Kanal-ID.")


def _youtube_items(channel_id: str) -> list[dict]:
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={urllib.parse.quote(channel_id)}"
    _, text = _http_get(url)
    root = ET.fromstring(text)
    items = []
    for entry in root.findall("atom:entry", YOUTUBE_NS):
        video_id = entry.findtext("yt:videoId", default="", namespaces=YOUTUBE_NS)
        title = html.unescape(entry.findtext("atom:title", default="", namespaces=YOUTUBE_NS))
        published = entry.findtext("atom:published", default="", namespaces=YOUTUBE_NS)
        link = entry.find("atom:link", YOUTUBE_NS)
        href = link.attrib.get("href", f"https://youtu.be/{video_id}") if link is not None else f"https://youtu.be/{video_id}"
        author = entry.find("atom:author/atom:name", YOUTUBE_NS)
        creator = author.text if author is not None else "YouTube"
        if video_id:
            items.append({"id": video_id, "title": title, "url": href, "published": published, "creator": creator})
    return items


_twitch_token_cache: dict[str, tuple[str, float]] = {}


def _twitch_token() -> str:
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        raise RuntimeError("TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET fehlen")
    cached = _twitch_token_cache.get(TWITCH_CLIENT_ID)
    if cached and cached[1] > time.time() + 30:
        return cached[0]
    data = urllib.parse.urlencode({"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}).encode()
    req = urllib.request.Request("https://id.twitch.tv/oauth2/token", data=data, method="POST", headers={"User-Agent": "ScratchAI/1.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        import json
        payload = json.loads(response.read().decode())
    token = payload["access_token"]
    _twitch_token_cache[TWITCH_CLIENT_ID] = (token, time.time() + int(payload.get("expires_in", 3600)))
    return token


def _twitch_stream(login: str) -> dict | None:
    token = _twitch_token()
    headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
    data = _http_json(f"https://api.twitch.tv/helix/streams?user_login={urllib.parse.quote(login)}", headers=headers)
    rows = data.get("data", [])
    return rows[0] if rows else None


def _x_user(username: str) -> dict:
    if not X_BEARER_TOKEN:
        raise RuntimeError("X_BEARER_TOKEN fehlt")
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}", "User-Agent": "ScratchAI/1.0"}
    return _http_json(f"https://api.x.com/2/users/by/username/{urllib.parse.quote(username.lstrip('@'))}", headers=headers).get("data", {})


def _x_posts(user_id: str, since_id: str | None = None) -> list[dict]:
    params = {
        "max_results": "10",
        "tweet.fields": "created_at,public_metrics,attachments,text",
        "expansions": "attachments.media_keys",
        "media.fields": "url,preview_image_url,type,width,height",
    }
    if since_id:
        params["since_id"] = since_id
    url = "https://api.x.com/2/users/{}/tweets?{}".format(user_id, urllib.parse.urlencode(params))
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}", "User-Agent": "ScratchAI/1.0"}
    payload = _http_json(url, headers=headers)
    media = {m.get("media_key"): m for m in payload.get("includes", {}).get("media", [])}
    result = []
    for post in payload.get("data", []):
        result.append({"id": post["id"], "text": post.get("text", ""), "created_at": post.get("created_at", ""), "media": list(media.values())})
    return result


@dataclass
class Subscription:
    id: int
    guild_id: int
    provider: str
    account: str
    channel_id: int
    role_id: int | None
    last_seen: str | None
    enabled: bool


class NotifyCog(commands.Cog):
    """Unified creator notification service."""

    notify_group = app_commands.Group(name="notify", description="YouTube-, Twitch- und X-Benachrichtigungen")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._init_schema()
        self.poll_loop.start()

    def cog_unload(self):
        self.poll_loop.cancel()

    def _init_schema(self):
        db = get_db()
        db.execute("""CREATE TABLE IF NOT EXISTS creator_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            account TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            role_id TEXT,
            last_seen TEXT,
            enabled BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(guild_id, provider, account)
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS idx_creator_notifications_enabled ON creator_notifications(enabled, provider)")
        db.commit()

    def _subscriptions(self) -> list[Subscription]:
        rows = get_db().execute("SELECT id,guild_id,provider,account,channel_id,role_id,last_seen,enabled FROM creator_notifications WHERE enabled=1").fetchall()
        return [Subscription(int(r[0]), int(r[1]), r[2], r[3], int(r[4]), int(r[5]) if r[5] else None, r[6], bool(r[7])) for r in rows]

    @app_commands.command(name="add", description="Creator zur Benachrichtigung hinzufügen")
    @app_commands.describe(provider="youtube, twitch oder x", account="Kanal/Login/@Name", channel="Discord-Kanal", role="Optional: Rolle pingen")
    @app_commands.choices(provider=[
        app_commands.Choice(name="YouTube", value="youtube"),
        app_commands.Choice(name="Twitch", value="twitch"),
        app_commands.Choice(name="X", value="x"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str, channel: discord.TextChannel, role: discord.Role | None = None):
        p = provider.value
        account = _normalize_account(p, account)
        try:
            if p == "youtube":
                account = await asyncio.to_thread(_resolve_youtube_channel_id, account)
            elif p == "x":
                user = await asyncio.to_thread(_x_user, account)
                account = user.get("username", account)
            else:
                account = account.lower()
        except Exception as exc:
            await interaction.response.send_message(f"❌ Creator konnte nicht geprüft werden: `{exc}`", ephemeral=True)
            return
        db = get_db()
        try:
            db.execute("INSERT INTO creator_notifications(guild_id,provider,account,channel_id,role_id) VALUES(?,?,?,?,?)", (str(interaction.guild_id), p, account, str(channel.id), str(role.id) if role else None))
            db.commit()
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                await interaction.response.send_message("⚠️ Dieser Creator ist bereits eingerichtet.", ephemeral=True)
                return
            raise
        await interaction.response.send_message(f"✅ **{p.upper()}** `{account}` → {channel.mention} eingerichtet." + (f" Ping: {role.mention}" if role else ""), ephemeral=True)

    @app_commands.command(name="remove", description="Creator-Benachrichtigung entfernen")
    @app_commands.describe(provider="youtube, twitch oder x", account="Kanal/Login/@Name")
    @app_commands.choices(provider=[
        app_commands.Choice(name="YouTube", value="youtube"),
        app_commands.Choice(name="Twitch", value="twitch"),
        app_commands.Choice(name="X", value="x"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str):
        p = provider.value
        account = _normalize_account(p, account)
        if p == "youtube" and not account.startswith("UC"):
            try:
                account = await asyncio.to_thread(_resolve_youtube_channel_id, account)
            except Exception:
                pass
        db = get_db()
        cur = db.execute("DELETE FROM creator_notifications WHERE guild_id=? AND provider=? AND account=?", (str(interaction.guild_id), p, account.lower() if p != "youtube" else account))
        db.commit()
        await interaction.response.send_message("🗑️ Entfernt." if cur.rowcount else "⚠️ Nicht gefunden.", ephemeral=True)

    @app_commands.command(name="list", description="Aktive Creator-Benachrichtigungen anzeigen")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_(self, interaction: discord.Interaction):
        rows = get_db().execute("SELECT provider,account,channel_id,role_id,enabled FROM creator_notifications WHERE guild_id=? ORDER BY provider,account", (str(interaction.guild_id),)).fetchall()
        if not rows:
            await interaction.response.send_message("Noch keine Creator-Benachrichtigungen eingerichtet.", ephemeral=True)
            return
        lines = []
        for p, account, channel_id, role_id, enabled in rows:
            channel = interaction.guild.get_channel(int(channel_id))
            role = interaction.guild.get_role(int(role_id)) if role_id else None
            lines.append(f"{'🟢' if enabled else '⏸️'} **{p}** `{account}` → {channel.mention if channel else '#gelöscht'}" + (f" · {role.mention}" if role else ""))
        await interaction.response.send_message("📡 **Creator Notifications**\n" + "\n".join(lines), ephemeral=True)

    @app_commands.command(name="test", description="Testnachricht für einen Creator senden")
    @app_commands.describe(provider="youtube, twitch oder x", account="Kanal/Login/@Name")
    @app_commands.choices(provider=[
        app_commands.Choice(name="YouTube", value="youtube"),
        app_commands.Choice(name="Twitch", value="twitch"),
        app_commands.Choice(name="X", value="x"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str):
        account = _normalize_account(provider.value, account)
        row = get_db().execute("SELECT channel_id,role_id FROM creator_notifications WHERE guild_id=? AND provider=? AND account=?", (str(interaction.guild_id), provider.value, account)).fetchone()
        if not row:
            await interaction.response.send_message("❌ Creator ist nicht eingerichtet.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(int(row[0]))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ Zielkanal existiert nicht mehr.", ephemeral=True)
            return
        embed = discord.Embed(title=f"📡 Test: {provider.name} — {account}", description="Die Creator-Benachrichtigungen funktionieren.", timestamp=datetime.now(timezone.utc))
        await channel.send(embed=embed)
        await interaction.response.send_message(f"✅ Test in {channel.mention} gesendet.", ephemeral=True)

    @tasks.loop(seconds=POLL_SECONDS)
    async def poll_loop(self):
        for sub in self._subscriptions():
            try:
                if sub.provider == "youtube":
                    await self._poll_youtube(sub)
                elif sub.provider == "twitch":
                    await self._poll_twitch(sub)
                elif sub.provider == "x":
                    await self._poll_x(sub)
            except Exception:
                logger.exception("Creator notification failed: %s/%s", sub.provider, sub.account)

    @poll_loop.before_loop
    async def before_poll_loop(self):
        await self.bot.wait_until_ready()

    async def _send(self, sub: Subscription, embed: discord.Embed):
        channel = self.bot.get_channel(sub.channel_id)
        if not isinstance(channel, discord.TextChannel):
            return
        role = channel.guild.get_role(sub.role_id) if sub.role_id else None
        content = role.mention if role else None
        allowed = discord.AllowedMentions(roles=True) if role else discord.AllowedMentions.none()
        await channel.send(content=content, embed=embed, allowed_mentions=allowed)

    def _set_seen(self, sub_id: int, value: str):
        db = get_db()
        db.execute("UPDATE creator_notifications SET last_seen=? WHERE id=?", (value, sub_id))
        db.commit()

    async def _poll_youtube(self, sub: Subscription):
        items = await asyncio.to_thread(_youtube_items, sub.account)
        items.sort(key=lambda x: x.get("published", ""))
        if not items:
            return
        if not sub.last_seen:
            self._set_seen(sub.id, items[-1]["id"])
            return
        unseen = []
        for item in items:
            if item["id"] == sub.last_seen:
                break
            unseen.append(item)
        for item in reversed(unseen):
            embed = discord.Embed(title=f"🎬 {item['title']}", url=item["url"], description=f"Neues YouTube-Video von **{item['creator']}**")
            if item.get("published"):
                try: embed.timestamp = datetime.fromisoformat(item["published"].replace("Z", "+00:00"))
                except ValueError: pass
            await self._send(sub, embed)
        self._set_seen(sub.id, items[-1]["id"])

    async def _poll_twitch(self, sub: Subscription):
        stream = await asyncio.to_thread(_twitch_stream, sub.account)
        current_id = str(stream["id"]) if stream else "offline"
        if not sub.last_seen:
            self._set_seen(sub.id, current_id)
            return
        if stream and sub.last_seen != current_id:
            embed = discord.Embed(title=f"🔴 {stream.get('user_name', sub.account)} ist LIVE!", url=f"https://twitch.tv/{sub.account}", description=stream.get("title") or "Live auf Twitch")
            embed.add_field(name="Kategorie", value=stream.get("game_name") or "Unbekannt", inline=True)
            embed.add_field(name="Zuschauer", value=str(stream.get("viewer_count", 0)), inline=True)
            thumb = stream.get("thumbnail_url", "").replace("{width}", "640").replace("{height}", "360")
            if thumb: embed.set_image(url=thumb)
            await self._send(sub, embed)
        self._set_seen(sub.id, current_id)

    async def _poll_x(self, sub: Subscription):
        user = await asyncio.to_thread(_x_user, sub.account)
        posts = await asyncio.to_thread(_x_posts, user["id"], sub.last_seen if sub.last_seen and sub.last_seen != "offline" else None)
        if not posts:
            if not sub.last_seen: self._set_seen(sub.id, "offline")
            return
        posts.sort(key=lambda x: x["id"])
        for post in posts:
            url = f"https://x.com/{user.get('username', sub.account)}/status/{post['id']}"
            text = post.get("text", "")[:4000]
            embed = discord.Embed(title=f"𝕏 Neuer Post von @{user.get('username', sub.account)}", url=url, description=text)
            if post.get("created_at"):
                try: embed.timestamp = datetime.fromisoformat(post["created_at"].replace("Z", "+00:00"))
                except ValueError: pass
            await self._send(sub, embed)
        self._set_seen(sub.id, posts[-1]["id"])


async def setup(bot: commands.Bot):
    await bot.add_cog(NotifyCog(bot))
