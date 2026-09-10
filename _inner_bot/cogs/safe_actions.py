"""Safe, non-AI external status actions for ScratchAI.

All network targets are fixed to documented public APIs. Users cannot supply
arbitrary URLs to the bot. Minecraft status is kept separate from the custom
command database/connector and only performs a public status lookup.
"""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request

import discord
from discord.ext import commands


TIMEOUT = 8
USER_AGENT = "ScratchAI-Discord-Bot/1.0"


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("API returned an unexpected response")
    return data


def _get_text(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        body = response.read(512).decode("utf-8", errors="replace")
        return int(response.status), body


def minecraft_status(host: str) -> dict:
    safe_host = host.strip()
    if not safe_host or len(safe_host) > 255 or any(c in safe_host for c in " /\\\"'`\n\r"):
        raise ValueError("ungültige Serveradresse")
    url = "https://api.mcsrvstat.us/3/" + urllib.parse.quote(safe_host, safe=".:[]-_")
    return _get_json(url)


def weather(latitude: float, longitude: float) -> dict:
    query = urllib.parse.urlencode({
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "timezone": "auto",
    })
    return _get_json("https://api.open-meteo.com/v1/forecast?" + query)


def website_status(url: str) -> tuple[int, str]:
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("nur http:// oder https:// erlaubt")
    # The command is deliberately restricted to domains configured by the owner.
    allowed = {
        item.strip().lower()
        for item in os.environ.get("WEBSITE_STATUS_DOMAINS", "").split(",")
        if item.strip()
    }
    if parsed.hostname.lower() not in allowed:
        raise ValueError("Domain ist nicht in WEBSITE_STATUS_DOMAINS freigegeben")
    return _get_text(url)


class SafeActions(commands.Cog):
    """Public status commands without arbitrary HTTP execution."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="mcstatus", aliases=["mc"])
    async def mcstatus(self, ctx: commands.Context, host: str):
        try:
            data = await asyncio.to_thread(minecraft_status, host)
        except Exception:
            await ctx.reply("❌ Minecraft-Status konnte gerade nicht abgefragt werden.", mention_author=False)
            return
        online = bool(data.get("online"))
        embed = discord.Embed(
            title=f"⛏️ Minecraft — {host}",
            description="🟢 Online" if online else "🔴 Offline",
        )
        if online:
            players = data.get("players") or {}
            version = (data.get("version") or {}).get("name") if isinstance(data.get("version"), dict) else data.get("version")
            embed.add_field(name="Spieler", value=f"{players.get('online', 0)}/{players.get('max', '?')}", inline=True)
            if version:
                embed.add_field(name="Version", value=str(version), inline=True)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="weather")
    async def weather_command(self, ctx: commands.Context, latitude: float, longitude: float):
        """!weather <latitude> <longitude> — no API key required."""
        try:
            data = await asyncio.to_thread(weather, latitude, longitude)
            current = data.get("current", {})
        except Exception:
            await ctx.reply("❌ Wetter konnte gerade nicht abgefragt werden.", mention_author=False)
            return
        embed = discord.Embed(title="🌤️ Wetter")
        embed.add_field(name="Temperatur", value=f"{current.get('temperature_2m', '?')} °C", inline=True)
        embed.add_field(name="Gefühlt", value=f"{current.get('apparent_temperature', '?')} °C", inline=True)
        embed.add_field(name="Wind", value=f"{current.get('wind_speed_10m', '?')} km/h", inline=True)
        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="webstatus")
    async def webstatus(self, ctx: commands.Context, url: str):
        try:
            status, _ = await asyncio.to_thread(website_status, url)
        except Exception as exc:
            await ctx.reply(f"❌ Website-Check nicht möglich: `{exc}`", mention_author=False)
            return
        icon = "🟢" if 200 <= status < 400 else "🔴"
        await ctx.reply(f"{icon} `{url}` → HTTP **{status}**", mention_author=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(SafeActions(bot))
