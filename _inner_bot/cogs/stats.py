from __future__ import annotations

import time as _time
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from core.db import track_command_usage, get_command_usage, save_member_snapshot, get_member_history, _add_xp, _get_leaderboard
from core.config import BOT_DIR, LEVEL_ROLES
from cogs.dashboard import log_audit_event

try:
    import psutil
    PSUTIL_AVAILABLE = True
except Exception:
    psutil = None
    PSUTIL_AVAILABLE = False

_START_TIME = _time.time()


class StatsCog(commands.Cog):
    """Statistiken, System-Info und Leveling. Slash-Commands als Gruppe."""
    stats = app_commands.Group(name="stats", description="Statistiken und System-Informationen")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.application_command and interaction.command:
            track_command_usage(interaction.command.name)
            log_audit_event("command", {
                "user": str(interaction.user),
                "command": interaction.command.name,
                "channel": getattr(interaction.channel, "name", "DM"),
            })

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        new_level = _add_xp(str(message.author.id), str(message.guild.id))
        if new_level is None:
            return
        from core.db import format_msg
        lu_text = format_msg(message.guild.id, "levelup_msg", mention=message.author.mention, name=message.author.display_name, level=new_level)
        embed = discord.Embed(title="🎉 Level Up!", description=lu_text, color=discord.Color.gold())
        earned_role = None
        for req_level, role_name in sorted(LEVEL_ROLES.items()):
            if new_level >= req_level:
                role = discord.utils.get(message.guild.roles, name=role_name)
                if role:
                    earned_role = role
        if earned_role:
            try:
                await message.author.add_roles(earned_role, reason=f"Level {new_level} erreicht")
                lr_text = format_msg(message.guild.id, "levelup_role_msg", mention=message.author.mention, name=message.author.display_name, level=new_level, role=earned_role.name)
                embed.add_field(name="Rolle erhalten", value=lr_text, inline=False)
            except discord.Forbidden:
                embed.add_field(name="Rolle erhalten", value=f"⚠️ Keine Berechtigung für {earned_role.name}", inline=False)
        if datetime.now().weekday() in (5, 6):
            embed.set_footer(text="🔥 Double XP am Wochenende!")
        try:
            await message.channel.send(embed=embed)
        except discord.Forbidden:
            pass

    @stats.command(name="show", description="Zeigt Bot-Statistiken und die meistgenutzten Commands")
    async def cmd_stats(self, interaction: discord.Interaction):
        uptime_sec = int(_time.time() - _START_TIME)
        days, rem = divmod(uptime_sec, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        usage = get_command_usage(limit=10)
        lines = [f'{i+1}. `/{c["command"]}` – {c["used"]}x' for i, c in enumerate(usage)] or ["Noch keine Daten."]
        embed = discord.Embed(title="📊 Bot-Statistiken", color=discord.Color.blue())
        embed.add_field(name="Uptime", value=f"{days}d {hours}h {minutes}m", inline=True)
        embed.add_field(name="Server", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Commands", value=str(len(self.bot.tree.get_commands())), inline=True)
        embed.add_field(name="Meistgenutzte Commands", value="\n".join(lines), inline=False)
        await interaction.response.send_message(embed=embed)

    @stats.command(name="system", description="Zeigt System-Ressourcen (CPU, RAM, Disk)")
    async def cmd_system(self, interaction: discord.Interaction):
        if not PSUTIL_AVAILABLE:
            await interaction.response.send_message("psutil ist nicht installiert (`pip install psutil`).", ephemeral=True)
            return
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(str(BOT_DIR))
        proc_mem = __import__("psutil").Process().memory_info().rss / 1024 / 1024
        embed = discord.Embed(title="🖥️ System", color=discord.Color.green())
        embed.add_field(name="CPU", value=f"{cpu}%", inline=True)
        embed.add_field(name="RAM", value=f"{mem.used / (1024**3):.1f} GB / {mem.total / (1024**3):.1f} GB ({mem.percent}%)", inline=True)
        embed.add_field(name="Disk", value=f"{disk.used / (1024**3):.1f} GB / {disk.total / (1024**3):.1f} GB", inline=True)
        embed.add_field(name="Bot-Prozess", value=f"{proc_mem:.1f} MB RAM", inline=True)
        await interaction.response.send_message(embed=embed)

    @stats.command(name="growth", description="Zeigt das Mitglieder-Wachstum des Servers")
    async def cmd_growth(self, interaction: discord.Interaction):
        history = get_member_history(interaction.guild_id, limit=14)
        save_member_snapshot(interaction.guild_id, interaction.guild.member_count)
        if len(history) < 2:
            await interaction.response.send_message(embed=discord.Embed(title="📈 Mitglieder-Wachstum", description=f"Aktuell: **{interaction.guild.member_count}** Mitglieder.\nWeitere Datenpunkte sammeln sich im Laufe der Zeit.", color=discord.Color.blue()))
            return
        history = history[::-1]
        max_count = max(h["count"] for h in history)
        bars = ["█" * max(1, int(8 * h["count"] / max_count)) for h in history]
        first, last = history[0]["count"], history[-1]["count"]
        delta = last - first
        arrow = "📈" if delta > 0 else "📉" if delta < 0 else "➖"
        embed = discord.Embed(title="📈 Mitglieder-Wachstum", description=f"{arrow} Von **{first}** auf **{last}** ({delta:+d})", color=discord.Color.blue())
        embed.add_field(name="Verlauf (letzte 14)", value="```\n" + "\n".join(bars) + "\n```", inline=False)
        await interaction.response.send_message(embed=embed)

    @stats.command(name="leaderboard", description="Zeigt die Top-Spieler nach Level und XP")
    @app_commands.describe(limit="Anzahl der Einträge (Standard: 10, max: 25)")
    async def cmd_leaderboard(self, interaction: discord.Interaction, limit: int = 10):
        limit = min(max(limit, 1), 25)
        entries = _get_leaderboard(str(interaction.guild_id), limit)
        if not entries:
            await interaction.response.send_message(embed=discord.Embed(title="🏆 Leaderboard", description="Noch keine Daten vorhanden.", color=discord.Color.gold()))
            return
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, e in enumerate(entries):
            medal = medals[i] if i < 3 else f"**{i+1}.**"
            member = interaction.guild.get_member(int(e["user_id"]))
            name = member.display_name if member else f"User {e['user_id']}"
            lines.append(f"{medal} **{name}** — Level {e['level']} | {e['xp']} XP")
        embed = discord.Embed(title="🏆 Leaderboard", description="\n".join(lines), color=discord.Color.gold())
        if datetime.now().weekday() in (5, 6):
            embed.set_footer(text="🔥 Double XP am Wochenende!")
        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(StatsCog(bot))
