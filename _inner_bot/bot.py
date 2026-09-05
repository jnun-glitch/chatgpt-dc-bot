"""ScratchAI Discord bot entrypoint.

The core deliberately stays small: Discord client lifecycle, extension loading,
health endpoint and the ticket-AI message hook. Feature code belongs in Cogs.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import time
import traceback
from pathlib import Path
from threading import Thread

from dotenv import load_dotenv
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask

BOT_DIR = Path(__file__).resolve().parent
load_dotenv(BOT_DIR / ".env", override=True)

from core.ai_ticket import analyze_ticket
from core.db import get_ticket_by_channel, init_db, update_ticket_ai
from core.logging import logger

BOT_TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
COGS_DIR = BOT_DIR / "cogs"
START_TIME = time.time()
loaded_cogs: list[str] = []
command_log: list[dict] = []
MAX_LOG_ENTRIES = 100
restart_count = 0

app = Flask("bot")


class ScratchAIBot(commands.Bot):
    """Main bot using discord.py's full extension/commands framework."""

    def __init__(self):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False),
        )

    async def setup_hook(self) -> None:
        init_db()
        await load_all_cogs(self)
        try:
            synced = await self.tree.sync()
            print(f"[SYNC] {len(synced)} globale Slash-Commands synchronisiert")
        except Exception as exc:
            logger.exception("Slash-Command-Sync fehlgeschlagen", exc_info=exc)


bot = ScratchAIBot()


def get_uptime() -> str:
    delta = int(time.time() - START_TIME)
    hours, remainder = divmod(delta, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


def log_command(name: str, user, status: str = "ok") -> None:
    command_log.append({
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        "command": name,
        "user": str(user),
        "status": status,
    })
    del command_log[:-MAX_LOG_ENTRIES]


async def load_all_cogs(client: commands.Bot) -> None:
    """Discover every Python Cog in cogs/ instead of maintaining a stale list."""
    loaded_cogs.clear()
    if not COGS_DIR.exists():
        logger.warning("Cogs directory fehlt: %s", COGS_DIR)
        return

    cog_names = sorted(
        path.stem
        for path in COGS_DIR.glob("*.py")
        if path.name != "__init__.py" and not path.name.startswith("_")
    )
    for cog in cog_names:
        try:
            await client.load_extension(f"cogs.{cog}")
            loaded_cogs.append(cog)
            print(f"  [OK] {cog}")
        except Exception:
            logger.exception("Cog konnte nicht geladen werden: %s", cog)
            print(f"  [FEHLER] {cog}")
    print(f"\n{len(loaded_cogs)}/{len(cog_names)} Cogs geladen")


async def unload_all_cogs(client: commands.Bot) -> None:
    for cog in loaded_cogs[:]:
        try:
            await client.unload_extension(f"cogs.{cog}")
        except Exception:
            logger.exception("Cog konnte nicht entladen werden: %s", cog)
    loaded_cogs.clear()


@app.route("/")
def route_index():
    online = bot.is_ready()
    status = "Online" if online else "Offline"
    return f"""<!doctype html><html><head><title>ScratchAI Bot</title>
<meta http-equiv="refresh" content="30">
<style>
body {{ font-family:system-ui,sans-serif; background:#0e0e10; color:#ccc; padding:40px; text-align:center; }}
h1 {{ color:#5865f2; }} .status {{ font-size:20px; margin:20px 0; }}
.card {{ background:#1e1f22; border:1px solid #3f4147; border-radius:12px; padding:20px; display:inline-block; margin:10px; min-width:160px; }}
.label {{ color:#8e9297; font-size:11px; text-transform:uppercase; }} .value {{ font-size:28px; font-weight:700; color:#fff; }}
</style></head><body>
<h1>ScratchAI Bot</h1><div class="status">● {status}</div>
<div class="card"><div class="label">Uptime</div><div class="value">{get_uptime()}</div></div>
<div class="card"><div class="label">Server</div><div class="value">{len(bot.guilds) if online else 0}</div></div>
<div class="card"><div class="label">Cogs</div><div class="value">{len(loaded_cogs)}</div></div>
<div class="card"><div class="label">Restarts</div><div class="value">{restart_count}</div></div>
</body></html>"""


@app.route("/health")
def route_health():
    ready = bot.is_ready()
    return json.dumps({
        "status": "ok" if ready else "starting",
        "uptime": get_uptime(),
        "guilds": len(bot.guilds) if ready else 0,
        "cogs": loaded_cogs,
        "cogs_loaded": len(loaded_cogs),
        "restarts": restart_count,
        "latency_ms": round(bot.latency * 1000) if bot.latency else None,
    })


def _read_int_env(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Env-Variable %s ist keine gültige Zahl (%r) – Default %s verwendet.", name, raw, default)
        return default
    if minimum is not None and value < minimum:
        logger.warning("Env-Variable %s=%s ist kleiner als %s – Default %s verwendet.", name, value, minimum, default)
        return default
    return value


def run_web() -> None:
    port = _read_int_env("PORT", 8080, minimum=1)
    if port > 65535:
        logger.warning("PORT=%s liegt außerhalb des gültigen Bereichs – Default 8080 verwendet.", port)
        port = 8080
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def run_bot() -> None:
    """Start the Discord client exactly once."""
    global restart_count
    restart_count = 1

    if not BOT_TOKEN:
        raise RuntimeError(
            "DISCORD_TOKEN ist nicht gesetzt. Trage den Bot-Token in _inner_bot/.env ein."
        )

    print("\n[START] Starte Discord-Bot...")
    try:
        bot.run(BOT_TOKEN, log_handler=None)
    except discord.LoginFailure:
        print(
            "[FEHLER] Discord hat den Bot-Token abgelehnt (401 Unauthorized).\n"
            "         Prüfe DISCORD_TOKEN in _inner_bot/.env.\n"
            "         Falls der Token stimmt, erzeuge im Discord Developer Portal einen neuen Bot-Token."
        )
        raise
    except KeyboardInterrupt:
        print("\n[STOP] Manuell gestoppt.")
    except Exception:
        traceback.print_exc()
        print("[STOP] Bot wurde wegen eines Startfehlers beendet.")
        raise


@bot.event
async def on_ready():
    print(f"\nEingeloggt als {bot.user} (ID: {bot.user.id})")
    print(f"Auf {len(bot.guilds)} Servern")
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="ScratchAI | /help")
    )
    print(f"Bot ist ONLINE! {len(loaded_cogs)} Cogs geladen.\n")


