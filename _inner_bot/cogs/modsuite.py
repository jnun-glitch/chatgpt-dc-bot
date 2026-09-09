"""ScratchAI Moderation Suite.

Original moderation tooling for ScratchAI.  The feature set is inspired by
common community-bot patterns but implemented specifically for this project.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core.channelnames import find_channel
from core.db import get_db
from core.logging import logger


class ModerationSuite(commands.Cog):
    """Cases, warnings, expiry, points and controlled escalation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ensure_tables()
        self._expiry_loop.start()

    def cog_unload(self):
        self._expiry_loop.cancel()

    @staticmethod
    def _ensure_tables() -> None:
        conn = get_db()
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS mod_cases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                moderator_id TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT NOT NULL,
                active INTEGER DEFAULT 1,
                points INTEGER DEFAULT 0,
                expires_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_mod_cases_user ON mod_cases(guild_id, user_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mod_cases_guild ON mod_cases(guild_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_mod_cases_expiry ON mod_cases(expires_at, active);
            """
        )
        columns = {row[1] for row in cur.execute("PRAGMA table_info(mod_cases)").fetchall()}
        if "points" not in columns:
            cur.execute("ALTER TABLE mod_cases ADD COLUMN points INTEGER DEFAULT 0")
        if "expires_at" not in columns:
            cur.execute("ALTER TABLE mod_cases ADD COLUMN expires_at TIMESTAMP")
        warn_columns = {row[1] for row in cur.execute("PRAGMA table_info(user_warns)").fetchall()}
        if "case_id" not in warn_columns:
            cur.execute("ALTER TABLE user_warns ADD COLUMN case_id INTEGER")
        if "expires_at" not in warn_columns:
            cur.execute("ALTER TABLE user_warns ADD COLUMN expires_at TIMESTAMP")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_warns_case ON user_warns(case_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_user_warns_expiry ON user_warns(expires_at)")
        conn.commit()
        conn.close()

    @staticmethod
    def _env_int(name: str, default: int, minimum: int = 0) -> int:
        try:
            return max(minimum, int(os.getenv(name, str(default))))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _warn_duration_days(cls) -> int:
        return cls._env_int("WARN_EXPIRY_DAYS", 30, 0)

    @classmethod
    def _points_for_warn(cls) -> int:
        return cls._env_int("WARN_POINTS", 1, 1)

    @classmethod
    def _escalation_threshold(cls) -> int:
        return cls._env_int("WARN_ESCALATION_THRESHOLD", 3, 2)

    @classmethod
    def _escalation_minutes(cls) -> int:
        return cls._env_int("WARN_ESCALATION_MINUTES", 10, 1)

    @staticmethod
    def _case(
        guild_id: int,
        user_id: int,
        moderator_id: int,
        action: str,
        reason: str,
        points: int = 0,
        expires_at: str | None = None,
    ) -> int:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO mod_cases (guild_id,user_id,moderator_id,action,reason,points,expires_at) VALUES (?,?,?,?,?,?,?)",
            (str(guild_id), str(user_id), str(moderator_id), action, reason[:1000], points, expires_at),
        )
        cid = cur.lastrowid
        conn.commit()
        conn.close()
        return int(cid)

    @staticmethod
    def _fetch_cases(guild_id: int, user_id: int | None = None, limit: int = 15):
        conn = get_db()
        cur = conn.cursor()
        if user_id is None:
            cur.execute(
                "SELECT id,user_id,moderator_id,action,reason,active,points,expires_at,created_at FROM mod_cases WHERE guild_id=? ORDER BY id DESC LIMIT ?",
                (str(guild_id), limit),
            )
        else:
            cur.execute(
                "SELECT id,user_id,moderator_id,action,reason,active,points,expires_at,created_at FROM mod_cases WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
                (str(guild_id), str(user_id), limit),
            )
        rows = cur.fetchall()
        conn.close()
        return rows

    @staticmethod
    def _active_points(guild_id: int, user_id: int) -> int:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT COALESCE(SUM(points),0) FROM mod_cases WHERE guild_id=? AND user_id=? AND action='WARN' AND active=1",
            (str(guild_id), str(user_id)),
        )
        value = int(cur.fetchone()[0] or 0)
        conn.close()
        return value

    async def _log_case(self, guild: discord.Guild, case_id: int, target: discord.abc.User, moderator: discord.abc.User, action: str, reason: str, points: int = 0, expires_at: str | None = None):
        try:
            channel = find_channel(guild, "admin-log")
            if not channel:
                return
            embed = discord.Embed(
                title=f"🛡️ Case #{case_id:04d} · {action}",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow(),
            )
            embed.add_field(name="User", value=f"{target.mention} (`{target.id}`)", inline=False)
            embed.add_field(name="Moderator", value=f"{moderator.mention} (`{moderator.id}`)", inline=True)
            if points:
                embed.add_field(name="Punkte", value=str(points), inline=True)
            if expires_at:
                embed.add_field(name="Läuft ab", value=expires_at, inline=True)
            embed.add_field(name="Grund", value=reason[:1024], inline=False)
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            logger.warning("Moderations-Log konnte nicht gesendet werden")

    @tasks.loop(minutes=1)
    async def _expiry_loop(self):
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id,user_id,guild_id FROM mod_cases WHERE action='WARN' AND active=1 AND expires_at IS NOT NULL AND expires_at <= ?",
            (now,),
        )
        expired = cur.fetchall()
        if expired:
            ids = [int(row["id"]) for row in expired]
            cur.executemany("UPDATE mod_cases SET active=0 WHERE id=?", [(cid,) for cid in ids])
            cur.executemany("DELETE FROM user_warns WHERE case_id=?", [(cid,) for cid in ids])
            conn.commit()
        conn.close()

    @_expiry_loop.before_loop
    async def _before_expiry_loop(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="modlog", description="Zeigt die letzten Moderationsfälle dieses Servers")
    @app_commands.default_permissions(moderate_members=True)
    async def modlog(self, interaction: discord.Interaction):
        rows = self._fetch_cases(interaction.guild_id, limit=10)
        if not rows:
            return await interaction.response.send_message("📋 Noch keine Moderationsfälle gespeichert.", ephemeral=True)
        lines = []
        for row in rows:
            status = "aktiv" if row["active"] else "abgelaufen/entfernt"
            lines.append(f"`#{row['id']:04d}` **{row['action']}** · <@{row['user_id']}> · {status} · {row['reason'][:90]}")
        embed = discord.Embed(title="📋 Moderationsfälle", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="modhistory", description="Zeigt die Moderationshistorie eines Users")
    @app_commands.describe(user="User")
    @app_commands.default_permissions(moderate_members=True)
    async def modhistory(self, interaction: discord.Interaction, user: discord.Member):
        rows = self._fetch_cases(interaction.guild_id, user.id, 15)
        if not rows:
            return await interaction.response.send_message(f"📋 Für {user.mention} gibt es keine Moderationsfälle.", ephemeral=True)
        lines = [f"`#{r['id']:04d}` **{r['action']}** · {r['reason'][:110]} · <@{r['moderator_id']}> · {r['created_at']}" for r in rows]
        embed = discord.Embed(title=f"📋 Historie · {user.display_name}", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="warn-remove", description="Entfernt eine einzelne aktive Verwarnung")
    @app_commands.describe(case_id="Case-ID der Verwarnung")
    @app_commands.default_permissions(moderate_members=True)
    async def warn_remove(self, interaction: discord.Interaction, case_id: int):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("UPDATE mod_cases SET active=0 WHERE guild_id=? AND id=? AND action='WARN' AND active=1", (str(interaction.guild_id), case_id))
        changed = cur.rowcount
        row = None
        if changed:
            cur.execute("SELECT user_id FROM mod_cases WHERE guild_id=? AND id=?", (str(interaction.guild_id), case_id))
            row = cur.fetchone()
            cur.execute("DELETE FROM user_warns WHERE case_id=?", (case_id,))
        conn.commit()
        conn.close()
        if not changed:
            return await interaction.response.send_message("❌ Dieser aktive WARN-Case wurde nicht gefunden.", ephemeral=True)
        await interaction.response.send_message(f"✅ Verwarnung `#{case_id:04d}` wurde entfernt und zählt nicht mehr.", ephemeral=True)
        if row:
            await self._log_case(interaction.guild, case_id, interaction.guild.get_member(int(row["user_id"])) or discord.Object(id=int(row["user_id"])), interaction.user, "WARN-REMOVE", "Verwarnung manuell entfernt")

    @app_commands.command(name="case", description="Zeigt einen einzelnen Moderationsfall")
    @app_commands.describe(case_id="Case-ID")
    @app_commands.default_permissions(moderate_members=True)
    async def case(self, interaction: discord.Interaction, case_id: int):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM mod_cases WHERE guild_id=? AND id=?", (str(interaction.guild_id), case_id))
        row = cur.fetchone()
        conn.close()
        if not row:
            return await interaction.response.send_message("❌ Case nicht gefunden.", ephemeral=True)
        embed = discord.Embed(title=f"🛡️ Case #{case_id:04d}", color=discord.Color.orange())
        embed.add_field(name="Aktion", value=row["action"])
        embed.add_field(name="Status", value="aktiv" if row["active"] else "abgelaufen/entfernt")
        embed.add_field(name="Punkte", value=str(row["points"] or 0))
        embed.add_field(name="User", value=f"<@{row['user_id']}> (`{row['user_id']}`)", inline=False)
        embed.add_field(name="Moderator", value=f"<@{row['moderator_id']}> (`{row['moderator_id']}`)", inline=False)
        embed.add_field(name="Grund", value=row["reason"][:1024], inline=False)
        if row["expires_at"]:
            embed.add_field(name="Ablauf", value=str(row["expires_at"]), inline=False)
        embed.set_footer(text=f"Erstellt: {row['created_at']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="warn-add", description="Fügt eine Verwarnung hinzu, erstellt einen Case und zählt Punkte")
    @app_commands.describe(user="User", grund="Grund")
    @app_commands.default_permissions(moderate_members=True)
    async def warn_add(self, interaction: discord.Interaction, user: discord.Member, grund: str):
        if user.id == interaction.user.id:
            return await interaction.response.send_message("❌ Du kannst dich nicht selbst verwarnen.", ephemeral=True)
        if user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Administratoren können damit nicht verwarnt werden.", ephemeral=True)
        if not grund.strip():
            return await interaction.response.send_message("❌ Ein Grund ist erforderlich.", ephemeral=True)

        points = self._points_for_warn()
        days = self._warn_duration_days()
        expires_at = None
        if days > 0:
            expires_at = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")

        cid = self._case(interaction.guild_id, user.id, interaction.user.id, "WARN", grund, points, expires_at)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_warns (user_id,guild_id,grund,von,case_id,expires_at) VALUES (?,?,?,?,?,?)",
            (str(user.id), str(interaction.guild_id), grund[:1000], str(interaction.user), cid, expires_at),
        )
        conn.commit()
        conn.close()

        total_points = self._active_points(interaction.guild_id, user.id)
        await interaction.response.send_message(
            f"⚠️ {user.mention} wurde verwarnt. **Case #{cid:04d}** · **{total_points} Punkte**",
            ephemeral=True,
        )
        await self._log_case(interaction.guild, cid, user, interaction.user, "WARN", grund, points, expires_at)

        threshold = self._escalation_threshold()
        if total_points >= threshold and not user.guild_permissions.administrator:
            minutes = self._escalation_minutes()
            try:
                until = discord.utils.utcnow() + timedelta(minutes=minutes)
                await user.timeout(until, reason=f"Automatische Eskalation nach {total_points} Verwarnungspunkten")
                escalation_case = self._case(
                    interaction.guild_id,
                    user.id,
                    interaction.guild.me.id if interaction.guild.me else self.bot.user.id,
                    "AUTO-TIMEOUT",
                    f"Automatische Eskalation nach {total_points} Verwarnungspunkten",
                )
                await self._log_case(interaction.guild, escalation_case, user, interaction.guild.me or self.bot.user, "AUTO-TIMEOUT", f"{total_points} aktive Verwarnungspunkte; Timeout {minutes} Minuten")
                await interaction.followup.send(f"🛡️ Automatische Eskalation: {user.mention} wurde für **{minutes} Minuten** in den Timeout gesetzt.", ephemeral=True)
            except (discord.Forbidden, discord.HTTPException):
                logger.warning("Automatische Warn-Eskalation fehlgeschlagen für %s", user.id)

    @app_commands.command(name="cases", description="Zeigt aktuelle Moderationsstatistiken")
    @app_commands.default_permissions(moderate_members=True)
    async def cases(self, interaction: discord.Interaction):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT action, COUNT(*) AS count FROM mod_cases WHERE guild_id=? AND active=1 GROUP BY action ORDER BY count DESC", (str(interaction.guild_id),))
        rows = cur.fetchall()
        cur.execute("SELECT COALESCE(SUM(points),0) FROM mod_cases WHERE guild_id=? AND action='WARN' AND active=1", (str(interaction.guild_id),))
        points = int(cur.fetchone()[0] or 0)
        conn.close()
        desc = "\n".join(f"**{r['action']}**: {r['count']}" for r in rows) or "Noch keine aktiven Cases."
        embed = discord.Embed(title="📊 Moderationsübersicht", description=desc, color=discord.Color.blurple())
        embed.add_field(name="Aktive Warnpunkte", value=str(points))
        embed.add_field(name="Warn-Ablauf", value=f"{self._warn_duration_days()} Tage" if self._warn_duration_days() else "Nie")
        embed.add_field(name="Eskalation", value=f"ab {self._escalation_threshold()} Punkten → {self._escalation_minutes()} Min Timeout")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationSuite(bot))
