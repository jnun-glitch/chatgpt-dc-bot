"""Creator-Alerts für YouTube, Twitch und X.

Eigenständige Implementierung, keine Übernahme von Red-DiscordBot-Code.
YouTube nutzt RSS, Twitch/X die offiziellen APIs. Neue Ereignisse werden
persistent dedupliziert und in einen Discord-Kanal gepostet.
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


def http_get(url: str, headers: dict[str, str] | None = None, data: bytes | None = None, method: str | None = None) -> str:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "ScratchAI/1.0"}, data=data, method=method)
    with urllib.request.urlopen(req, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace")


def json_get(url: str, headers: dict[str, str]) -> dict:
    return json.loads(http_get(url, headers=headers))


def youtube_channel_id(value: str) -> str:
    value = value.strip()
    match = re.search(r"(?:youtube\.com/)?channel/(UC[a-zA-Z0-9_-]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"UC[a-zA-Z0-9_-]{20,}", value):
        return value
    handle = value.rstrip("/").split("/")[-1].lstrip("@")
    text = http_get(f"https://www.youtube.com/@{urllib.parse.quote(handle, safe='')}")
    match = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]+)"', text)
    if match:
        return match.group(1)
    raise ValueError("YouTube-Kanal nicht gefunden. Nutze eine UC... Kanal-ID oder einen @Handle.")


def youtube_latest(channel_id: str) -> list[dict]:
    text = http_get(f"https://www.youtube.com/feeds/videos.xml?channel_id={urllib.parse.quote(channel_id)}")
    root = ET.fromstring(text)
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/yt"}
    result = []
    for entry in root.findall("a:entry", ns):
        vid = entry.findtext("yt:videoId", "", ns)
        if not vid:
            continue
        result.append({
            "id": vid,
            "title": html.unescape(entry.findtext("a:title", "", ns)),
            "url": f"https://youtu.be/{vid}",
            "creator": entry.findtext("a:author/a:name", "YouTube", ns),
            "published": entry.findtext("a:published", "", ns),
        })
    return result


_twitch_token: tuple[str, float] | None = None


def twitch_stream(login: str) -> dict | None:
    global _twitch_token
    if not TWITCH_CLIENT_ID or not TWITCH_CLIENT_SECRET:
        raise RuntimeError("TWITCH_CLIENT_ID und TWITCH_CLIENT_SECRET fehlen")
    if not _twitch_token or _twitch_token[1] < time.time() + 30:
        body = urllib.parse.urlencode({"client_id": TWITCH_CLIENT_ID, "client_secret": TWITCH_CLIENT_SECRET, "grant_type": "client_credentials"}).encode()
        payload = json.loads(http_get("https://id.twitch.tv/oauth2/token", headers={"User-Agent": "ScratchAI/1.0"}, data=body, method="POST"))
        _twitch_token = (payload["access_token"], time.time() + int(payload.get("expires_in", 3600)))
    token = _twitch_token[0]
    payload = json_get(f"https://api.twitch.tv/helix/streams?user_login={urllib.parse.quote(login)}", {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"})
    rows = payload.get("data", [])
    return rows[0] if rows else None


def x_user(username: str) -> dict:
    if not X_BEARER_TOKEN:
        raise RuntimeError("X_BEARER_TOKEN fehlt")
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}", "User-Agent": "ScratchAI/1.0"}
    return json_get(f"https://api.x.com/2/users/by/username/{urllib.parse.quote(username.lstrip('@'))}", headers).get("data", {})


def x_latest(user_id: str, since_id: str | None) -> list[dict]:
    if not X_BEARER_TOKEN:
        raise RuntimeError("X_BEARER_TOKEN fehlt")
    params = {"max_results": "10", "tweet.fields": "created_at,attachments", "expansions": "attachments.media_keys", "media.fields": "url,preview_image_url,type"}
    if since_id:
        params["since_id"] = since_id
    headers = {"Authorization": f"Bearer {X_BEARER_TOKEN}", "User-Agent": "ScratchAI/1.0"}
    payload = json_get("https://api.x.com/2/users/{}/tweets?{}".format(user_id, urllib.parse.urlencode(params)), headers)
    return payload.get("data", [])


class SocialCog(commands.Cog):
    """Unified social/creator notification service."""

    notify = app_commands.Group(name="notify", description="Creator-Benachrichtigungen")

    def __init__(self, bot: commands.Bot):
        self.bot = bot
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
        self.poll.start()

    def cog_unload(self):
        self.poll.cancel()

    @notify.command(name="add", description="YouTube-, Twitch- oder X-Creator überwachen")
    @app_commands.describe(provider="Plattform", account="Kanal, Login oder @Name", channel="Zielkanal", role="Optionale Ping-Rolle")
    @app_commands.choices(provider=[app_commands.Choice(name="YouTube", value="youtube"), app_commands.Choice(name="Twitch", value="twitch"), app_commands.Choice(name="X", value="x")])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def add(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str, channel: discord.TextChannel, role: discord.Role | None = None):
        p = provider.value
        try:
            if p == "youtube":
                account = await asyncio.to_thread(youtube_channel_id, account)
            elif p == "twitch":
                account = account.rstrip("/").split("/")[-1].lower()
                await asyncio.to_thread(twitch_stream, account)
            else:
                account = account.rstrip("/").split("/")[-1].lstrip("@").lower()
                user = await asyncio.to_thread(x_user, account)
                account = user.get("username", account).lower()
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
        await interaction.response.send_message(f"✅ `{p}` **{account}** → {channel.mention}" + (f" · {role.mention}" if role else ""), ephemeral=True)

    @notify.command(name="remove", description="Creator-Überwachung entfernen")
    @app_commands.choices(provider=[app_commands.Choice(name="YouTube", value="youtube"), app_commands.Choice(name="Twitch", value="twitch"), app_commands.Choice(name="X", value="x")])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def remove(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str):
        p = provider.value
        account = account.rstrip("/").split("/")[-1].lstrip("@")
        if p == "youtube" and not account.startswith("UC"):
            try: account = await asyncio.to_thread(youtube_channel_id, account)
            except Exception: pass
        db = get_db()
        cur = db.execute("DELETE FROM creator_notifications WHERE guild_id=? AND provider=? AND account=?", (str(interaction.guild_id), p, account.lower() if p != "youtube" else account))
        db.commit()
        await interaction.response.send_message("🗑️ Entfernt." if cur.rowcount else "⚠️ Nicht gefunden.", ephemeral=True)

    @notify.command(name="list", description="Creator-Überwachungen anzeigen")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def list_(self, interaction: discord.Interaction):
        rows = get_db().execute("SELECT provider,account,channel_id,role_id FROM creator_notifications WHERE guild_id=? ORDER BY provider,account", (str(interaction.guild_id),)).fetchall()
        if not rows:
            await interaction.response.send_message("📡 Keine Creator-Überwachungen eingerichtet.", ephemeral=True)
            return
        lines = []
        for p, account, channel_id, role_id in rows:
            ch = interaction.guild.get_channel(int(channel_id))
            role = interaction.guild.get_role(int(role_id)) if role_id else None
            lines.append(f"• **{p}** `{account}` → {ch.mention if ch else 'gelöschter Kanal'}" + (f" · {role.mention}" if role else ""))
        await interaction.response.send_message("📡 **Creator Alerts**\n" + "\n".join(lines), ephemeral=True)

    @notify.command(name="test", description="Test-Alert senden")
    @app_commands.choices(provider=[app_commands.Choice(name="YouTube", value="youtube"), app_commands.Choice(name="Twitch", value="twitch"), app_commands.Choice(name="X", value="x")])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test(self, interaction: discord.Interaction, provider: app_commands.Choice[str], account: str):
        p = provider.value
        account = account.rstrip("/").split("/")[-1].lstrip("@")
        row = get_db().execute("SELECT channel_id,role_id FROM creator_notifications WHERE guild_id=? AND provider=? AND account=?", (str(interaction.guild_id), p, account.lower() if p != "youtube" else account)).fetchone()
        if not row:
            await interaction.response.send_message("❌ Creator nicht gefunden. Nutze zuerst `/notify add`.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(int(row[0]))
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("❌ Zielkanal existiert nicht mehr.", ephemeral=True)
            return
        await channel.send(embed=discord.Embed(title=f"📡 Test-Alert: {p}", description=f"Überwachung für **{account}** ist aktiv.", timestamp=datetime.now(timezone.utc)))
        await interaction.response.send_message("✅ Test gesendet.", ephemeral=True)

    @tasks.loop(seconds=POLL_SECONDS)
    async def poll(self):
        rows = get_db().execute("SELECT id,guild_id,provider,account,channel_id,role_id,last_seen FROM creator_notifications WHERE enabled=1").fetchall()
        for row in rows:
            try:
                await self._poll_one(row)
            except Exception:
                logger.exception("Social alert failed: %s/%s", row[2], row[3])

    @poll.before_loop
    async def before_poll(self):
        await self.bot.wait_until_ready()

    async def _send(self, row, embed: discord.Embed):
        channel = self.bot.get_channel(int(row[4]))
        if not isinstance(channel, discord.TextChannel):
            return
        role = channel.guild.get_role(int(row[5])) if row[5] else None
        await channel.send(content=role.mention if role else None, embed=embed, allowed_mentions=discord.AllowedMentions(roles=True) if role else discord.AllowedMentions.none())

    async def _seen(self, sub_id: int, value: str):
        db = get_db(); db.execute("UPDATE creator_notifications SET last_seen=? WHERE id=?", (value, sub_id)); db.commit()

    async def _poll_one(self, row):
        sub_id, _, provider, account, _, _, last_seen = row
        if provider == "youtube":
            items = await asyncio.to_thread(youtube_latest, account)
            items.sort(key=lambda x: x["published"])
            if not items: return
            if not last_seen:
                await self._seen(sub_id, items[-1]["id"]); return
            new = []
            for item in items:
                if item["id"] == last_seen: break
                new.append(item)
            for item in reversed(new):
                await self._send(row, discord.Embed(title=f"🎬 {item['title']}", url=item["url"], description=f"Neues Video von **{item['creator']}**"))
            await self._seen(sub_id, items[-1]["id"])
        elif provider == "twitch":
            stream = await asyncio.to_thread(twitch_stream, account)
            state = str(stream["id"]) if stream else "offline"
            if not last_seen:
                await self._seen(sub_id, state); return
            if stream and state != last_seen:
                embed = discord.Embed(title=f"🔴 {stream.get('user_name', account)} ist LIVE!", url=f"https://twitch.tv/{account}", description=stream.get("title") or "Live auf Twitch")
                embed.add_field(name="Kategorie", value=stream.get("game_name") or "Unbekannt")
                await self._send(row, embed)
            await self._seen(sub_id, state)
        else:
            user = await asyncio.to_thread(x_user, account)
            posts = await asyncio.to_thread(x_latest, user["id"], last_seen if last_seen and last_seen != "offline" else None)
            if not posts:
                if not last_seen: await self._seen(sub_id, "offline")
                return
            posts.sort(key=lambda x: x["id"])
            for post in posts:
                url = f"https://x.com/{user.get('username', account)}/status/{post['id']}"
                await self._send(row, discord.Embed(title=f"𝕏 Neuer Post von @{user.get('username', account)}", url=url, description=post.get("text", "")[:4000]))
            await self._seen(sub_id, posts[-1]["id"])


async def setup(bot: commands.Bot):
    await bot.add_cog(SocialCog(bot))
