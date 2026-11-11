"""Twitch EventSub WebSocket live alerts.

This is an optional fast path for Twitch stream.online notifications. The
existing polling in social.py remains as a fallback, so missing EventSub
credentials do not disable Twitch notifications.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import discord
from discord.ext import commands, tasks

from core.db import get_db
from core.logging import logger
from cogs.social import make_twitch_embed

try:
    import websockets
except ImportError:  # pragma: no cover - dependency is installed in requirements.txt
    websockets = None


TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "").strip()
TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "").strip()
TWITCH_USER_ACCESS_TOKEN = os.environ.get("TWITCH_USER_ACCESS_TOKEN", "").strip()
EVENTSUB_ENABLED = os.environ.get("TWITCH_EVENTSUB_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


class TwitchEventSubCog(commands.Cog):
    """Keep one EventSub WebSocket and subscribe to all configured Twitch creators."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._stop = asyncio.Event()
        self._ws_task = asyncio.create_task(self._run())

    def cog_unload(self):
        self._stop.set()
        self._ws_task.cancel()

    def _configured(self) -> bool:
        return bool(EVENTSUB_ENABLED and websockets and TWITCH_CLIENT_ID and TWITCH_USER_ACCESS_TOKEN)

    def _subscriptions(self) -> list[tuple[int, int, str, int | None, str | None]]:
        rows = get_db().execute(
            "SELECT id,guild_id,account,channel_id,role_id,state "
            "FROM social_notifications WHERE enabled=1 AND provider='twitch'"
        ).fetchall()
        return [
            (int(r[0]), int(r[1]), str(r[2]), int(r[3]), int(r[4]) if r[4] else None, r[5])
            for r in rows
        ]

    def _twitch_user(self, login: str) -> dict:
        headers = {
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {TWITCH_USER_ACCESS_TOKEN}",
        }
        req = urllib.request.Request(
            "https://api.twitch.tv/helix/users?login=" + urllib.parse.quote(login),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Twitch users HTTP {exc.code}: {body[:200]}") from exc
        rows = payload.get("data") or []
        if not rows:
            raise RuntimeError(f"Twitch-Kanal nicht gefunden: {login}")
        return rows[0]

    def _save_state(self, sub_id: int, state: str):
        db = get_db()
        db.execute("UPDATE social_notifications SET state=? WHERE id=?", (state, sub_id))
        db.commit()

    async def _send_alert(self, sub, event: dict):
        sub_id, guild_id, account, channel_id, role_id, previous_state = sub
        stream_id = str(event.get("id") or "")
        if not stream_id or previous_state == stream_id:
            return

        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError(f"Zielkanal {channel_id} nicht gefunden")

        # EventSub stream.online contains the creator identity but not title/game.
        # Fetch the current stream through the Twitch API so the Discord embed has
        # the same useful information as the existing polling implementation.
        stream = await asyncio.to_thread(self._current_stream, account)
        if not stream:
            stream = {
                "id": stream_id,
                "title": "Twitch Stream",
                "game_name": "Unbekannt",
                "viewer_count": 0,
                "user_name": event.get("broadcaster_user_name") or account,
            }

        embed = make_twitch_embed(stream, account)
        role = channel.guild.get_role(role_id) if role_id else None
        await channel.send(
            content=role.mention if role else None,
            embed=embed,
            allowed_mentions=discord.AllowedMentions(roles=bool(role), everyone=False, users=False),
        )
        self._save_state(sub_id, stream_id)
        logger.info("Twitch EventSub alert sent: %s/%s", account, stream_id)

    def _current_stream(self, login: str) -> dict | None:
        headers = {
            "Client-ID": TWITCH_CLIENT_ID,
            "Authorization": f"Bearer {TWITCH_USER_ACCESS_TOKEN}",
        }
        req = urllib.request.Request(
            "https://api.twitch.tv/helix/streams?user_login=" + urllib.parse.quote(login),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("Twitch stream lookup failed for %s: %s", login, exc)
            return None
        rows = payload.get("data") or []
        return rows[0] if rows else None

    async def _subscribe(self, websocket, session_id: str, broadcaster_id: str):
        token = TWITCH_USER_ACCESS_TOKEN
        body = {
            "type": "stream.online",
            "version": "1",
            "condition": {"broadcaster_user_id": broadcaster_id},
            "transport": {"method": "websocket", "session_id": session_id},
        }
        request = urllib.request.Request(
            "https://api.twitch.tv/helix/eventsub/subscriptions",
            data=json.dumps(body).encode(),
            headers={
                "Client-ID": TWITCH_CLIENT_ID,
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            if exc.code == 409:
                logger.info("Twitch EventSub already subscribed: %s", broadcaster_id)
                return
            raise RuntimeError(f"EventSub subscribe HTTP {exc.code}: {text[:300]}") from exc
        data = payload.get("data") or []
        if data:
            logger.info("Twitch EventSub subscribed: %s", broadcaster_id)

    async def _run(self):
        await self.bot.wait_until_ready()
        if not self._configured():
            logger.info("Twitch EventSub disabled: set TWITCH_CLIENT_ID + TWITCH_USER_ACCESS_TOKEN to enable it. Polling remains active.")
            return

        while not self._stop.is_set():
            try:
                async with websockets.connect("wss://eventsub.wss.twitch.tv/ws", ping_interval=20, ping_timeout=20) as websocket:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=15)
                    welcome = json.loads(raw)
                    session = welcome.get("payload", {}).get("session", {})
                    session_id = session.get("id")
                    if not session_id:
                        raise RuntimeError("Twitch EventSub returned no session id")

                    seen_broadcasters: set[str] = set()
                    for _, _, account, _, _, _ in self._subscriptions():
                        try:
                            user = await asyncio.to_thread(self._twitch_user, account)
                            broadcaster_id = str(user["id"])
                            if broadcaster_id not in seen_broadcasters:
                                await self._subscribe(websocket, session_id, broadcaster_id)
                                seen_broadcasters.add(broadcaster_id)
                        except Exception:
                            logger.exception("Could not subscribe Twitch creator: %s", account)

                    logger.info("Twitch EventSub connected; watching %d creator(s)", len(seen_broadcasters))
                    async for raw in websocket:
                        message = json.loads(raw)
                        message_type = message.get("metadata", {}).get("message_type")
                        if message_type != "notification":
                            continue
                        if message.get("metadata", {}).get("subscription_type") != "stream.online":
                            continue
                        event = message.get("payload", {}).get("event", {})
                        broadcaster_id = str(event.get("broadcaster_user_id") or "")
                        for sub in self._subscriptions():
                            try:
                                user = await asyncio.to_thread(self._twitch_user, sub[2])
                                if str(user.get("id")) == broadcaster_id:
                                    await self._send_alert(sub, event)
                            except Exception:
                                logger.exception("Twitch EventSub alert failed for %s", sub[2])
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Twitch EventSub disconnected: %s; retrying in 15s", exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=15)
                except asyncio.TimeoutError:
                    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(TwitchEventSubCog(bot))
