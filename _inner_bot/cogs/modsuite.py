"""ScratchAI Moderation Suite.

Inspired by common moderation-bot patterns, but implemented specifically for ScratchAI.
Adds a compact case system and moderator tooling without copying another bot's implementation.
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from core.db import get_db
from core.channelnames import find_channel


class ModerationSuite(commands.Cog):
    """Case history, warning management and moderation utilities."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._ensure_tables()

    @staticmethod
    def _ensure_tables() -> None:
        conn = get_db()
        cur = conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS mod_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            moderator_id TEXT NOT NULL,
            action TEXT NOT NULL,
            reason TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_mod_cases_user ON mod_cases(guild_id, user_id, id DESC);
        CREATE INDEX IF NOT EXISTS idx_mod_cases_guild ON mod_cases(guild_id, id DESC);
        """)
        columns = {row[1] for row in cur.execute("PRAGMA table_info(user_warns)").fetchall()}
        if "case_id" not in columns:
            cur.execute("ALTER TABLE user_warns ADD COLUMN case_id INTEGER")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_user_warns_case ON user_warns(case_id)")
        conn.commit()
        conn.close()

    @staticmethod
    def _case(guild_id: int, user_id: int, moderator_id: int, action: str, reason: str) -> int:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO mod_cases (guild_id,user_id,moderator_id,action,reason) VALUES (?,?,?,?,?)",
            (str(guild_id), str(user_id), str(moderator_id), action, reason[:1000]),
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
                "SELECT id,user_id,moderator_id,action,reason,created_at FROM mod_cases WHERE guild_id=? ORDER BY id DESC LIMIT ?",
                (str(guild_id), limit),
            )
        else:
            cur.execute(
                "SELECT id,user_id,moderator_id,action,reason,created_at FROM mod_cases WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT ?",
                (str(guild_id), str(user_id), limit),
            )
        rows = cur.fetchall()
        conn.close()
        return rows

    async def _log_case(self, guild: discord.Guild, case_id: int, target: discord.abc.User, moderator: discord.abc.User, action: str, reason: str):
        try:
            channel = find_channel(guild, "admin-log")
            if not channel:
                return
            embed = discord.Embed(title=f"🛡️ Case #{case_id:04d} · {action}", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
            embed.add_field(name="User", value=f"{target.mention} (`{target.id}`)", inline=False)
            embed.add_field(name="Moderator", value=f"{moderator.mention} (`{moderator.id}`)", inline=True)
            embed.add_field(name="Grund", value=reason[:1024], inline=False)
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            pass

    @app_commands.command(name="modlog", description="Zeigt die letzten Moderationsfälle dieses Servers")
    @app_commands.default_permissions(moderate_members=True)
    async def modlog(self, interaction: discord.Interaction):
        rows = self._fetch_cases(interaction.guild_id, limit=10)
        if not rows:
            return await interaction.response.send_message("📋 Noch keine Moderationsfälle gespeichert.", ephemeral=True)
        lines = [f"`#{row['id']:04d}` **{row['action']}** · <@{row['user_id']}> · {row['reason'][:100]}" for row in rows]
        embed = discord.Embed(title="📋 Moderationsfälle", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="modhistory", description="Zeigt die Moderationshistorie eines Users")
    @app_commands.describe(user="User")
    @app_commands.default_permissions(moderate_members=True)
    async def modhistory(self, interaction: discord.Interaction, user: discord.Member):
        rows = self._fetch_cases(interaction.guild_id, user.id, 15)
        if not rows:
            return await interaction.response.send_message(f"📋 Für {user.mention} gibt es keine Moderationsfälle.", ephemeral=True)
        lines = [f"`#{r['id']:04d}` **{r['action']}** · {r['reason'][:120]} · <@{r['moderator_id']}>" for r in rows]
        embed = discord.Embed(title=f"📋 Historie · {user.display_name}", description="\n".join(lines), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="warn-remove", description="Entfernt eine einzelne Verwarnung")
    @app_commands.describe(case_id="Case-ID der Verwarnung")
    @app_commands.default_permissions(moderate_members=True)
    async def warn_remove(self, interaction: discord.Interaction, case_id: int):
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE mod_cases SET active=0 WHERE guild_id=? AND id=? AND action='WARN' AND active=1",
            (str(interaction.guild_id), case_id),
        )
        changed = cur.rowcount
        row = None
        if changed:
            cur.execute(
                "SELECT user_id FROM mod_cases WHERE guild_id=? AND id=?",
                (str(interaction.guild_id), case_id),
            )
            row = cur.fetchone()
            cur.execute("DELETE FROM user_warns WHERE case_id=?", (case_id,))
        conn.commit()
        conn.close()
        if not changed:
            return await interaction.response.send_message("❌ Dieser aktive WARN-Case wurde nicht gefunden.", ephemeral=True)
        await interaction.response.send_message(f"✅ Verwarnung `#{case_id:04d}` wurde entfernt und zählt nicht mehr.", ephemeral=True)
        if row:
            try:
                channel = find_channel(interaction.guild, "admin-log")
                if channel:
                    await channel.send(f"🧹 WARN-Case `#{case_id:04d}` von <@{row['user_id']}> wurde von {interaction.user.mention} entfernt.")
            except (discord.Forbidden, discord.HTTPException):
                pass

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
        embed.add_field(name="Status", value="aktiv" if row["active"] else "entfernt")
        embed.add_field(name="User", value=f"<@{row['user_id']}> (`{row['user_id']}`)", inline=False)
        embed.add_field(name="Moderator", value=f"<@{row['moderator_id']}> (`{row['moderator_id']}`)", inline=False)
        embed.add_field(name="Grund", value=row["reason"][:1024], inline=False)
        embed.set_footer(text=f"Erstellt: {row['created_at']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="warn-add", description="Fügt eine Verwarnung hinzu und erstellt einen Case")
    @app_commands.describe(user="User", grund="Grund")
    @app_commands.default_permissions(moderate_members=True)
    async def warn_add(self, interaction: discord.Interaction, user: discord.Member, grund: str):
        if user.id == interaction.user.id:
            return await interaction.response.send_message("❌ Du kannst dich nicht selbst verwarnen.", ephemeral=True)
        if user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Administratoren können damit nicht verwarnt werden.", ephemeral=True)
        cid = self._case(interaction.guild_id, user.id, interaction.user.id, "WARN", grund)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO user_warns (user_id,guild_id,grund,von,case_id) VALUES (?,?,?,?,?)",
            (str(user.id), str(interaction.guild_id), grund[:1000], str(interaction.user), cid),
        )
        conn.commit()
        conn.close()
        await interaction.response.send_message(f"⚠️ {user.mention} wurde verwarnt. **Case #{cid:04d}**", ephemeral=True)
        await self._log_case(interaction.guild, cid, user, interaction.user, "WARN", grund)

    @app_commands.command(name="cases", description="Zeigt aktuelle Moderationsstatistiken")
    @app_commands.default_permissions(moderate_members=True)
    async def cases(self, interaction: discord.Interaction):
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT action, COUNT(*) AS count FROM mod_cases WHERE guild_id=? AND active=1 GROUP BY action ORDER BY count DESC", (str(interaction.guild_id),))
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM mod_cases WHERE guild_id=? AND active=1", (str(interaction.guild_id),))
        total = cur.fetchone()[0]
        conn.close()
        desc = "\n".join(f"**{r['action']}**: {r['count']}" for r in rows) or "Noch keine aktiven Cases."
        embed = discord.Embed(title="📊 Moderationsübersicht", description=desc, color=discord.Color.blurple())
        embed.add_field(name="Aktive Cases", value=str(total))
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationSuite(bot))
