"""On-demand Twitch live-status command.

Uses the existing Twitch API helpers from cogs.social so credentials and token
handling stay in one place. No Twitch password or user login is requested.
"""
from __future__ import annotations

import asyncio
import os

import discord
from discord.ext import commands

from cogs.social import make_twitch_embed, twitch_stream, twitch_user


TWITCH_DEFAULT_CHANNEL = os.environ.get("TWITCH_DEFAULT_CHANNEL", "").strip().lstrip("@").lower()


class StreamStatusCog(commands.Cog):
    """Provide a lightweight !stream command for Twitch status checks."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="stream", aliases=["live"])
    async def stream(self, ctx: commands.Context, channel: str | None = None):
        """Show whether a Twitch channel is currently live."""
        login = (channel or TWITCH_DEFAULT_CHANNEL).strip().lstrip("@").lower()
        if not login:
            await ctx.reply("❌ Nutze `!stream <twitch-kanal>` oder setze `TWITCH_DEFAULT_CHANNEL`.", mention_author=False)
            return

        try:
            user = await asyncio.to_thread(twitch_user, login)
            login = str(user.get("login") or login).lower()
            stream = await asyncio.to_thread(twitch_stream, login)
        except (RuntimeError, ValueError) as exc:
            await ctx.reply(f"❌ Twitch konnte nicht abgefragt werden: `{exc}`", mention_author=False)
            return
        except Exception:
            await ctx.reply("❌ Die Twitch-Abfrage ist gerade fehlgeschlagen.", mention_author=False)
            return

        if not stream:
            await ctx.reply(f"⚫ **{user.get('display_name') or login}** ist gerade nicht live.", mention_author=False)
            return

        embed = make_twitch_embed(stream, login)
        await ctx.reply(embed=embed, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(StreamStatusCog(bot))
