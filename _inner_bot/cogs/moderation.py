"""Moderation: ban, kick, timeout, warn, Channel-Control, Rollen, Purge, Permissions."""
import re
from datetime import timedelta
import sqlite3
import discord
from discord import app_commands
from discord.ext import commands
from core.config import DB_PATH
from core.db import get_db
from core.channelnames import find_channel
from core.db import format_msg


def _no_perm(interaction):
    return format_msg(interaction.guild_id, 'no_perm_msg')
from core.logging import logger

_PERM_PRESETS = {
    'nur_lesen': {'view_channel': True, 'send_messages': False, 'read_messages': True},
    'nur_schreiben': {'view_channel': True, 'read_messages': True, 'send_messages': True, 'attach_files': False, 'embed_links': False},
    'lesen_schreiben': {'view_channel': True, 'read_messages': True, 'send_messages': True, 'attach_files': True, 'embed_links': True},
    'moderator': {'view_channel': True, 'read_messages': True, 'send_messages': True, 'manage_messages': True, 'attach_files': True, 'embed_links': True, 'mention_everyone': True},
    'kein_zugriff': {'view_channel': False},
    'alle_rechte': {'manage_channels': True, 'manage_messages': True, 'send_messages': True, 'view_channel': True, 'read_messages': True},
    'sprachchat': {'view_channel': True, 'connect': True, 'speak': True},
    'sprachchat_nur_zuhören': {'view_channel': True, 'connect': True, 'speak': False},
}