@bot.event
async def on_connect():
    print("[CONNECT] Verbindung hergestellt")


@bot.event
async def on_disconnect():
    print("[DISCONNECT] Verbindung verloren - reconnectet automatisch...")


@bot.event
async def on_resumed():
    print("[RESUME] Verbindung wiederhergestellt")


@bot.event
async def on_error(event, *args, **kwargs):
    logger.exception("Unhandled Discord event error: %s", event)


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    command_name = interaction.command.qualified_name if interaction.command else "unknown"
    log_command(command_name, interaction.user, "error")
    logger.exception("Command error: /%s", command_name, exc_info=error)

    message = "Beim Ausführen des Befehls ist ein Fehler aufgetreten."
    if isinstance(error, app_commands.CheckFailure):
        message = "Du hast keine Berechtigung für diesen Befehl."
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = "Dieser Befehl ist gerade auf Cooldown. Bitte versuche es gleich erneut."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.tree.command(name="ping", description="Zeigt die Bot-Latenz")
async def cmd_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000) if bot.latency else 0
    log_command("ping", interaction.user)
    await interaction.response.send_message(f"Pong! {latency}ms")


@bot.tree.command(name="hallo", description="Sagt Hallo zurück")
async def cmd_hallo(interaction: discord.Interaction):
    log_command("hallo", interaction.user)
    await interaction.response.send_message(f"Hallo {interaction.user.mention}! Wie geht es dir?")


async def _run_ai_ticket(message: discord.Message) -> None:
    ticket = get_ticket_by_channel(str(message.channel.id))
    if not ticket:
        return

    allowed = str(message.author.id) == str(ticket["user_id"])
    if message.guild:
        allowed = allowed or message.author.guild_permissions.manage_channels
        role_names = {role.name.casefold() for role in message.author.roles}
        allowed = allowed or bool(role_names & {"admin", "moderator", "support", "staff"})
    if not allowed:
        await message.channel.send("❌ Du hast keine Berechtigung für die AI-Ticketanalyse.")
        return

    await message.channel.send("🔍 **AI analysiert das komplette Ticket...**")
    lines = [
        f"Ticket #{ticket['ticket_number']:04d}",
        f"Kategorie: {ticket.get('kategorie', 'Sonstiges')}",
        f"Betreff: {ticket.get('betreff', 'Kein Betreff')}",
        "",
        "TICKETVERLAUF:",
    ]
    try:
        async for msg in message.channel.history(limit=500, oldest_first=True):
            if msg.content.strip().lower() == "!ai":
                continue
            content = msg.content.strip() or "[Kein Text]"
            if msg.attachments:
                content += " [Anhänge: " + ", ".join(a.filename for a in msg.attachments) + "]"
            lines.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.display_name}: {content}")
    except discord.Forbidden:
        await message.channel.send("❌ Ich kann den Ticketverlauf nicht lesen.")
        return
    except Exception as exc:
        logger.exception("Ticket-History konnte nicht gelesen werden", exc_info=exc)
        await message.channel.send("❌ Der Ticketverlauf konnte nicht geladen werden.")
        return

    transcript = "\n".join(lines)
    if len(transcript) > 60000:
        transcript = transcript[:12000] + "\n\n[... älterer Verlauf gekürzt ...]\n\n" + transcript[-47000:]
    try:
        verdict = await asyncio.to_thread(analyze_ticket, transcript)
        update_ticket_ai(str(message.channel.id), verdict)
    except Exception as exc:
        logger.exception("AI-Ticketanalyse fehlgeschlagen", exc_info=exc)
        await message.channel.send(f"❌ AI-Analyse fehlgeschlagen: `{str(exc)[:300]}`")
        log_command("!ai", message.author, "error")
        return

    embed = discord.Embed(
        title=f"🤖 AI-Ticketanalyse #{ticket['ticket_number']:04d}",
        description=verdict[:4096],
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"Analysiert mit DeepSeek • ausgelöst von {message.author.display_name}")
    await message.channel.send(embed=embed)
    log_command("!ai", message.author)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    if message.content.strip().lower() == "!ai":
        await _run_ai_ticket(message)
    await bot.process_commands(message)


if __name__ == "__main__":
    print("=" * 50)
    print("  ScratchAI Bot")
    print("=" * 50)
    print(f"  Token gesetzt: {'JA' if BOT_TOKEN else 'NEIN!'}")
    print(f"  Webserver: Port {os.environ.get('PORT', '8080')}")
    print("=" * 50)
    Thread(target=run_web, daemon=True).start()
    run_bot()
