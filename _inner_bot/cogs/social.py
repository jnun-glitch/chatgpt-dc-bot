"""Creator alerts for YouTube, Twitch and X.

YouTube and Twitch use persistent event state. The first poll initializes the
current feed/state without replaying old events. Later polls announce only new
YouTube uploads/live events and new Twitch stream sessions.
"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
import time
import urllib.error
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


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Env-Variable %s ist keine gültige Zahl (%r) – Default %s verwendet.", name, raw, default)
        return default
    return max(minimum, value)


POLL_SECONDS = _env_int("NOTIFY_POLL_SECONDS", 60, 30)
TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "").strip()
TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
X_BEARER_TOKEN = os.environ.get("X_BEARER_TOKEN", "").strip()

YOUTUBE_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/yt",
}


def normalize_account(provider: str, account: str) -> str:
    value = account.strip()
    if not value:
        raise ValueError("Account darf nicht leer sein")
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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return int(response.status), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body[:300]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Netzwerkfehler: {exc.reason}") from exc


def _http_json(url: str, headers: dict[str, str] | None = None, timeout: int = 15) -> dict:
    status, text = _http_get(url, headers=headers, timeout=timeout)
    if status < 200 or status >= 300:
        raise RuntimeError(f"HTTP {status}: {text[:300]}")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Ungültige JSON-Antwort") from exc


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
    _, text = _http_get(
        f"https://www.youtube.com/feeds/videos.xml?channel_id={urllib.parse.quote(channel_id)}"
    )
    root = ET.fromstring(text)
    items: list[dict] = []
    for entry in root.findall("atom:entry", YOUTUBE_NS):
        video_id = entry.findtext("yt:videoId", default="", namespaces=YOUTUBE_NS)
        if not video_id:
            continue
        published = entry.findtext("atom:published", default="", namespaces=YOUTUBE_NS)
        link = entry.find("atom:link", YOUTUBE_NS)
        author = entry.find("atom:author", YOUTUBE_NS)
        author_name = (
            author.findtext("atom:name", default="YouTube", namespaces=YOUTUBE_NS)
            if author is not None
            else "YouTube"
        )
        items.append({
            "id": video_id,
            "title": html.unescape(entry.findtext("atom:title", default="", namespaces=YOUTUBE_NS)),
            "url": link.attrib.get("href") if link is not None else f"https://youtu.be/{video_id}",
            "published": published,
            "updated": entry.findtext("atom:updated", default=published, namespaces=YOUTUBE_NS),
            "creator": author_name,
        })
    return items


def youtube_video_state(video_id: str) -> dict[str, bool]:
    """Best-effort classification of a public YouTube watch page."""
    try:
        _, text = _http_get(f"https://www.youtube.com/watch?v={urllib.parse.quote(video_id)}")
    except Exception:
        return {"is_live_content": False, "is_live_now": False}

    def _bool(pattern: str) -> bool:
        match = re.search(pattern, text)
        return bool(match and match.group(1).lower() == "true")

    live_now = _bool(r'"isLiveNow":(true|false)')
    live_content = _bool(r'"isLiveContent":(true|false)')
    if not live_content:
        live_content = bool(re.search(r'"liveBroadcastDetails"\s*:', text))
    return {"is_live_content": live_content, "is_live_now": live_now}


def youtube_kind(video_state: dict) -> str:
    return "live" if video_state.get("is_live_content") and video_state.get("is_live_now") else "video"


def youtube_initial_marker(items: list[dict]) -> str | None:
    """Return the newest feed ID used to seed a new subscription without alerts."""
    ordered = sorted(
        (item for item in items if item.get("id")),
        key=lambda item: (str(item.get("published") or ""), str(item.get("id") or "")),
    )
    return str(ordered[-1]["id"]) if ordered else None


def twitch_should_notify(previous_state: str | None, stream_id: str) -> bool:
    return bool(stream_id) and previous_state != stream_id


def youtube_thumbnail(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{urllib.parse.quote(video_id, safe='')}/hqdefault.jpg"


def make_youtube_embed(item: dict, kind: str = "video") -> discord.Embed:
    is_live = kind == "live"
    title = "🔴 YouTube ist LIVE!" if is_live else "📺 Neues YouTube-Video"
    url = item["url"]
    embed = discord.Embed(
        title=title,
        description=f"**{item.get('title') or 'Neuer Upload'}**",
        url=url,
        timestamp=datetime.now(timezone.utc),
        color=discord.Color.red(),
    )
    embed.set_image(url=youtube_thumbnail(item["id"]))
    embed.add_field(name="🔗 Anschauen", value=f"[YouTube öffnen]({url})", inline=False)
    embed.set_footer(text=item.get("creator") or "YouTube")
    return embed


def make_twitch_embed(stream: dict, account: str) -> discord.Embed:
    url = f"https://twitch.tv/{account}"
    embed = discord.Embed(
        title="🔴 Twitch ist LIVE!",
        description=f"**{stream.get('title') or 'Twitch Stream'}**",
        url=url,
        timestamp=datetime.now(timezone.utc),
        color=discord.Color.purple(),
    )
    embed.add_field(name="🎮 Kategorie", value=str(stream.get("game_name") or "Unbekannt"), inline=True)
    embed.add_field(name="👀 Zuschauer", value=f"{int(stream.get('viewer_count') or 0):,}", inline=True)
    embed.add_field(name="🔗 Stream", value=f"[Twitch öffnen]({url})", inline=False)
    thumb = stream.get("thumbnail_url")
    if thumb:
        embed.set_image(url=thumb.replace("{width}", "640").replace("{height}", "360"))
    embed.set_footer(text=stream.get("user_name") or account)
    return embed


_twitch_token: tuple[str, float] | None = None


def twitch_app_token() -> str:
    global _twitch_token
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        raise RuntimeError("TWITCH_CLIENT_ID/TWITCH_CLIENT_SECRET fehlen")
    if _twitch_token and _twitch_token[1] > time.time() + 30:
        return _twitch_token[0]
    body = urllib.parse.urlencode({
        "client_id": TWITCH_CLIENT_ID,
        "client_secret": TWITCH_CLIENT_SECRET,
        "grant_type": "client_credentials",
    }).encode()
    req = urllib.request.Request("https://id.twitch.tv/oauth2/token", data=body, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Twitch Token HTTP {exc.code}: {body_text[:200]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Twitch Token Netzwerkfehler: {exc.reason}") from exc
    token = str(payload.get("access_token") or "")
    if not token:
        raise RuntimeError("Twitch API lieferte keinen Access-Token")
    _twitch_token = (token, time.time() + int(payload.get("expires_in", 3600)))
    return token


def twitch_stream(login: str) -> dict | None:
    token = twitch_app_token()
    headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
    rows = _http_json(
        f"https://api.twitch.tv/helix/streams?user_login={urllib.parse.quote(login)}", headers=headers
    ).get("data") or []
    return rows[0] if rows else None


def twitch_user(login: str) -> dict:
    token = twitch_app_token()
    headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
    rows = _http_json(
        f"https://api.twitch.tv/helix/users?login={urllib.parse.quote(login)}", headers=headers
    ).get("data") or []
    if not rows:
        raise ValueError("Twitch-Kanal nicht gefunden")
    return rows[0]


def x_user(username: str) -> dict:
    if not X_BEARER_TOKEN:
        raise RuntimeError("X_BEARER_TOKEN fehlt")
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}", "User-Agent": "ScratchAI/1.0"}
    data = _http_json(
        f"https://api.x.com/2/users/by/username/{urllib.parse.quote(username.lstrip('@'))}", headers=headers
    ).get("data")
    if not data:
        raise ValueError("X-User nicht gefunden")
    return data


def x_posts(user_id: str, since_id: str | None = None) -> list[dict]:
    if not X_BEARER_TOKEN:
        raise RuntimeError("X_BEARER_TOKEN fehlt")
    params = {
        "max_results": "10",
        "tweet.fields": "created_at,text,attachments",
        "expansions": "attachments.media_keys",
        "media.fields": "url,preview_image_url,type",
    }
    if since_id:
        params["since_id"] = since_id
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}", "User-Agent": "ScratchAI/1.0"}
    payload = _http_json(
        "https://api.x.com/2/users/{}/tweets?{}".format(user_id, urllib.parse.urlencode(params)), headers=headers
    )
    media = {m.get("media_key"): m for m in payload.get("includes", {}).get("media", [])}
    result = []
    for post in payload.get("data", []):
        keys = post.get("attachments", {}).get("media_keys", [])
        result.append({
            "id": post["id"],
            "text": post.get("text", ""),
            "created_at": post.get("created_at", ""),
            "media": [media[k] for k in keys if k in media],
        })
    return result


def latest_unseen(items: list[dict], last_seen: str | None) -> list[dict]:
    """Return each unseen item once, in chronological order."""
    ordered = sorted(
        items,
        key=lambda item: (0, str(item.get("published") or item.get("created_at") or ""), str(item.get("id") or ""))
        if item.get("published") or item.get("created_at")
        else (1, "", str(item.get("id") or "")),
    )
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
    marker = str(last_seen)
    for index, item in enumerate(unique):
        if item["id"] == marker:
            return unique[index + 1 :]
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
        rows = get_db().execute(
            "SELECT id,guild_id,provider,account,channel_id,role_id,last_seen,state,enabled "
            "FROM social_notifications WHERE enabled=1"
        ).fetchall()
        return [
            Subscription(int(r[0]), int(r[1]), r[2], r[3], int(r[4]), int(r[5]) if r[5] else None, r[6], r[7], bool(r[8]))
            for r in rows
        ]

    def _save(self, sub_id: int, last_seen: str | None = None, state: str | None = None):
        db = get_db()
        db.execute(
            "UPDATE social_notifications SET last_seen=COALESCE(?,last_seen), state=COALESCE(?,state) WHERE id=?",
            (last_seen, state, sub_id),
        )
        db.commit()

    async def _resolve_lookup_account(self, provider: str, account: str) -> str:
        normalized = normalize_account(provider, account)
        if provider == "youtube":
            return await asyncio.to_thread(resolve_youtube_channel_id, normalized)
        if provider == "twitch":
            return (await asyncio.to_thread(twitch_user, normalized)).get("login", normalized).lower()
        return (await asyncio.to_thread(x_user, normalized)).get("username", normalized).lower()

    @group.command(name="add", description="Creator-Alert hinzufügen")
    @app_commands.describe(provider="youtube, twitch oder x", account="Kanal/Login/@Name", channel="Discord-Kanal", role="Optionale Ping-Rolle")
    @app_commands.choices(provider=[
        app_commands.Choice(name="YouTube", value="youtube"),
        app_commands.Choice(name="Twitch", value="twitch"),
        app_commands.Choice(name="X", value="x"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str, channel: discord.TextChannel, role: discord.Role | None = None):
        p = provider.value
        try:
            account = await self._resolve_lookup_account(p, account)
        except Exception as exc:
            await interaction.response.send_message(f"❌ Prüfung fehlgeschlagen: `{exc}`", ephemeral=True)
            return
        db = get_db()
        try:
            db.execute(
                "INSERT INTO social_notifications(guild_id,provider,account,channel_id,role_id) VALUES(?,?,?,?,?)",
                (str(interaction.guild_id), p, account, str(channel.id), str(role.id) if role else None),
            )
            db.commit()
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                await interaction.response.send_message("⚠️ Dieser Creator ist bereits eingerichtet.", ephemeral=True)
                return
            raise
        await interaction.response.send_message(f"✅ **{p.upper()}** `{account}` → {channel.mention} eingerichtet.", ephemeral=True)

    @group.command(name="remove", description="Creator-Alert entfernen")
    @app_commands.describe(provider="Provider", account="Kanal/Login/@Name")
    @app_commands.choices(provider=[
        app_commands.Choice(name="YouTube", value="youtube"),
        app_commands.Choice(name="Twitch", value="twitch"),
        app_commands.Choice(name="X", value="x"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str):
        p = provider.value
        try:
            account = await self._resolve_lookup_account(p, account)
        except Exception:
            account = normalize_account(p, account)
        db = get_db()
        cur = db.execute(
            "DELETE FROM social_notifications WHERE guild_id=? AND provider=? AND account=?",
            (str(interaction.guild_id), p, account),
        )
        db.commit()
        await interaction.response.send_message("🗑️ Entfernt." if cur.rowcount else "⚠️ Nicht gefunden.", ephemeral=True)

    @group.command(name="list", description="Creator-Alerts anzeigen")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_(self, interaction: discord.Interaction):
        rows = get_db().execute(
            "SELECT provider,account,channel_id,role_id,enabled FROM social_notifications "
            "WHERE guild_id=? ORDER BY provider,account",
            (str(interaction.guild_id),),
        ).fetchall()
        if not rows:
            await interaction.response.send_message("📡 Keine Creator-Alerts eingerichtet.", ephemeral=True)
            return
        chunks: list[str] = []
        current = "📡 **Creator Alerts**\n"
        for p, account, channel_id, role_id, enabled in rows:
            channel = interaction.guild.get_channel(int(channel_id))
            line = f"{'🟢' if enabled else '⏸️'} **{p}** `{account}` → {channel.mention if channel else '#gelöscht'}"
            if role_id:
                line += f" · <@&{role_id}>"
            if len(current) + len(line) + 1 > 1900:
                chunks.append(current.rstrip())
                current = ""
            current += line + "\n"
        if current.strip():
            chunks.append(current.rstrip())
        await interaction.response.send_message(chunks[0], ephemeral=True)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)

    @group.command(name="test", description="Test-Alert senden")
    @app_commands.describe(provider="Provider", account="Kanal/Login/@Name")
    @app_commands.choices(provider=[
        app_commands.Choice(name="YouTube", value="youtube"),
        app_commands.Choice(name="Twitch", value="twitch"),
        app_commands.Choice(name="X", value="x"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str):
        p = provider.value
        try:
            account = await self._resolve_lookup_account(p, account)
        except Exception:
            account = normalize_account(p, account)
        row = get_db().execute(
            "SELECT channel_id,role_id FROM social_notifications WHERE guild_id=? AND provider=? AND account=?",
            (str(interaction.guild_id), p, account),
        ).fetchone()
        if not row:
            await interaction.response.send_message("❌ Creator nicht eingerichtet.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(int(row[0]))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ Zielkanal nicht gefunden.", ephemeral=True)
            return
        if p == "youtube":
            embed = make_youtube_embed({"id": "dQw4w9WgXcQ", "title": "Beispiel-Video", "url": "https://youtu.be/dQw4w9WgXcQ", "creator": account})
        elif p == "twitch":
            embed = make_twitch_embed({"title": "Beispiel-Stream", "game_name": "Test", "viewer_count": 42, "user_name": account}, account)
        else:
            embed = discord.Embed(title="𝕏 Test Alert", description=f"Alert-System für `{account}` funktioniert.", color=discord.Color.dark_grey())
        role_id = int(row[1]) if row[1] else None
        role = interaction.guild.get_role(role_id) if role_id else None
        try:
            await channel.send(
                content=role.mention if role else None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(roles=bool(role), everyone=False, users=False),
            )
        except discord.Forbidden:
            await interaction.response.send_message("❌ Ich darf im Zielkanal keine Nachrichten senden.", ephemeral=True)
            return
        except discord.HTTPException as exc:
            await interaction.response.send_message(f"❌ Discord-Fehler: `{exc}`", ephemeral=True)
            return
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

    async def _send(self, sub: Subscription, embed: discord.Embed) -> None:
        channel = self.bot.get_channel(sub.channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"Zielkanal {sub.channel_id} nicht gefunden")
        role = channel.guild.get_role(sub.role_id) if sub.role_id else None
        try:
            await channel.send(
                content=role.mention if role else None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(roles=bool(role), everyone=False, users=False),
            )
        except discord.Forbidden as exc:
            raise RuntimeError(f"Keine Sendeberechtigung in Kanal {sub.channel_id}") from exc
        except discord.HTTPException as exc:
            raise RuntimeError(f"Discord-Fehler in Kanal {sub.channel_id}: {exc}") from exc

    async def _youtube(self, sub: Subscription):
        items = await asyncio.to_thread(youtube_feed, sub.account)
        if not items:
            return
        if not sub.last_seen:
            marker = youtube_initial_marker(items)
            if marker:
                self._save(sub.id, last_seen=marker)
            return

        unseen = latest_unseen(items, sub.last_seen)
        for item in unseen:
            state = await asyncio.to_thread(youtube_video_state, item["id"])
            kind = youtube_kind(state)
            embed = make_youtube_embed(item, kind=kind)
            await self._send(sub, embed)
            self._save(sub.id, last_seen=item["id"])

    async def _twitch(self, sub: Subscription):
        stream = await asyncio.to_thread(twitch_stream, sub.account)
        if not stream:
            if sub.state != "offline":
                self._save(sub.id, state="offline")
            return
        stream_id = str(stream.get("id") or "")
        if not twitch_should_notify(sub.state, stream_id):
            return
        embed = make_twitch_embed(stream, sub.account)
        await self._send(sub, embed)
        self._save(sub.id, state=stream_id)

    async def _x(self, sub: Subscription):
        user = await asyncio.to_thread(x_user, sub.account)
        posts = await asyncio.to_thread(x_posts, user["id"], sub.last_seen)
        normalized = [{**post, "published": post.get("created_at")} for post in posts]
        if not sub.last_seen:
            marker = youtube_initial_marker(normalized)
            if marker:
                self._save(sub.id, last_seen=marker)
            return
        unseen = latest_unseen(normalized, sub.last_seen)
        for post in unseen:
            url = f"https://x.com/{user.get('username', sub.account)}/status/{post['id']}"
            embed = discord.Embed(
                title=f"𝕏 Neuer Post von @{user.get('username', sub.account)}",
                description=f"{(post.get('text') or 'Neuer Post')[:3500]}\n\n{url}",
                url=url,
                timestamp=datetime.now(timezone.utc),
                color=discord.Color.dark_grey(),
            )
            for media in post.get("media", [])[:1]:
                preview = media.get("preview_image_url") or media.get("url")
                if preview:
                    embed.set_image(url=preview)
            await self._send(sub, embed)
            self._save(sub.id, last_seen=post["id"])


async def setup(bot: commands.Bot):
    await bot.add_cog(SocialCog(bot))
