"""Automatische Bot-Backups."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from discord import app_commands
from discord.ext import commands, tasks

from core.backup import create_backup, prune_backups
from core.config import DB_PATH, DATA_DIR, TRANSCRIPTS_DIR
from core.logging import logger


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(minimum, int(raw))
    except ValueError:
        logger.warning("Env-Variable %s ist keine gültige Zahl (%r) – Default %s verwendet.", name, raw, default)
        return default


BACKUP_INTERVAL_SECONDS = _env_int("BACKUP_INTERVAL_SECONDS", 300, 60)
BACKUP_RETENTION = _env_int("BACKUP_RETENTION", 288, 1)
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", str(DATA_DIR / "backups"))).resolve()


class BackupCog(commands.Cog):
    backup = app_commands.Group(name="backup", description="Bot-Backups verwalten")

    def __init__(self, bot):
        self.bot = bot
        self.last_backup = None
        self.last_error = None
        self.backup_loop.start()

    def cog_unload(self):
        self.backup_loop.cancel()

    async def _make_backup(self):
        path = await asyncio.to_thread(create_backup, db_path=DB_PATH, transcripts_dir=TRANSCRIPTS_DIR, backup_dir=BACKUP_DIR)
        await asyncio.to_thread(prune_backups, BACKUP_DIR, BACKUP_RETENTION)
        self.last_backup = path
        self.last_error = None
        return path

    @tasks.loop(seconds=BACKUP_INTERVAL_SECONDS)
    async def backup_loop(self):
        try:
            path = await self._make_backup()
            logger.info("Automatisches Backup erstellt: %s", path)
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("Automatisches Backup fehlgeschlagen", exc_info=exc)

    @backup_loop.before_loop
    async def before_backup_loop(self):
        await self.bot.wait_until_ready()
        try:
            path = await self._make_backup()
            logger.info("Startup-Backup erstellt: %s", path)
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("Startup-Backup fehlgeschlagen", exc_info=exc)

    @backup.command(name="now", description="Erstellt sofort ein Backup")
    async def backup_now(self, interaction):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("❌ Nur der Bot-Owner darf Backups auslösen.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            path = await self._make_backup()
        except Exception as exc:
            logger.exception("Manuelles Backup fehlgeschlagen", exc_info=exc)
            await interaction.followup.send(f"❌ Backup fehlgeschlagen: `{str(exc)[:300]}`", ephemeral=True)
            return
        await interaction.followup.send(f"✅ Backup erstellt: `{path.name}`\nAufbewahrung: {BACKUP_RETENTION} Backups.", ephemeral=True)

    @backup.command(name="status", description="Zeigt den Backup-Status")
    async def backup_status(self, interaction):
        if not await self.bot.is_owner(interaction.user):
            await interaction.response.send_message("❌ Nur der Bot-Owner darf den Backup-Status sehen.", ephemeral=True)
            return
        files = sorted(BACKUP_DIR.glob("scratchai_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True) if BACKUP_DIR.exists() else []
        latest = files[0].name if files else "Noch kein Backup"
        error = self.last_error or "Keiner"
        await interaction.response.send_message(
            f"**Backup-Status**\nIntervall: `{BACKUP_INTERVAL_SECONDS // 60} Min.`\n"
            f"Vorhandene Backups: `{len(files)}`\nLetztes Backup: `{latest}`\nFehler: `{error[:500]}`",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(BackupCog(bot))
