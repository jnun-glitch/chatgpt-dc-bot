"""Authenticated local callback server for n8n ticket responses."""
from __future__ import annotations

import asyncio
import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import discord

from core.config import BOT_SECRET
from core.logging import logger

_MAX_BODY_BYTES = 64 * 1024
_MAX_RESPONSE_CHARS = 12_000
_bot = None
_server = None
_server_thread = None


async def _deliver_ticket_response(ticket_number: str, channel_id: int, response: str) -> None:
    bot = _bot
    if bot is None:
        raise RuntimeError("Discord-Bot ist nicht bereit")

    channel = bot.get_channel(channel_id)
    if channel is None:
        channel = await bot.fetch_channel(channel_id)
    if not isinstance(channel, (discord.TextChannel, discord.Thread)):
        raise RuntimeError("Ticket-Ziel ist kein Textkanal")

    response = response[:_MAX_RESPONSE_CHARS]
    chunks = [response[index:index + 1800] for index in range(0, len(response), 1800)]
    for index, chunk in enumerate(chunks):
        prefix = f"🤖 **n8n-Antwort für Ticket #{ticket_number}**\n" if index == 0 else ""
        await channel.send(
            prefix + chunk,
            allowed_mentions=discord.AllowedMentions.none(),
        )


class CallbackHandler(BaseHTTPRequestHandler):
    """Validate n8n callbacks and deliver their response to the ticket channel."""

    def _json(self, status: int, body: dict) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path != "/ticket-callback":
            self._json(404, {"error": "Not found"})
            return
        if not BOT_SECRET:
            self._json(503, {"error": "Server nicht konfiguriert"})
            return
        provided_secret = self.headers.get("X-Bot-Secret", "").encode("utf-8")
        if not hmac.compare_digest(provided_secret, BOT_SECRET.encode("utf-8")):
            self._json(401, {"error": "Unauthorized"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "Ungültige Content-Length"})
            return
        if length <= 0 or length > _MAX_BODY_BYTES:
            self._json(413 if length > _MAX_BODY_BYTES else 400, {"error": "Ungültige Body-Größe"})
            return

        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "Ungültiger JSON-Body"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "JSON-Body muss ein Objekt sein"})
            return

        ticket_number = str(body.get("ticket_number", "")).strip()
        raw_channel_id = body.get("channel_id")
        raw_response = body.get("output", body.get("text", ""))
        if not ticket_number or not ticket_number.isdigit():
            self._json(400, {"error": "Ungültige Ticketnummer"})
            return
        try:
            channel_id = int(raw_channel_id)
        except (TypeError, ValueError):
            self._json(400, {"error": "Ungültige Channel-ID"})
            return
        response = raw_response if isinstance(raw_response, str) else json.dumps(raw_response, ensure_ascii=False)
        response = response.strip()
        if not response:
            self._json(400, {"error": "Ticket-Antwort ist leer"})
            return

        try:
            future = asyncio.run_coroutine_threadsafe(
                _deliver_ticket_response(ticket_number, channel_id, response),
                _bot.loop,
            )
            future.result(timeout=30)
        except TimeoutError:
            logger.error("n8n callback timed out for ticket #%s", ticket_number)
            self._json(504, {"error": "Discord-Antwort hat zu lange gedauert"})
            return
        except Exception as exc:
            logger.exception("n8n callback failed for ticket #%s: %s", ticket_number, exc)
            self._json(503, {"error": "Ticket-Antwort konnte nicht zugestellt werden"})
            return

        logger.info("n8n callback delivered for ticket #%s", ticket_number)
        self._json(200, {"status": "ok"})

    def log_message(self, format, *args):
        pass


def start_callback_server(bot_instance, port: int = 5681) -> None:
    """Start the local n8n callback listener once when a secret is configured."""
    global _bot, _server, _server_thread
    _bot = bot_instance
    if not BOT_SECRET:
        logger.info("n8n callback disabled: BOT_SECRET ist nicht gesetzt")
        return
    if _server_thread and _server_thread.is_alive():
        return

    _server = ThreadingHTTPServer(("127.0.0.1", port), CallbackHandler)
    _server.daemon_threads = True
    _server_thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _server_thread.start()
    logger.info("n8n callback server started on 127.0.0.1:%s", port)
