import os
import time
import json
import datetime
import asyncio
import traceback
from threading import Thread

import discord
from discord import app_commands
from flask import Flask

from core.ai_ticket import analyze_ticket
from core.db import get_ticket_by_channel, update_ticket_ai
from core.logging import logger


BOT_TOKEN = os.environ.get("DISCORD_TOKEN", "")
START_TIME = time.time()
loaded_cogs = []
command_log = []
max_log_entries = 50
restart_count = 0


app = Flask("bot")


intents = discord.Intents.all()
bot = discord.Client(intents=intents, connector=None)
tree = app_commands.CommandTree(bot)


def get_uptime():
    delta = int(time.time() - START_TIME)
    hours, remainder = divmod(delta, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


def log_command(name, user, status="ok"):
    entry = {
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        "command": name,
        "user": str(user),
        "status": status,
    }
    command_log.append(entry)
    if len(command_log) > max_log_entries:
        command_log.pop(0)


COG_LIST = [
    "active", "admin", "ai", "automod", "community", "dashboard",
    "fun", "help", "info", "levelroles", "mcstatus",
    "moderation", "music", "private_vc", "reactionroles",
    "starboard", "stats", "tickets", "verify",
]


async def load_all_cogs():
    global loaded_cogs
    loaded_cogs = []
    for cog in COG_LIST:
        try:
            await bot.load_extension(f"cogs.{cog}")
            loaded_cogs.append(cog)
            print(f"  [OK] {cog}")
        except Exception as e:
            print(f"  [FEHLER] {cog}: {e}")
    print(f"\n{len(loaded_cogs)}/{len(COG_LIST)} Cogs geladen")


async def unload_all_cogs():
    global loaded_cogs
    for cog in loaded_cogs[:]:
        try:
            await bot.unload_extension(f"cogs.{cog}")
        except Exception:
            pass
    loaded_cogs = []


@app.route("/")
def route_index():
    status = "Online" if bot.is_ready() else "Offline"
    color = "#4EC9B0" if bot.is_ready() else "#F14C4C"
    guilds = len(bot.guilds) if bot.is_ready() else 0
    return f"""<html><head><title>ScratchAI Bot</title>
<meta http-equiv="refresh" content="30">
<style>
body {{ font-family:sans-serif; background:#0E0E10; color:#CCC; padding:40px; text-align:center; }}
h1 {{ color:#007ACC; }}
.status {{ color:{color}; font-size:20px; margin:20px 0; }}
.card {{ background:#1E1E1E; border:1px solid #3C3C3C; border-radius:8px; padding:20px; display:inline-block; margin:10px; min-width:150px; }}
.label {{ color:#666; font-size:11px; text-transform:uppercase; }}
.value {{ font-size:28px; font-weight:bold; color:#fff; }}
</style></head><body>
<h1>ScratchAI Bot</h1>
<div class="status">● {status}</div>
<div class="card"><div class="label">Uptime</div><div class="value">{get_uptime()}</div></div>
<div class="card"><div class="label">Server</div><div class="value">{guilds}</div></div>
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
        "cogs_expected": len(COG_LIST),
        "restarts": restart_count,
        "latency_ms": round(bot.latency * 1000) if bot.latency else None,
    })


def run_web():
    port = int(os.environ.get("PORT", "8080") or "8080")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def run_bot():
    global restart_count
    while True:
        try:
            restart_count += 1
            print(f"\n[START] Bot Start #{restart_count}...")
            bot.run(BOT_TOKEN)
        except KeyboardInterrupt:
            print("\n[STOP] Manuell gestoppt.")
            break
        except Exception as e:
            print(f"\n[CRASH] {e}")
            traceback.print_exc()
            print("[RESTART] Neustart in 5 Sekunden...")
            time.sleep(5)


@bot.event
async def on_ready():
    print(f"\nEingeloggt als {bot.user} (ID: {bot.user.id})")
    print(f"Auf {len(bot.guilds)} Servern")
    try:
        await tree.sync()
        print("Slash-Commands synchronisiert")
    except Exception as e:
        print(f"Sync-Fehler: {e}")
    if not loaded_cogs:
        print("Lade alle Cogs...")
        await load_all_cogs()
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="ScratchAI | /help")
    )
    print(f"\nBot ist ONLINE! {len(loaded_cogs)} Cogs geladen.\n")


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
async def on_socket_raw_receive(msg):
    pass


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    command_name = interaction.command.name if interaction.command else "unknown"
    log_command(command_name, interaction.user, "error")
    print(f"[COMMAND ERROR] /{command_name}: {error}")

    message = "Beim Ausführen des Befehls ist ein Fehler aufgetreten."
    if isinstance(error, app_commands.CheckFailure):
        message = "Du hast keine Berechtigung für diesen Befehl."
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = "Dieser Befehl ist gerade auf Cooldown. Bitte versuche es gleich erneut."

    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@tree.command(name="ping", description="Zeigt die Bot-Latenz")
async def cmd_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000) if bot.latency else 0
    log_command("ping", interaction.user)
    await interaction.response.send_message(f"Pong! {latency}ms")


@tree.command(name="hallo", description="Sagt Hallo zurueck")
async def cmd_hallo(interaction: discord.Interaction):
    log_command("hallo", interaction.user)
    await interaction.response.send_message(
        f"Hallo {interaction.user.mention}! Wie geht es dir?"
    )


@tree.command(name="status", description="Zeigt den Bot-Status")
async def cmd_status(interaction: discord.Interaction):
    embed = discord.Embed(title="Bot Status", color=0x007ACC)
    embed.add_field(name="Status", value="Online")
    embed.add_field(name="Uptime", value=get_uptime())
    embed.add_field(name="Server", value=str(len(bot.guilds)))
    embed.add_field(name="Cogs", value=str(len(loaded_cogs)))
    embed.add_field(name="Restarts", value=str(restart_count))
    embed.add_field(
        name="Latenz",
        value=f"{round(bot.latency * 1000)}ms" if bot.latency else "N/A",
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="serverinfo", description="Zeigt Informationen ueber den Server")
async def cmd_serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    log_command("serverinfo", interaction.user)
    embed = discord.Embed(title=guild.name, color=0x007ACC)
    embed.add_field(name="Mitglieder", value=str(guild.member_count))
    embed.add_field(
        name="Erstellt", value=guild.created_at.strftime("%d.%m.%Y")
    )
    embed.add_field(name="Server-ID", value=str(guild.id))
    await interaction.response.send_message(embed=embed)


@tree.command(name="userinfo", description="Zeigt Informationen ueber einen Nutzer")
async def cmd_userinfo(
    interaction: discord.Interaction, member: discord.Member = None
):
    member = member or interaction.user
    log_command("userinfo", interaction.user)
    embed = discord.Embed(title=str(member), color=member.color)
    embed.add_field(name="ID", value=str(member.id))
    embed.add_field(
        name="Beigetreten",
        value=member.joined_at.strftime("%d.%m.%Y") if member.joined_at else "?",
    )
    embed.add_field(name="Bot?", value="Ja" if member.bot else "Nein")
    await interaction.response.send_message(embed=embed)


async def _run_ai_ticket(message: discord.Message):
    """Analyze the complete current ticket without blocking Discord's event loop."""
    ticket = get_ticket_by_channel(str(message.channel.id))
    if not ticket:
        await message.channel.send("❌ `!ai` funktioniert nur in einem offenen Ticket-Channel.")
        return

    # Support/Admin/Moderator dürfen analysieren; der Ticket-Ersteller darf sein eigenes Ticket ebenfalls prüfen.
    allowed = str(message.author.id) == str(ticket["user_id"])
    if message.guild:
        allowed = allowed or message.author.guild_permissions.manage_channels
        role_names = {role.name.lower() for role in message.author.roles}
        allowed = allowed or bool(role_names & {"admin", "moderator", "support"})
    if not allowed:
        await message.channel.send("❌ Du hast keine Berechtigung für die AI-Ticketanalyse.")
        return

    await message.channel.send("🔍 **AI analysiert das komplette Ticket...** Bitte kurz warten.")

    lines = [
        f"Ticket #{ticket['ticket_number']:04d}",
        f"Kategorie: {ticket.get('kategorie', 'Sonstiges')}",
        f"Betreff: {ticket.get('betreff', 'Kein Betreff')}",
        "",
        "TICKETVERLAUF:",
    ]
    try:
        async for msg in message.channel.history(limit=500, oldest_first=True):
            if msg.content.strip() == "!ai":
                continue
            timestamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
            content = msg.content.strip() or "[Kein Text]"
            attachments = " ".join(a.filename for a in msg.attachments)
            if attachments:
                content += f" [Anhänge: {attachments}]"
            lines.append(f"[{timestamp}] {msg.author.display_name}: {content}")
    except discord.Forbidden:
        await message.channel.send("❌ Ich kann den Ticketverlauf nicht lesen. Prüfe die Channel-Berechtigungen des Bots.")
        return
    except Exception as exc:
        logger.error(f"Ticket-History konnte nicht gelesen werden: {exc}")
        await message.channel.send("❌ Der Ticketverlauf konnte nicht geladen werden.")
        return

    # Schutz gegen extrem große Requests; die jüngsten Nachrichten bleiben erhalten.
    transcript = "\n".join(lines)
    if len(transcript) > 60000:
        transcript = lines[:5] and "\n".join(lines[:5]) + "\n\n[Älterer Verlauf wegen Größenlimit gekürzt]\n" + "\n".join(lines[-500:])
        transcript = transcript[-60000:]

    try:
        verdict = await asyncio.to_thread(analyze_ticket, transcript)
        update_ticket_ai(str(message.channel.id), verdict)
    except Exception as exc:
        logger.error(f"AI-Ticketanalyse fehlgeschlagen: {exc}")
        await message.channel.send(f"❌ AI-Analyse fehlgeschlagen: `{str(exc)[:300]}`")
        log_command("!ai", message.author, "error")
        return

    embed = discord.Embed(
        title=f"🤖 AI-Ticketanalyse #{ticket['ticket_number']:04d}",
        description=verdict[:4096],
        color=discord.Color.blurple(),
    )
    embed.set_footer(text=f"Analysiert von DeepSeek • ausgelöst von {message.author.display_name}")
    await message.channel.send(embed=embed)
    log_command("!ai", message.author)


@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.content.strip().lower() == "!ai":
        await _run_ai_ticket(message)


if __name__ == "__main__":
    print("=" * 50)
    print("  ScratchAI Bot - Replit 24/7")
    print("=" * 50)
    print(f"  Token gesetzt: {'JA' if BOT_TOKEN else 'NEIN!'}")
    print(f"  Webserver: Port {os.environ.get('PORT', '8080')}")
    print("=" * 50)

    Thread(target=run_web, daemon=True).start()
    run_bot()
