"""Small background scheduler for persistent reminders.

Keeps scheduled work separate from command definitions so reminders survive a
bot restart. Delivery is best-effort and database state is only marked sent
after a successful DM.
"""
from __future__ import annotations

from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from core.db import get_db
from core.logging import logger


class SchedulerV2(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._loop.start()

    def cog_unload(self):
        self._loop.cancel()

    @tasks.loop(seconds=20)
    async def _loop(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id,user_id,message FROM reminders WHERE sent=0 AND remind_at <= ? ORDER BY id ASC LIMIT 25",
            (now,),
        )
        rows = cur.fetchall()
        conn.close()

        for row in rows:
            try:
                user = self.bot.get_user(int(row["user_id"])) or await self.bot.fetch_user(int(row["user_id"]))
                await user.send(f"⏰ **Erinnerung**\n{row['message']}")
            except (discord.Forbidden, discord.HTTPException, ValueError):
                logger.warning("Reminder %s konnte nicht zugestellt werden", row["id"])
                continue
            except Exception:
                logger.exception("Unbekannter Fehler beim Reminder %s", row["id"])
                continue

            conn = get_db()
            cur = conn.cursor()
            cur.execute("UPDATE reminders SET sent=1 WHERE id=? AND sent=0", (row["id"],))
            conn.commit()
            conn.close()

    @_loop.before_loop
    async def _before_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(SchedulerV2(bot))
