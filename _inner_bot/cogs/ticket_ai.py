"""Permission-checked ticket AI analysis without colliding with the existing /ai command.

Command: /ticket-ai analyze
The legacy !ai path remains available in bot.py for backwards compatibility.
"""
from __future__ import annotations

import asyncio
import os

import discord
from discord import app_commands
from discord.ext import commands

from core.ai_ticket import analyze_ticket
from core.ai_ticket_runtime import TicketAIRuntime
from core.db import get_ticket_by_channel, update_ticket_ai
from core.logging import logger


RUNTIME = TicketAIRuntime(
    max_concurrency=max(1, int(os.environ.get("TICKET_AI_MAX_CONCURRENCY", "2") or 2)),
    cooldown_seconds=max(0, int(os.environ.get("TICKET_AI_COOLDOWN_SECONDS", "300") or 300)),
)


class TicketAICog(commands.Cog):
    """Ticket AI with permission checks and bounded execution."""

    ticket_ai = app_commands.Group(name="ticket-ai", description="Ticket-AI Analyse")

    @ticket_ai.command(name="analyze", description="Analysiert den aktuellen Ticketverlauf")
    @app_commands.describe(zeilen="Maximale Anzahl Nachrichten im Verlauf")
    @app_commands.default_permissions(manage_channels=True)
    async def analyze(self, interaction: discord.Interaction, zeilen: int = 500):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Nur auf einem Server verfügbar.", ephemeral=True)
            return
        if not (
            interaction.user.guild_permissions.administrator
            or interaction.user.guild_permissions.manage_channels
            or interaction.user.guild_permissions.manage_messages
        ):
            await interaction.response.send_message("⛔ Du brauchst eine Moderations-/Ticket-Berechtigung.", ephemeral=True)
            return

        ticket = get_ticket_by_channel(str(interaction.channel_id))
        if not ticket:
            await interaction.response.send_message("❌ Dieser Kanal ist kein registriertes Ticket.", ephemeral=True)
            return

        limit = min(max(10, int(zeilen)), 1000)
        await interaction.response.defer(ephemeral=True, thinking=True)

        lines = [
            f"Ticket #{ticket['ticket_number']:04d}",
            f"Kategorie: {ticket.get('kategorie', 'Sonstiges')}",
            f"Betreff: {ticket.get('betreff', 'Kein Betreff')}",
            "",
            "TICKETVERLAUF:",
        ]
        try:
            async for msg in interaction.channel.history(limit=limit, oldest_first=True):
                if msg.content.strip().lower() in {"!ai", "/ai"}:
                    continue
                content = msg.content.strip() or "[Kein Text]"
                if msg.attachments:
                    content += " [Anhänge: " + ", ".join(a.filename for a in msg.attachments[:10]) + "]"
                lines.append(f"[{msg.created_at.strftime('%Y-%m-%d %H:%M')}] {msg.author.display_name}: {content}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Ich darf den Ticketverlauf nicht lesen.", ephemeral=True)
            return

        transcript = "\n".join(lines)
        if len(transcript) > 60000:
            transcript = transcript[:12000] + "\n\n[... älterer Verlauf gekürzt ...]\n\n" + transcript[-47000:]

        async def work() -> str:
            return await asyncio.to_thread(analyze_ticket, transcript)

        key = f"{interaction.guild.id}:{interaction.channel_id}"
        try:
            verdict = await RUNTIME.run(key, work)
        except RuntimeError as exc:
            text = str(exc)
            if text.startswith("cooldown:"):
                remaining = text.split(":", 1)[1]
                await interaction.followup.send(f"⏳ Ticket-AI ist noch im Cooldown ({remaining}s).", ephemeral=True)
            else:
                await interaction.followup.send("❌ Ticket-AI konnte nicht gestartet werden.", ephemeral=True)
            return
        except Exception:
            logger.exception("Ticket-AI slash analysis failed")
            await interaction.followup.send("❌ Die Ticket-AI-Analyse ist fehlgeschlagen.", ephemeral=True)
            return

        try:
            update_ticket_ai(str(interaction.channel_id), verdict)
        except Exception:
            logger.exception("Ticket-AI result could not be persisted")

        embed = discord.Embed(
            title=f"🤖 Ticket-AI #{ticket['ticket_number']:04d}",
            description=verdict[:4096],
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Analyse auf Moderations-/Ticket-Ebene · begrenzte Parallelität aktiv")
        await interaction.followup.send(embed=embed, ephemeral=False)


async def setup(bot: commands.Bot):
    await bot.add_cog(TicketAICog(bot))
