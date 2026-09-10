"""Persist the existing AutoMod warning/timeout state across restarts.

This deliberately wraps the existing AutomodCog instead of duplicating its
filter pipeline, so current escalation behavior remains unchanged.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any

from discord.ext import commands

from cogs.automod import AutomodCog
from core.automod_strikes import get_strike_state, init_automod_strikes


class AutoModPersistenceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_automod_strikes()
        self._wrapped = False
        self._wrap_existing_automod()

    def _wrap_existing_automod(self) -> None:
        automod = self.bot.get_cog("AutomodCog")
        if automod is None or getattr(automod, "_persistent_strikes_wrapped", False):
            return

        original = automod._handle_violation

        @wraps(original)
        async def persistent_handle(message, reason: str, *, escalate: bool = True):
            guild = message.guild
            user = message.author
            if guild is not None and hasattr(user, "id"):
                state = get_strike_state(guild.id, user.id)
                automod._warn_cache[guild.id][user.id] = int(state.get("strikes", 0))
                automod._timeout_level[guild.id][user.id] = int(state.get("timeout_level", 0))

            result = await original(message, reason, escalate=escalate)

            if guild is not None and hasattr(user, "id"):
                from core.automod_strikes import save_strike_state
                save_strike_state(
                    guild.id,
                    user.id,
                    int(automod._warn_cache[guild.id][user.id]),
                    int(automod._timeout_level[guild.id][user.id]),
                    reason,
                )
            return result

        automod._handle_violation = persistent_handle
        automod._persistent_strikes_wrapped = True
        self._wrapped = True

    @commands.Cog.listener()
    async def on_ready(self):
        self._wrap_existing_automod()


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoModPersistenceCog(bot))
