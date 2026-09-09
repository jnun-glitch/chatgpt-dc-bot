"""Automatische Bot-Backups mit Integritätsprüfung."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from discord.ext import commands, tasks

from core.backup import create_backup, prune_backups, verify_backup
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
    """Automatischer Backup-Dienst; der manuelle /backup-Command bleibt im Admin-Cog."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.last_backup: Path | None = None
        self.last_error: str | None = None
        self.last_verified: bool | None = None
        self.backup_loop.start()

    def cog_unload(self):
        self.backup_loop.cancel()

    async def _make_backup(self) -> Path:
        path = await asyncio.to_thread(create_backup, db_path=DB_PATH, transcripts_dir=TRANSCRIPTS_DIR, backup_dir=BACKUP_DIR)
        valid, errors = await asyncio.to_thread(verify_backup, path)
        if not valid:
            self.last_verified = False
            raise RuntimeError("Backup-Integritätsprüfung fehlgeschlagen: " + "; ".join(errors[:3]))
        await asyncio.to_thread(prune_backups, BACKUP_DIR, BACKUP_RETENTION)
        self.last_backup = path
        self.last_verified = True
        self.last_error = None
        return path

    @tasks.loop(seconds=BACKUP_INTERVAL_SECONDS)
    async def backup_loop(self):
        try:
            path = await self._make_backup()
            logger.info("Automatisches Backup erstellt und geprüft: %s", path)
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("Automatisches Backup fehlgeschlagen", exc_info=exc)

    @backup_loop.before_loop
    async def before_backup_loop(self):
        await self.bot.wait_until_ready()
        try:
            path = await self._make_backup()
            logger.info("Startup-Backup erstellt und geprüft: %s", path)
        except Exception as exc:
            self.last_error = str(exc)
            logger.exception("Startup-Backup fehlgeschlagen", exc_info=exc)


async def setup(bot: commands.Bot):
    await bot.add_cog(BackupCog(bot))
