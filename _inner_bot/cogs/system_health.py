"""Extended, secret-safe system health information."""
from __future__ import annotations

import importlib.util
import os

import discord
from discord import app_commands
from discord.ext import commands

from cogs.monitoring import MonitoringCog
from core.db import get_db
from core.logging import logger


class SystemHealthCog(commands.Cog):
    """Adds a deeper health subcommand to the existing /system group."""

    @MonitoringCog.system.command(name="health", description="Prüft APIs, Voice, Music und Cogs")
    @app_commands.default_permissions(administrator=True)
    async def health(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Nur Server-Admins können die Health-Prüfung ausführen.", ephemeral=True)
            return

        checks: list[str] = []

        # Configuration presence only. Never reveal actual secret values.
        config_keys = {
            "Discord Token": "DISCORD_TOKEN",
            "Twitch Client": "TWITCH_CLIENT_ID",
            "YouTube API": "YOUTUBE_API_KEY",
            "n8n Webhook": "N8N_WEBHOOK_URL",
        }
        for label, env_name in config_keys.items():
            checks.append(f"🔐 {label}: **{'konfiguriert' if os.environ.get(env_name, '').strip() else 'nicht gesetzt'}**")

        try:
            conn = get_db()
            conn.execute("SELECT 1")
            conn.close()
            checks.append("🗄️ Datenbank: **OK**")
        except Exception:
            logger.exception("Health DB check failed")
            checks.append("🗄️ Datenbank: **FEHLER**")

        voice_connected = sum(1 for guild in self.bot.guilds if guild.voice_client and guild.voice_client.is_connected())
        checks.append(f"🔊 Voice-Verbindungen: **{voice_connected}**")

        music_available = all(importlib.util.find_spec(name) is not None for name in ("yt_dlp", "nacl"))
        try:
            import shutil
            music_available = music_available and bool(shutil.which("ffmpeg") or shutil.which("ffmpeg.exe"))
        except Exception:
            music_available = False
        checks.append(f"🎵 Music-Dependencies: **{'OK' if music_available else 'FEHLEN'}**")

        checks.append(f"🧩 Geladene Cogs: **{len(self.bot.cogs)}**")
        checks.append(f"⚙️ Slash-Root-Commands: **{len(self.bot.tree.get_commands())}/100**")
        checks.append(f"🌐 Server: **{len(self.bot.guilds)}**")

        embed = discord.Embed(
            title="🩺 ScratchAI Health Check",
            description="\n".join(checks),
            color=discord.Color.green(),
        )
        embed.set_footer(text="Es werden nur Konfigurationszustände angezeigt – keine Secrets.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(SystemHealthCog(bot))
