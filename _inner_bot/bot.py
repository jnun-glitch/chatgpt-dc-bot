from __future__ import annotations

import importlib
import os
import threading
from pathlib import Path

import discord
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
        super().__init__(
            command_prefix=commands.when_mentioned_or("!"),
            intents=discord.Intents.all(),
        )

    async def setup_hook(self) -> None:
        init_db()
        await load_all_cogs(self)
        await sync_commands_safely(self)


async def _add_grouped_cog(client: ScratchAIBot, cog, module_name: str) -> None:
    """Register all root commands of a Cog below one slash-command group.

    This is only used when the bot approaches Discord's 100 global root-command
    limit. Listeners, tasks and command callbacks remain fully active.
    """
    root_commands = [
        cmd for cmd in getattr(cog, "__cog_app_commands__", ())
        if getattr(cmd, "parent", None) is None and isinstance(cmd, app_commands.Command)
    ]
    other_commands = [cmd for cmd in getattr(cog, "__cog_app_commands__", ()) if cmd not in root_commands]
    if not root_commands:
        await client.add_cog(cog)
        return

    stem = module_name.rsplit(".", 1)[-1].replace("_", "-")
    if len(stem) > 32:
        stem = stem[:32]
    name = stem
    existing = client.tree.get_command(name)
    if existing is not None:
        name = f"{stem[:27]}-cmd"
        if client.tree.get_command(name) is not None:
            raise RuntimeError(f"Kann keine eindeutige Command-Gruppe für {module_name} erstellen")

    group = app_commands.Group(name=name, description=f"{stem} Commands")
    for cmd in root_commands:
        group.add_command(cmd)
    cog.__cog_app_commands__ = tuple(other_commands) + (group,)
    await client.add_cog(cog)


async def _load_cog_with_adaptive_commands(client: ScratchAIBot, module_name: str) -> str:
    """Load a Cog, compressing its root slash commands only when necessary."""
    module = importlib.import_module(module_name)
    setup = getattr(module, "setup", None)
    if setup is None:
        raise RuntimeError(f"{module_name} hat keine setup()-Funktion")

    try:
        await client.load_extension(module_name)
        return "normal"
    except discord.app_commands.errors.CommandAlreadyRegistered:
        # The common collision in this project is the old admin /backup command.
        # Prefer the dedicated BackupCog group /backup now|status.
        if module_name == "cogs.backup":
            client.tree.remove_command("backup", type=discord.AppCommandType.chat_input)
            # Extension was only partially injected, so unload before retrying.
            if module_name in client.extensions:
                await client.unload_extension(module_name)
            module = importlib.import_module(module_name)
            setup = getattr(module, "setup")
            await setup(client)
            return "normal"
        # Retry by loading a fresh Cog instance, but hide its root app commands
        # from Cog._inject and register one compressed group instead.
        if module_name in client.extensions:
            await client.unload_extension(module_name)
        cog_cls = None
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, commands.Cog) and value is not commands.Cog:
                cog_cls = value
                break
        if cog_cls is None:
            raise
        cog = cog_cls(client)
        await _add_grouped_cog(client, cog, module_name)
        return "grouped"
    except discord.app_commands.errors.CommandLimitReached:
        if module_name in client.extensions:
            await client.unload_extension(module_name)
        cog_cls = None
        for value in vars(module).values():
            if isinstance(value, type) and issubclass(value, commands.Cog) and value is not commands.Cog:
                cog_cls = value
                break
        if cog_cls is None:
            raise
        cog = cog_cls(client)
        await _add_grouped_cog(client, cog, module_name)
        return "grouped"


async def load_all_cogs(client: ScratchAIBot) -> None:
    cogs_dir = BOT_DIR / "cogs"
    total = 0
    grouped = 0
    failed = 0

    for path in sorted(cogs_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        cog_name = path.stem
        module_name = f"cogs.{cog_name}"
        try:
            mode = await _load_cog_with_adaptive_commands(client, module_name)
            total += 1
            grouped += mode == "grouped"
            print(f"  [OK] {cog_name}" + (" (Commands gruppiert)" if mode == "grouped" else ""))
        except Exception:
            failed += 1
            logger.exception("Cog konnte nicht geladen werden: %s", cog_name)
            print(f"  [FEHLER] {cog_name}")

    print(f"{total}/{total + failed} Cogs geladen ({grouped} mit gruppierten Slash-Commands)")


async def sync_commands_safely(client: ScratchAIBot) -> None:
    roots = client.tree.get_commands()
    print(f"[SYNC] {len(roots)} globale Slash-Commands vorbereitet")
    if len(roots) > 100:
        logger.error("Mehr als 100 globale Slash-Commands erkannt (%s). Sync wird übersprungen.", len(roots))
        print("[SYNC] FEHLER: Mehr als 100 globale Slash-Commands – Sync übersprungen")
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