class ModerationCog(commands.Cog):
    """Moderations- und Verwaltungs-Commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _admin_log(self, guild, title: str, description: str, color=discord.Color.blue()):
        """Loggt eine Mod-Aktion in #admin-log (falls vorhanden)."""
        try:
            log_ch = find_channel(guild, 'admin-log')
            if log_ch:
                embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
                await log_ch.send(embed=embed)
        except Exception:
            pass

    @staticmethod
    def _is_special_message(message) -> bool:
        """Erkennt geschützte Bot-Nachrichten (Prefill-Marker im Embed-Footer)."""
        for emb in getattr(message, 'embeds', None) or []:
            if emb.footer and 'Prefill:' in (emb.footer.text or ''):
                return True
        return False

    @app_commands.command(name='ban', description='Bannt einen User vom Server')
    @app_commands.describe(user='User zum Bannen', grund='Grund für den Ban')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_ban(self, interaction: discord.Interaction, user: discord.Member, grund: str = 'Kein Grund angegeben'):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        if user.guild_permissions.administrator:
            await interaction.response.send_message('Kann keine Admins bannen!', ephemeral=True)
            return
        try:
            await user.ban(reason=grund, delete_message_days=1)
            embed = discord.Embed(title='User gebannt', description=f'{user.mention} wurde gebannt.\n**Grund:** {grund}', color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            await self._admin_log(interaction.guild, '🚫 Ban', f'{interaction.user.mention} bannte {user.mention}\n**Grund:** {grund}', discord.Color.red())
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='unban', description='Entbannt einen User')
    @app_commands.describe(user_id='User ID zum Entbannen')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_unban(self, interaction: discord.Interaction, user_id: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            uid = int(user_id)
            user = await interaction.guild.fetch_ban(discord.Object(uid))
            await interaction.guild.unban(user.user)
            embed = discord.Embed(title='User entbannt', description=f'{user.user.mention} wurde entbannt.', color=discord.Color.green())
            await interaction.response.send_message(embed=embed)
            await self._admin_log(interaction.guild, '✅ Unban', f'{interaction.user.mention} entbannte {user.user.mention}', discord.Color.green())
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='kick', description='Kickt einen User vom Server')
    @app_commands.describe(user='User zum Kicken', grund='Grund für den Kick')
    @app_commands.default_permissions(kick_members=True)
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_kick(self, interaction: discord.Interaction, user: discord.Member, grund: str = 'Kein Grund angegeben'):
        if not interaction.user.guild_permissions.kick_members:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        if user.guild_permissions.administrator:
            await interaction.response.send_message('Kann keine Admins kicken!', ephemeral=True)
            return
        try:
            await user.kick(reason=grund)
            embed = discord.Embed(title='User gekickt', description=f'{user.mention} wurde gekickt.\n**Grund:** {grund}', color=discord.Color.orange())
            await interaction.response.send_message(embed=embed)
            await self._admin_log(interaction.guild, '👢 Kick', f'{interaction.user.mention} kickte {user.mention}\n**Grund:** {grund}', discord.Color.orange())
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='timeout', description='Muted einen User temporär')
    @app_commands.describe(user='User zum Muten', minuten='Dauer in Minuten (Standard: 5)', grund='Grund')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_timeout(self, interaction: discord.Interaction, user: discord.Member, minuten: int = 5, grund: str = 'Kein Grund'):
        # Only OWNER can mute
        from core.config import OWNER_ID
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message(
                '⛔ Nur der Owner kann Leute muten.', ephemeral=True)
        # Check mute_immune.txt
        try:
            from core.muteimmune import is_mute_immune
            if is_mute_immune(user.id):
                return await interaction.response.send_message(
                    f'🛡️ {user.mention} ist vor Auto-Mute geschützt (`mute_immune.txt`).', ephemeral=True)
        except Exception:
            pass
        try:
            until = (discord.utils.utcnow() + timedelta(minutes=minuten)).isoformat()
            await user.edit(communication_disabled_until=until, reason=grund)
            embed = discord.Embed(title='User gemutet', description=f'{user.mention} für **{minuten} Minuten** gemutet.\n**Grund:** {grund}', color=discord.Color.orange())
            await interaction.response.send_message(embed=embed)
            await self._admin_log(interaction.guild, '⏱️ Timeout', f'{interaction.user.mention} mutete {user.mention} für **{minuten} Min.**\n**Grund:** {grund}', discord.Color.orange())
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='untimeout', description='Hebt den Mute eines Users auf')
    @app_commands.describe(user='User zum Entmuten')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_untimeout(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            await user.edit(communication_disabled_until=None, reason='Timeout aufgehoben')
            embed = discord.Embed(title='Timeout aufgehoben', description=f'{user.mention} kann wieder schreiben.', color=discord.Color.green())
            await interaction.response.send_message(embed=embed)
            await self._admin_log(interaction.guild, '✅ Timeout aufgehoben', f'{interaction.user.mention} entmutete {user.mention}', discord.Color.green())
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='warn', description='Verwarnt einen User')
    @app_commands.describe(user='User zum Verwarnen', grund='Grund für die Verwarnung')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_warn(self, interaction: discord.Interaction, user: discord.Member, grund: str = 'Kein Grund'):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        uid = str(user.id)
        gid = str(interaction.guild_id)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO user_warns (user_id, guild_id, grund, von) VALUES (?, ?, ?, ?)',
                       (uid, gid, grund, str(interaction.user)))
        conn.commit()
        cursor.execute('SELECT COUNT(*) FROM user_warns WHERE user_id = ? AND guild_id = ?', (uid, gid))
        warn_count = cursor.fetchone()[0]
        conn.close()

        timeout_at, kick_at, timeout_minutes = self._get_warn_thresholds(interaction.guild_id)

        action_note = ''
        if warn_count >= kick_at:
            action_note = await self._auto_warn_kick(interaction, user, warn_count, kick_at)
        elif warn_count >= timeout_at:
            action_note = await self._auto_warn_timeout(interaction, user, warn_count, timeout_at, timeout_minutes)

        embed = discord.Embed(
            title='User verwarnet',
            description=f'{user.mention} wurde verwarnet. **({warn_count}/{kick_at} Warns bis Kick)**\n**Grund:** {grund}',
            color=discord.Color.orange(),
        )
        if action_note:
            embed.add_field(name='Automatische Konsequenz', value=action_note, inline=False)
        await interaction.response.send_message(embed=embed)
        await self._admin_log(interaction.guild, '⚠️ Verwarnung', f'{interaction.user.mention} verwarnte {user.mention} ({warn_count}/{kick_at})\n**Grund:** {grund}', discord.Color.orange())

    @staticmethod
    def _get_warn_thresholds(guild_id) -> tuple:
        """Konfigurierbare Warn-Schwellen aus guild_settings (Defaults: 3 = Timeout, 5 = Kick)."""
        from core.db import get_guild_config
        cfg = get_guild_config(guild_id)
        try:
            timeout_at = max(1, int(cfg.get('warn_timeout_at') or 3))
        except (ValueError, TypeError):
            timeout_at = 3
        try:
            kick_at = max(timeout_at + 1, int(cfg.get('warn_kick_at') or 5))
        except (ValueError, TypeError):
            kick_at = 5
        try:
            timeout_minutes = max(1, int(cfg.get('warn_timeout_minutes') or 60))
        except (ValueError, TypeError):
            timeout_minutes = 60
        return timeout_at, kick_at, timeout_minutes

    async def _auto_warn_timeout(self, interaction, user, warn_count, timeout_at, timeout_minutes) -> str:
        """Wendet beim Erreichen der Timeout-Schwelle automatisch einen Timeout an."""
        if user.guild_permissions.administrator:
            return f'Timeout-Schwelle ({timeout_at}) erreicht, aber {user.mention} ist Admin – kein Auto-Timeout.'
        try:
            from core.muteimmune import is_mute_immune
            if is_mute_immune(user.id):
                return f'Timeout-Schwelle ({timeout_at}) erreicht, aber {user.mention} ist in `mute_immune.txt` – kein Auto-Timeout.'
        except Exception:
            pass
        try:
            until = (discord.utils.utcnow() + timedelta(minutes=timeout_minutes)).isoformat()
            await user.edit(communication_disabled_until=until, reason=f'Auto-Timeout nach {warn_count} Warns')
            await self._admin_log(interaction.guild, '⏱️ Auto-Timeout', f'{user.mention} nach **{warn_count} Warns** automatisch für **{timeout_minutes} Min.** gemutet.', discord.Color.orange())
            return f'{user.mention} wurde automatisch für **{timeout_minutes} Minuten** gemutet ({warn_count} Warns).'
        except Exception as e:
            return f'Timeout-Schwelle ({timeout_at}) erreicht, aber automatisches Muten fehlgeschlagen: {e}'

    async def _auto_warn_kick(self, interaction, user, warn_count, kick_at) -> str:
        """Wendet beim Erreichen der Kick-Schwelle automatisch einen Kick an."""
        if user.guild_permissions.administrator:
            return f'Kick-Schwelle ({kick_at}) erreicht, aber {user.mention} ist Admin – kein Auto-Kick.'
        try:
            await user.kick(reason=f'Auto-Kick nach {warn_count} Warns')
            await self._admin_log(interaction.guild, '👢 Auto-Kick', f'{user.mention} nach **{warn_count} Warns** automatisch gekickt.', discord.Color.orange())
            return f'{user.mention} wurde automatisch **gekickt** ({warn_count} Warns).'
        except Exception as e:
            return f'Kick-Schwelle ({kick_at}) erreicht, aber automatischer Kick fehlgeschlagen: {e}'

    @app_commands.command(name='warnings', description='Zeigt die Verwarnungen eines Users')
    @app_commands.describe(user='User whose warnings to show')
    async def cmd_warnings(self, interaction: discord.Interaction, user: discord.Member):
        uid = str(user.id)
        gid = str(interaction.guild_id)
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT grund, von, zeit FROM user_warns WHERE user_id = ? AND guild_id = ? ORDER BY zeit', (uid, gid))
        warns = cursor.fetchall()
        conn.close()
        if not warns:
            await interaction.response.send_message(embed=discord.Embed(description=f'{user.mention} hat keine Verwarnungen.', color=discord.Color.green()))
            return
        desc = '\n'.join([f'**{i+1}.** {w["grund"]} (von {w["von"]})' for i, w in enumerate(warns)])
        embed = discord.Embed(title=f'Verwarnungen von {user.display_name}', description=desc, color=discord.Color.orange())
        _, kick_at, _ = self._get_warn_thresholds(interaction.guild_id)
        embed.set_footer(text=f'{len(warns)}/{kick_at} Warns')
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='warn-clear', description='Entfernt alle Verwarnungen eines Users')
    @app_commands.describe(user='User')
    @app_commands.default_permissions(administrator=True)
    async def cmd_warn_clear(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            with sqlite3.connect(str(DB_PATH)) as conn:
                conn.execute('DELETE FROM user_warns WHERE user_id = ? AND guild_id = ?', (str(user.id), str(interaction.guild_id)))
            embed = discord.Embed(title='Verwarnungen entfernt', description=f'Alle Verwarnungen von {user.mention} wurden entfernt.', color=discord.Color.green())
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    # ── Channel Control ────────────────────────────────────────────────────────
    @app_commands.command(name='slowmode', description='Setzt Slowmode in einem Channel')
    @app_commands.describe(
        zeit='Dauer z.B. "30s", "5m", "1h" oder "0" zum Ausschalten',
        channel='Channel (Standard: aktueller)',
    )
    @app_commands.default_permissions(administrator=True)
    async def cmd_slowmode(self, interaction: discord.Interaction, zeit: str, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        raw = zeit.lower().strip()
        if raw in ('aus', 'off', 'stop', 'none', '0s'):
            seconds = 0
        else:
            match = re.match(r'^(\d+)\s*(s|sek|sekunden|m|min|minuten|h|std|stunden)?$', raw)
            if not match:
                embed = discord.Embed(title='Ungültiges Format', description='Nutze z.B. `30s`, `5m`, `1h` oder `aus` zum Ausschalten.', color=discord.Color.red())
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return
            amount = int(match.group(1))
            unit = (match.group(2) or 's').lower()
            if unit in ('m', 'min', 'minuten'):
                seconds = amount * 60
            elif unit in ('h', 'std', 'stunden'):
                seconds = amount * 3600
            else:
                seconds = amount
        if seconds > 21600:
            await interaction.response.send_message('Maximal 6 Stunden (21600s) erlaubt.', ephemeral=True)
            return
        target = channel or interaction.channel
        try:
            await target.edit(slowmode_delay=seconds)
            msg = f'Slowmode auf **{seconds} Sekunden** gesetzt.' if seconds > 0 else 'Slowmode deaktiviert.'
            embed = discord.Embed(title='Slowmode', description=f'{target.mention}: {msg}', color=discord.Color.blue())
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='lock', description='Schließt den aktuellen Channel')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_lock(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=False)
            embed = discord.Embed(title='Channel gesperrt', description=f'{interaction.channel.mention} wurde gesperrt.', color=discord.Color.red())
            await interaction.response.send_message(embed=embed)
            await self._admin_log(interaction.guild, '🔒 Channel gesperrt', f'{interaction.user.mention} sperrte {interaction.channel.mention}', discord.Color.red())
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='unlock', description='Öffnet den aktuellen Channel')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_unlock(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            await interaction.channel.set_permissions(interaction.guild.default_role, send_messages=True)
            embed = discord.Embed(title='Channel geöffnet', description=f'{interaction.channel.mention} wurde geöffnet.', color=discord.Color.green())
            await interaction.response.send_message(embed=embed)
            await self._admin_log(interaction.guild, '🔓 Channel geöffnet', f'{interaction.user.mention} öffnete {interaction.channel.mention}', discord.Color.green())
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    # ── User Management ────────────────────────────────────────────────────────
    @app_commands.command(name='role', description='Rolle hinzufügen oder entfernen')
    @app_commands.describe(aktion='add oder remove', user='User', rolle='Rollenname')
    @app_commands.choices(aktion=[
        app_commands.Choice(name='Hinzufügen', value='add'),
        app_commands.Choice(name='Entfernen', value='remove'),
    ])
    @app_commands.default_permissions(administrator=True)
    async def cmd_role(self, interaction: discord.Interaction, aktion: app_commands.Choice[str], user: discord.Member, rolle: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        role = discord.utils.get(interaction.guild.roles, name=rolle)
        if not role:
            await interaction.response.send_message(f'Rolle **{rolle}** nicht gefunden!', ephemeral=True)
            return
        try:
            if aktion.value == 'add':
                await user.add_roles(role)
                embed = discord.Embed(title='Rolle hinzugefügt', description=f'{role.name} wurde zu {user.mention} hinzugefügt.', color=discord.Color.green())
            else:
                await user.remove_roles(role)
                embed = discord.Embed(title='Rolle entfernt', description=f'{role.name} wurde von {user.mention} entfernt.', color=discord.Color.orange())
            await interaction.response.send_message(embed=embed)
            await self._admin_log(interaction.guild, '🎭 Rolle geändert', f'{interaction.user.mention} → **{aktion.name}** {role.mention} für {user.mention}', discord.Color.blue())
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='role-create', description='Erstellt eine neue Rolle')
    @app_commands.describe(name='Name der Rolle', farbe='Hex-Farbe (z.B. #00FF00)', getrennt='Zeigt Rolle getrennt von anderen an?')
    @app_commands.default_permissions(administrator=True)
    async def cmd_role_create(self, interaction: discord.Interaction, name: str, farbe: str = '#99AAB5', getrennt: bool = True):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            color = int(farbe.lstrip('#'), 16)
        except ValueError:
            color = 0x99AAB5
        try:
            role = await interaction.guild.create_role(name=name, color=color, hoist=getrennt)
            embed = discord.Embed(title='Rolle erstellt', description=f'Rolle **{role.mention}** mit Farbe `{farbe}` angelegt.', color=color)
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='role-delete', description='Löscht eine Rolle')
    @app_commands.describe(rolle='Rolle zum Löschen')
    @app_commands.default_permissions(administrator=True)
    async def cmd_role_delete(self, interaction: discord.Interaction, rolle: discord.Role):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        if rolle >= interaction.guild.me.top_role:
            await interaction.response.send_message('Ich kann diese Rolle nicht löschen (zu hoch in der Hierarchie).', ephemeral=True)
            return
        try:
            await rolle.delete()
            embed = discord.Embed(title='Rolle gelöscht', description=f'Rolle **{rolle.name}** wurde gelöscht.', color=discord.Color.blue())
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='role-color', description='Ändert die Farbe einer Rolle')
    @app_commands.describe(rolle='Rolle', farbe='Neue Hex-Farbe (z.B. #FF0000)')
    @app_commands.default_permissions(administrator=True)
    async def cmd_role_color(self, interaction: discord.Interaction, rolle: discord.Role, farbe: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            color = int(farbe.lstrip('#'), 16)
        except ValueError:
            await interaction.response.send_message('Ungültige Farbe! Nutze z.B. `#FF0000`.', ephemeral=True)
            return
        try:
            await rolle.edit(color=color)
            embed = discord.Embed(title='Rollenfarbe geändert', description=f'{rolle.mention} hat jetzt die Farbe `{farbe}`.', color=color)
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='role-list', description='Zeigt alle Rollen des Servers')
    async def cmd_role_list(self, interaction: discord.Interaction):
        roles = sorted(interaction.guild.roles, key=lambda r: r.position, reverse=True)
        lines = [f'{r.mention} – {len(r.members)} Mitglieder' for r in roles if not r.is_default() and not r.is_bot_managed()]
        embed = discord.Embed(title='📋 Server-Rollen', description='\n'.join(lines) if lines else 'Keine Rollen', color=discord.Color.blue())
        await interaction.response.send_message(embed=embed)

    # ── Berechtigungs-Voreinstellungen ─────────────────────────────────────────
    @app_commands.command(name='permissions', description='Setzt Berechtigungs-Voreinstellungen für Rolle/User auf einem Channel')
    @app_commands.describe(
        ziel='Rolle oder User (@Rolle oder @User)',
        voreinstellung='Welche Voreinstellung anwenden?',
        channel='Channel (Standard: aktueller)',
        hinzufuegen='Berechtigung hinzufügen statt ersetzen? (True=add, False=ersetzen)',
    )
    @app_commands.choices(voreinstellung=[
        app_commands.Choice(name='📖 Nur Lesen', value='nur_lesen'),
        app_commands.Choice(name='✍️ Nur Schreiben', value='nur_schreiben'),
        app_commands.Choice(name='✅ Lesen + Schreiben', value='lesen_schreiben'),
        app_commands.Choice(name='🛡️ Moderator', value='moderator'),
        app_commands.Choice(name='🚫 Kein Zugriff', value='kein_zugriff'),
        app_commands.Choice(name='👑 Alle Rechte', value='alle_rechte'),
        app_commands.Choice(name='🎙️ Sprachchat', value='sprachchat'),
        app_commands.Choice(name='🔇 Sprachchat nur zuhören', value='sprachchat_nur_zuhören'),
    ])
    @app_commands.default_permissions(administrator=True)
    async def cmd_permissions(self, interaction: discord.Interaction, ziel: str, voreinstellung: app_commands.Choice[str], channel: discord.TextChannel = None, hinzufuegen: bool = False):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        preset = _PERM_PRESETS.get(voreinstellung.value)
        if not preset:
            await interaction.response.send_message('Unbekannte Voreinstellung!', ephemeral=True)
            return
        target_channel = channel or interaction.channel

        target = None
        if ziel.startswith('<@&'):
            target = interaction.guild.get_role(int(ziel[3:-1]))
        elif ziel.startswith('<@'):
            target = await interaction.guild.fetch_member(int(ziel[2:-1]))
        else:
            target = discord.utils.get(interaction.guild.roles, name=ziel)

        if target is None:
            embed = discord.Embed(title='Nicht gefunden', description=f'**{ziel}** konnte nicht als Rolle oder User gefunden werden.', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        try:
            overwrite = target_channel.overwrites_for(target)
            for perm_name, value in preset.items():
                setattr(overwrite, perm_name, value)
            await target_channel.set_permissions(target, overwrite=overwrite)
            embed = discord.Embed(
                title='Berechtigungen gesetzt',
                description=f'**{target.display_name if isinstance(target, discord.Member) else target.name}** → `{target_channel.mention}`\nVoreinstellung: **{voreinstellung.name}**',
                color=discord.Color.green(),
            )
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='permissions-reset', description='Entfernt alle Berechtigungs-Overrides für Rolle/User auf einem Channel')
    @app_commands.describe(ziel='Rolle oder User (@Rolle oder @User)', channel='Channel (Standard: aktueller)')
    @app_commands.default_permissions(administrator=True)
    async def cmd_permissions_reset(self, interaction: discord.Interaction, ziel: str, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        target_channel = channel or interaction.channel
        target = None
        if ziel.startswith('<@&'):
            target = interaction.guild.get_role(int(ziel[3:-1]))
        elif ziel.startswith('<@'):
            target = await interaction.guild.fetch_member(int(ziel[2:-1]))
        else:
            target = discord.utils.get(interaction.guild.roles, name=ziel)
        if target is None:
            await interaction.response.send_message(f'**{ziel}** nicht gefunden.', ephemeral=True)
            return
        try:
            await target_channel.set_permissions(target, overwrite=None)
            embed = discord.Embed(title='Berechtigungen zurückgesetzt', description=f'Overrides für **{getattr(target, "display_name", target.name)}** entfernt.', color=discord.Color.blue())
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='nick', description='Ändert den Nicknamen eines Users')
    @app_commands.describe(user='User', nickname='Neuer Nickname')
    @app_commands.default_permissions(administrator=True)
    async def cmd_nick(self, interaction: discord.Interaction, user: discord.Member, nickname: str):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            old_nick = user.display_name
            await user.edit(nick=nickname)
            embed = discord.Embed(title='Nickname geändert', description=f'{old_nick} → **{nickname}**', color=discord.Color.blue())
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='nick-reset', description='Setzt den Nicknamen eines Users zurück')
    @app_commands.describe(user='User')
    @app_commands.default_permissions(administrator=True)
    async def cmd_nick_reset(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            await user.edit(nick=None)
            embed = discord.Embed(title='Nickname zurückgesetzt', description=f'{user.mention} hat seinen Standardnamen zurück.', color=discord.Color.blue())
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='purge', description='Löscht Nachrichten im Channel')
    @app_commands.describe(anzahl='Anzahl der Nachrichten (1-100)')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.cooldown(2, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_purge(self, interaction: discord.Interaction, anzahl: int = 10):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        if anzahl < 1 or anzahl > 100:
            await interaction.response.send_message('Anzahl muss zwischen 1 und 100 liegen!', ephemeral=True)
            return
        try:
            deleted = await interaction.channel.purge(
                limit=anzahl,
                check=lambda m: not self._is_special_message(m) and not m.pinned
            )
            embed = discord.Embed(title='Nachrichten gelöscht', description=f'**{len(deleted)}** Nachrichten wurden gelöscht (speziell geschützte übersprungen).', color=discord.Color.blue())
            await interaction.response.send_message(embed=embed, delete_after=5)
            await self._admin_log(interaction.guild, '🧹 Purge', f'{interaction.user.mention} löschte **{len(deleted)}** Nachrichten in {interaction.channel.mention}', discord.Color.blue())
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='purge-user', description='Löscht Nachrichten eines bestimmten Users im Channel')
    @app_commands.describe(user='User dessen Nachrichten gelöscht werden', anzahl='Maximale Anzahl (1-100)')
    @app_commands.default_permissions(administrator=True)
    @app_commands.checks.cooldown(2, 10.0, key=lambda i: (i.guild_id, i.user.id))
    async def cmd_purge_user(self, interaction: discord.Interaction, user: discord.Member, anzahl: int = 20):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        if anzahl < 1 or anzahl > 100:
            await interaction.response.send_message('Anzahl muss zwischen 1 und 100 liegen!', ephemeral=True)
            return
        try:
            def check(m):
                return m.author.id == user.id and not self._is_special_message(m) and not m.pinned
            deleted = await interaction.channel.purge(limit=anzahl, check=check)
            embed = discord.Embed(title='Nachrichten gelöscht', description=f'**{len(deleted)}** Nachrichten von {user.mention} gelöscht (speziell geschützte übersprungen).', color=discord.Color.blue())
            await interaction.response.send_message(embed=embed, delete_after=5)
            await self._admin_log(interaction.guild, '🧹 Purge (User)', f'{interaction.user.mention} löschte **{len(deleted)}** Nachrichten von {user.mention} in {interaction.channel.mention}', discord.Color.blue())
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='deafen', description='Deaft einen User im Voice (Server-stumm)')
    @app_commands.describe(user='User zum Deafen')
    @app_commands.default_permissions(administrator=True)
    async def cmd_deafen(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            await user.edit(deafen=True)
            embed = discord.Embed(title='User gedeaft', description=f'{user.mention} ist jetzt server-stumm.', color=discord.Color.orange())
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='undeafen', description='Macht einen User wieder hörbar')
    @app_commands.describe(user='User zum Undeafen')
    @app_commands.default_permissions(administrator=True)
    async def cmd_undeafen(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            await user.edit(deafen=False)
            embed = discord.Embed(title='User undeaft', description=f'{user.mention} ist wieder hörbar.', color=discord.Color.green())
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='voice-kick', description='Entfernt einen User aus dem Voice-Channel')
    @app_commands.describe(user='User zum Entfernen')
    @app_commands.default_permissions(administrator=True)
    async def cmd_voice_kick(self, interaction: discord.Interaction, user: discord.Member):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        if not user.voice or not user.voice.channel:
            await interaction.response.send_message(f'{user.mention} ist in keinem Voice-Channel.', ephemeral=True)
            return
        try:
            await user.move_to(None)
            embed = discord.Embed(title='Voice-Kick', description=f'{user.mention} wurde aus dem Voice-Channel entfernt.', color=discord.Color.orange())
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    # ── Content Commands ────────────────────────────────────────────────────────
    @app_commands.command(name='announce', description='Sendet eine Announcement')
    @app_commands.describe(titel='Titel', nachricht='Nachricht', channel='Channel für die Announcement')
    @app_commands.default_permissions(administrator=True)
    async def cmd_announce(self, interaction: discord.Interaction, titel: str, nachricht: str, channel: discord.TextChannel = None):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        target = channel or interaction.channel
        embed = discord.Embed(title=titel, description=nachricht, color=discord.Color.gold())
        embed.set_footer(text=f'Announcement von {interaction.user.display_name}')
        try:
            await target.send(embed=embed)
            await interaction.response.send_message(f'Announcement in {target.mention} gesendet!', ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)

    @app_commands.command(name='embed', description='Erstellt ein eigenes Embed')
    @app_commands.describe(titel='Titel', beschreibung='Beschreibung', farbe='Hex-Farbe (z.B. #FF0000)', footer='Footer Text')
    @app_commands.default_permissions(administrator=True)
    async def cmd_embed(self, interaction: discord.Interaction, titel: str, beschreibung: str, farbe: str = '#3498DB', footer: str = ''):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            color = int(farbe.lstrip('#'), 16)
        except ValueError:
            color = 0x3498DB
        embed = discord.Embed(title=titel, description=beschreibung, color=color)
        if footer:
            embed.set_footer(text=footer)
        await interaction.response.send_message(embed=embed)

    # ── Info Commands ───────────────────────────────────────────────────────────
    @app_commands.command(name='serverinfo', description='Zeigt Informationen über den Server')
    async def cmd_serverinfo(self, interaction: discord.Interaction):
        guild = interaction.guild
        embed = discord.Embed(title=guild.name, color=discord.Color.blue())
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name='Owner', value=guild.owner.mention if guild.owner else 'Unbekannt', inline=True)
        embed.add_field(name='Erstellt', value=f'<t:{int(guild.created_at.timestamp())}:R>', inline=True)
        embed.add_field(name='Member', value=guild.member_count, inline=True)
        embed.add_field(name='Text Channels', value=len(guild.text_channels), inline=True)
        embed.add_field(name='Voice Channels', value=len(guild.voice_channels), inline=True)
        embed.add_field(name='Rollen', value=len(guild.roles), inline=True)
        embed.add_field(name='Boosts', value=guild.premium_subscription_count or 0, inline=True)
        embed.add_field(name='Boost Level', value=guild.premium_tier, inline=True)
        if guild.description:
            embed.add_field(name='Beschreibung', value=guild.description, inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name='auditlog', description='Zeigt die letzten 10 Aktionen im Server')
    @app_commands.default_permissions(administrator=True)
    async def cmd_auditlog(self, interaction: discord.Interaction):
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(_no_perm(interaction), ephemeral=True)
            return
        try:
            entries = []
            async for entry in interaction.guild.audit_logs(limit=10):
                action_map = {
                    discord.AuditLogAction.ban: '🚫 Ban',
                    discord.AuditLogAction.unban: '✅ Unban',
                    discord.AuditLogAction.kick: '👢 Kick',
                    discord.AuditLogAction.member_role_update: '🎭 Rollen-Update',
                    discord.AuditLogAction.member_update: '📝 Member-Update',
                    discord.AuditLogAction.channel_create: '📢 Channel erstellt',
                    discord.AuditLogAction.channel_delete: '🗑️ Channel gelöscht',
                    discord.AuditLogAction.role_create: '🎨 Rolle erstellt',
                    discord.AuditLogAction.role_delete: '🗑️ Rolle gelöscht',
                    discord.AuditLogAction.message_delete: '🗑️ Nachricht gelöscht',
                }
                action_str = action_map.get(entry.action, str(entry.action))
                entries.append(f'**{action_str}** von {entry.user.mention} → {entry.target}')
            embed = discord.Embed(title='Audit Log', description='\n'.join(entries) if entries else 'Keine Einträge', color=discord.Color.blue())
            await interaction.response.send_message(embed=embed)
        except Exception as e:
            await interaction.response.send_message(f'Fehler: {e}', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ModerationCog(bot))
