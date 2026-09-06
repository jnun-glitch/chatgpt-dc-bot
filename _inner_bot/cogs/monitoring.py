"""System diagnostics and bounded runtime metrics."""
from __future__ import annotations

import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands

from core.db import get_db
from core.logging import logger
from core.monitoring import increment, observe_latency, record_event, snapshot


class MonitoringCog(commands.Cog):
    """Owner/admin diagnostics without adding many top-level commands."""

    system = app_commands.Group(name="system", description="Systemstatus, Diagnostik und Metriken")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @system.command(name="diagnostics", description="Prüft Bot, Datenbank, Commands und Laufzeit")
    @app_commands.default_permissions(administrator=True)
    async def diagnostics(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Nur Server-Admins können die Diagnostik ausführen.", ephemeral=True)
            return
        started = time.perf_counter()
        await interaction.response.defer(ephemeral=True)
        checks: list[str] = []
        checks.append(f"🤖 Discord: **OK** · {self.bot.latency * 1000:.0f} ms")
        try:
            conn = get_db()
            conn.execute("SELECT 1")
            conn.close()
            checks.append("🗄️ Datenbank: **OK**")
        except Exception as exc:
            increment("diagnostics.db_error")
            logger.exception("Diagnostics DB check failed", exc_info=exc)
            checks.append("🗄️ Datenbank: **FEHLER**")
        root = len(self.bot.tree.get_commands())
        checks.append(f"⚙️ Slash-Commands: **{root}/100 Top-Level**")
        checks.append(f"🧩 Cogs: **{len(getattr(self.bot, 'cogs', {}))}**")
        checks.append(f"🏠 Server: **{len(self.bot.guilds)}**")
        snap = snapshot()
        lat = snap["latency"]
        if lat["p95_ms"] is not None:
            checks.append(f"📈 Runtime-Latenz: Ø **{lat['avg_ms']:.1f} ms**, P95 **{lat['p95_ms']:.1f} ms**")
        elapsed = (time.perf_counter() - started) * 1000
        observe_latency("diagnostics", elapsed)
        record_event("diagnostics", guild_id=interaction.guild.id, status="ok")
        embed = discord.Embed(title="🩺 ScratchAI System-Diagnose", description="\n".join(checks), color=discord.Color.green())
        embed.set_footer(text="Keine Nachrichteninhalte oder Tokens werden in den Metriken gespeichert.")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @system.command(name="metrics", description="Zeigt Laufzeit-Metriken des Bots")
    @app_commands.default_permissions(administrator=True)
    async def metrics(self, interaction: discord.Interaction):
        if not interaction.guild or not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Nur Server-Admins können Metriken sehen.", ephemeral=True)
            return
        snap = snapshot()
        counters = snap["counters"]
        interesting = [
            (key, value) for key, value in sorted(counters.items())
            if not key.startswith("latency.")
        ][-12:]
        lines = [f"⏱️ Uptime: **{snap['uptime_seconds'] / 3600:.1f} h**"]
        if snap["latency"]["avg_ms"] is not None:
            lines.append(f"📈 Latenz: Ø **{snap['latency']['avg_ms']:.1f} ms** · P95 **{snap['latency']['p95_ms']:.1f} ms**")
        lines.append(f"📦 Events: **{len(snap['recent_events'])}** im letzten Fenster")
        if interesting:
            lines.append("\n".join(f"• `{key}`: **{value}**" for key, value in interesting))
        else:
            lines.append("• Noch keine Runtime-Ereignisse aufgezeichnet.")
        embed = discord.Embed(title="📊 ScratchAI Metriken", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @commands.Cog.listener()
    async def on_ready(self):
        increment("discord.ready")
        record_event("discord_ready", guild_id="global")

    @commands.Cog.listener()
    async def on_disconnect(self):
        increment("discord.disconnect")
        record_event("discord_disconnect", status="reconnecting")

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command: app_commands.Command):
        increment("commands.completed")
        record_event("command", command=command.qualified_name, guild_id=interaction.guild_id, status="ok")

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):
        increment("commands.error")
        record_event("command_error", command=getattr(ctx.command, "qualified_name", "unknown"), status=type(error).__name__)


async def setup(bot: commands.Bot):
    await bot.add_cog(MonitoringCog(bot))
