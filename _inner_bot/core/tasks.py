"""Hintergrund-Tasks: Reminder-Loop + Member-Snapshots + Auto-Backup + Heartbeat."""
import asyncio
import shutil
from datetime import datetime

import discord
from core.db import get_pending_reminders, mark_reminder_sent, save_member_snapshot
from core.logging import logger
from core.config import BOT_DIR, DB_PATH, PROJECT_ROOT

_HEARTBEAT_FILE = PROJECT_ROOT / 'data' / 'bot_heartbeat.txt'


async def reminder_check_loop(bot):
    """Prüft alle 30s auf fällige Reminder und sendet DMs."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(30)
        try:
            reminders = get_pending_reminders()
            for r in reminders:
                user = bot.get_user(int(r['user_id']))
                if user:
                    try:
                        dm = await user.create_dm()
                        embed = discord.Embed(
                            title='⏰ Erinnerung',
                            description=r['message'],
                            color=discord.Color.gold()
                        )
                        await dm.send(embed=embed)
                    except Exception:
                        pass
                mark_reminder_sent(r['id'])
        except Exception as e:
            logger.error(f'Reminder check error: {e}')


async def member_snapshot_loop(bot):
    """Speichert alle 6h die Mitgliederzahl jedes Servers für /growth."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            for guild in bot.guilds:
                save_member_snapshot(guild.id, guild.member_count)
        except Exception as e:
            logger.error(f'Member snapshot error: {e}')
        await asyncio.sleep(6 * 3600)


async def backup_loop(bot, interval_hours: int = 24, keep: int = 7):
    """Erstellt täglich ein DB-Backup, rotiert nach Anzahl (7 Stück)."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            backup_dir = BOT_DIR / 'backups'
            backup_dir.mkdir(exist_ok=True)
            if DB_PATH.exists():
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                target = backup_dir / f'auto_backup_{timestamp}.db'
                shutil.copy2(str(DB_PATH), str(target))
                logger.info(f'Auto-Backup erstellt: {target.name} ({target.stat().st_size / 1024:.1f} KB)')

                auto = sorted(backup_dir.glob('auto_backup_*.db'))
                for old in auto[:-keep]:
                    try:
                        old.unlink()
                        logger.info(f'Backup rotiert: {old.name} entfernt')
                    except Exception:
                        pass
            else:
                logger.warning('Auto-Backup übersprungen: DB nicht gefunden')
        except Exception as e:
            logger.error(f'Auto-Backup Fehler: {e}')
        await asyncio.sleep(interval_hours * 3600)


async def heartbeat_loop(bot, interval_seconds: int = 60):
    """Schreibt alle 60s einen Heartbeat-Timestamp – Basis für den Watchdog."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        try:
            _HEARTBEAT_FILE.parent.mkdir(exist_ok=True)
            _HEARTBEAT_FILE.write_text(datetime.now().isoformat(), encoding='utf-8')
        except Exception as e:
            logger.error(f'Heartbeat Fehler: {e}')
        await asyncio.sleep(interval_seconds)
