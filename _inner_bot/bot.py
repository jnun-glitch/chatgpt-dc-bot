from __future__ import annotations

import importlib
import os
import threading

import discord
from discord import app_commands
from dotenv import load_dotenv
from flask import Flask, jsonify
from discord.ext import commands

from core.config import BOT_DIR
from core.db import init_db
from core.logging import logger

load_dotenv(BOT_DIR / ".env", override=True)
BOT_TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()


class ScratchAIBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=discord.Intents.all())

    async def setup_hook(self) -> None:
        init_db()
        await load_all_cogs(self)
        await sync_commands_safely(self)


def _cog_class(module):
    return next((v for v in vars(module).values() if isinstance(v, type) and issubclass(v, commands.Cog) and v is not commands.Cog), None)


async def _add_grouped_cog(client: ScratchAIBot, cog, module_name: str) -> None:
    original = list(getattr(cog, "__cog_app_commands__", ()))
    roots = [cmd for cmd in original if getattr(cmd, "parent", None) is None and isinstance(cmd, app_commands.Command)]
    others = [cmd for cmd in original if cmd not in roots]
    if len(roots) <= 1:
        await client.add_cog(cog)
        return

    primary = roots[0]
    secondary = roots[1:]
    stem = module_name.rsplit(".", 1)[-1].replace("_", "-")
    group_name = f"{stem}-cmds"[:32]
    if client.tree.get_command(group_name, type=discord.AppCommandType.chat_input):
        group_name = f"{stem[:27]}-grp"
    if client.tree.get_command(group_name, type=discord.AppCommandType.chat_input):
        raise RuntimeError(f"Keine freie Command-Gruppe für {module_name}")

    group = app_commands.Group(name=group_name, description=f"Weitere {stem} Commands")
    for cmd in secondary:
        group.add_command(cmd)
    cog.__cog_app_commands__ = tuple(others) + (primary, group)
    await client.add_cog(cog)


async def _load_cog_adaptive(client: ScratchAIBot, module_name: str) -> str:
    module = importlib.import_module(module_name)
    cog_cls = _cog_class(module)
    if cog_cls is None:
        raise RuntimeError(f"Keine Cog-Klasse in {module_name} gefunden")

    if module_name == "cogs.backup":
        client.tree.remove_command("backup", type=discord.AppCommandType.chat_input)

    cog = cog_cls(client)
    commands_in_cog = list(getattr(cog, "__cog_app_commands__", ()))
    roots = [cmd for cmd in commands_in_cog if getattr(cmd, "parent", None) is None]

    if len(roots) <= 1:
        await client.add_cog(cog)
        return "normal"

    await _add_grouped_cog(client, cog, module_name)
    return "grouped"


async def load_all_cogs(client: ScratchAIBot) -> None:
    cogs_dir = BOT_DIR / "cogs"
    total = grouped = failed = 0
    for path in sorted(cogs_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        name = path.stem
        try:
            mode = await _load_cog_adaptive(client, f"cogs.{name}")
            total += 1
            grouped += mode == "grouped"
            print(f"  [OK] {name}" + (" (Commands gruppiert)" if mode == "grouped" else ""))
        except Exception:
            failed += 1
            logger.exception("Cog konnte nicht geladen werden: %s", name)
            print(f"  [FEHLER] {name}")
    print(f"{total}/{total + failed} Cogs geladen ({grouped} mit gruppierten Slash-Commands)")


async def sync_commands_safely(client: ScratchAIBot) -> None:
    roots = client.tree.get_commands()
    print(f"[SYNC] {len(roots)} globale Slash-Commands vorbereitet")
    if len(roots) > 100:
        logger.error("Mehr als 100 globale Slash-Commands erkannt (%s).", len(roots))
        print("[SYNC] FEHLER: Mehr als 100 globale Slash-Commands")
        return
    try:
        synced = await client.tree.sync()
        print(f"[SYNC] {len(synced)} globale Slash-Commands synchronisiert")
    except discord.HTTPException as exc:
        logger.exception("Slash-Command-Sync fehlgeschlagen")
        print(f"[SYNC] FEHLER: {exc}")


bot = ScratchAIBot()
app = Flask(__name__)


@bot.event
async def on_ready() -> None:
    print("[CONNECT] Verbindung hergestellt\n")
    print(f"Eingeloggt als {bot.user} (ID: {bot.user.id if bot.user else 'unbekannt'})")
    print(f"Auf {len(bot.guilds)} Servern")
    print(f"Bot ist ONLINE! {len(bot.cogs)} Cogs geladen.")


@bot.event
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
    logger.error("App-Command-Fehler: %s", error, exc_info=error)
    try:
        if interaction.response.is_done():
            await interaction.followup.send("❌ Beim Ausführen des Commands ist ein Fehler aufgetreten.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Beim Ausführen des Commands ist ein Fehler aufgetreten.", ephemeral=True)
    except Exception:
        pass


@app.get("/")
def root():
    return jsonify(status="ok", bot_ready=bot.is_ready(), guilds=len(bot.guilds), cogs=len(bot.cogs))


@app.get("/health")
def health():
    return jsonify(status="ok" if bot.is_ready() else "starting")


def _read_int_env(name: str, default: int, minimum: int = 1) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        logger.warning("Env-Variable %s ist keine gültige Zahl (%r) – Default %s verwendet.", name, raw, default)
        return default


def run_web() -> None:
    port = _read_int_env("PORT", 8080)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


def run_bot() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("DISCORD_TOKEN fehlt. Bitte .env prüfen.")
    try:
        bot.run(BOT_TOKEN, log_handler=None)
    except discord.LoginFailure as exc:
        raise RuntimeError("Discord-Login fehlgeschlagen. DISCORD_TOKEN prüfen.") from exc


if __name__ == "__main__":
    threading.Thread(target=run_web, daemon=True).start()
    run_bot()
