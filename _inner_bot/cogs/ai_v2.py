"""AI V2 runtime maintenance.

This intentionally adds no new Slash-Commands.  It keeps the existing AI
interface stable while preventing per-user rate-limit state from growing
forever and exposing a small internal health snapshot for diagnostics.
"""
from __future__ import annotations

import time

from discord.ext import commands, tasks

from cogs import ai as ai_module
from core.logging import logger


class AIV2Runtime(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cleanup.start()

    def cog_unload(self):
        self._cleanup.cancel()

    @tasks.loop(minutes=5)
    async def _cleanup(self):
        now = time.monotonic()
        cutoff = now - ai_module._ASK_WINDOW
        removed = 0
        for key, recent in list(ai_module._ask_rate_limit.items()):
            while recent and recent[0] <= cutoff:
                recent.popleft()
            if not recent:
                ai_module._ask_rate_limit.pop(key, None)
                removed += 1
        if removed:
            logger.debug("AI rate-limit cleanup: %s inaktive Sessions entfernt", removed)

    @_cleanup.before_loop
    async def _before_cleanup(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(AIV2Runtime(bot))
