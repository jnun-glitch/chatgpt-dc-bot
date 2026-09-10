"""On-demand YouTube channel status/count command."""
from __future__ import annotations

import asyncio
import os
import urllib.parse
import urllib.request
import json

import discord
from discord.ext import commands


def youtube_channel(identifier: str) -> dict:
    key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY fehlt")
    value = identifier.strip()
    params = {"part": "snippet,statistics", "key": key, "maxResults": "1"}
    if value.startswith("UC") and len(value) >= 20:
        params["id"] = value
    else:
        params["forHandle"] = value.lstrip("@").lstrip("/")
    url = "https://www.googleapis.com/youtube/v3/channels?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": "ScratchAI-Discord-Bot/1.0"})
    with urllib.request.urlopen(request, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8"))
    items = data.get("items") or []
    if not items:
        raise ValueError("YouTube-Kanal nicht gefunden")
    return items[0]


class YouTubeStatus(commands.Cog):
    @commands.command(name="youtube", aliases=["yt"])
    async def youtube(self, ctx: commands.Context, channel: str):
        try:
            item = await asyncio.to_thread(youtube_channel, channel)
        except Exception as exc:
            await ctx.reply(f"❌ YouTube konnte nicht abgefragt werden: `{exc}`", mention_author=False)
            return
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        title = snippet.get("title") or channel
        channel_id = item.get("id")
        embed = discord.Embed(title=f"▶️ {title}")
        embed.add_field(name="Abonnenten", value=str(stats.get("subscriberCount", "—")), inline=True)
        embed.add_field(name="Videos", value=str(stats.get("videoCount", "—")), inline=True)
        embed.add_field(name="Aufrufe", value=str(stats.get("viewCount", "—")), inline=True)
        if channel_id:
            embed.url = f"https://www.youtube.com/channel/{channel_id}"
        await ctx.reply(embed=embed, mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(YouTubeStatus(bot))
