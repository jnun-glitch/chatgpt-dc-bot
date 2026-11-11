"""Verifizierung: verify, verified, verify-link, verify-unlink, verify-check."""
import time
import sqlite3
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands
from core.config import DB_PATH, OWNER_ID, VERIFY_CHANNEL_ID, VERIFIED_ROLE_NAME
from core.db import get_db, check_rate_limit, increment_rate_limit, reset_rate_limit, log_verification
from core.utils import _is_allowed_channel
from core.logging import logger


class VerifyCog(commands.Cog):
    """Website-Verifizierung und Account-Verknüpfung."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='verify', description='Verifiziere dich mit deinem Code von der Website')
    @app_commands.describe(code='Dein Verifizierungscode')
    async def cmd_verify(self, interaction: discord.Interaction, code: str):
        embed = discord.Embed(
            title=f'Hallo {interaction.user.display_name}!',
            description='Ich überprüfe deinen Code...',
            color=discord.Color.blurple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

        if not _is_allowed_channel(interaction):
            ch = self.bot.get_channel(VERIFY_CHANNEL_ID)
            ch_name = ch.mention if ch else f'#{VERIFY_CHANNEL_ID}'
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title=f'Hallo {interaction.user.display_name}!',
                    description=f'❌ Dieser Befehl ist nur in {ch_name} erlaubt.',
                    color=discord.Color.red()
                )
            )
            return

        guild = interaction.guild
        if guild is None:
            await interaction.edit_original_response(
                embed=discord.Embed(title='Fehler', description='Verifizierung ist nur auf einem Server möglich.', color=discord.Color.red())
            )
            return
        role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)
        bot_member = guild.me
        if role is None:
            await interaction.edit_original_response(
                embed=discord.Embed(title='Fehler', description='Verified-Rolle nicht gefunden. Bitte admin informieren.', color=discord.Color.red())
            )
            return
        if (
            bot_member is None
            or not bot_member.guild_permissions.manage_roles
            or role >= bot_member.top_role
        ):
            await interaction.edit_original_response(
                embed=discord.Embed(title='Fehler', description='Der Bot kann die Verified-Rolle nicht verwalten. Bitte Rollenrechte und Hierarchie prüfen.', color=discord.Color.red())
            )
            return

        user_id = str(interaction.user.id)

        blocked, remaining = check_rate_limit(user_id)
        if blocked:
            minutes = remaining // 60
            seconds = remaining % 60
            embed = discord.Embed(
                title='Rate Limit',
                description=f'Zu viele Versuche. Warte **{minutes}m {seconds}s**.',
                color=discord.Color.orange()
            )
            await interaction.edit_original_response(embed=embed)
            return

        clean_code = code.strip().upper()

        if len(clean_code) != 6:
            increment_rate_limit(user_id)
            embed = discord.Embed(title='Ungültiger Code', description='Der Code muss **6 Zeichen** lang sein.', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)
            return

        conn = None
        try:
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute('BEGIN IMMEDIATE')
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM verify_codes WHERE code = ?', (clean_code,))
            row = cursor.fetchone()

            if not row:
                conn.rollback()
                conn.close()
                increment_rate_limit(user_id)
                log_verification(user_id, clean_code, False, 'Code not found')
                embed = discord.Embed(title='Verifizierung fehlgeschlagen', description='Code nicht gefunden. Überprüfe den Code auf der Website.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
                return

            if row['used']:
                conn.rollback()
                conn.close()
                increment_rate_limit(user_id)
                log_verification(user_id, clean_code, False, 'Already used')
                embed = discord.Embed(title='Verifizierung fehlgeschlagen', description='Dieser Code wurde bereits benutzt.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
                return

            expires_at = datetime.fromisoformat(row['expires_at'])
            now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.now()
            if expires_at < now:
                conn.rollback()
                conn.close()
                increment_rate_limit(user_id)
                log_verification(user_id, clean_code, False, 'Expired')
                embed = discord.Embed(title='Verifizierung fehlgeschlagen', description='Dieser Code ist abgelaufen. Bitte generiere einen neuen Code auf der Website.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
                return

            cursor.execute(
                'SELECT 1 FROM discord_links WHERE discord_user_id = ? AND confirmed = TRUE LIMIT 1',
                (user_id,),
            )
            if cursor.fetchone():
                conn.rollback()
                conn.close()
                embed = discord.Embed(title='Bereits verknüpft', description='Dein Discord-Konto ist bereits mit einem Website-Account verknüpft.', color=discord.Color.orange())
                await interaction.edit_original_response(embed=embed)
                return

            cursor.execute('UPDATE verify_codes SET used = TRUE WHERE code = ? AND used = FALSE', (clean_code,))
            if cursor.rowcount != 1:
                conn.rollback()
                conn.close()
                increment_rate_limit(user_id)
                embed = discord.Embed(title='Verifizierung fehlgeschlagen', description='Dieser Code wurde bereits benutzt.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
                return

            website_username = row['username']
            cursor.execute(
                'DELETE FROM discord_links WHERE website_username = ? AND confirmed = FALSE',
                (website_username,)
            )
            expires_at = datetime.now() + timedelta(hours=24)
            cursor.execute(
                'INSERT INTO discord_links (code, website_username, discord_username, discord_user_id, confirmed, expires_at) VALUES (?, ?, ?, ?, TRUE, ?)',
                ('LINKED_' + clean_code, website_username, str(interaction.user), user_id, expires_at)
            )

            conn.commit()
            conn.close()

            try:
                await interaction.user.add_roles(role)
            except discord.Forbidden:
                self._rollback_verification(clean_code, user_id)
                log_verification(user_id, clean_code, False, 'Role assignment forbidden')
                embed = discord.Embed(title='Fehler', description='Keine Berechtigung für Rollenzuweisung.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
                return
            except Exception as e:
                self._rollback_verification(clean_code, user_id)
                log_verification(user_id, clean_code, False, f'Role assignment failed: {str(e)[:120]}')
                logger.error(f'Role assignment failed: {e}')
                embed = discord.Embed(title='Fehler', description='Ein Fehler ist aufgetreten.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
                return

            reset_rate_limit(user_id)
            log_verification(user_id, clean_code, True, f'Website user: {website_username}')
            embed = discord.Embed(
                title=f'Hallo {interaction.user.display_name}! Verifizierung erfolgreich',
                description=(
                    f'Willkommen! Du hast jetzt die **{VERIFIED_ROLE_NAME}**-Rolle!\n\n'
                    f'**Website-Account:** {website_username}\n'
                    f'**Discord:** {interaction.user}\n\n'
                    f'Nutze jetzt `/ask` um Fragen zu stellen oder `/generate` um ein Spiel zu erstellen!'
                ),
                color=discord.Color.green()
            )
            await interaction.edit_original_response(embed=embed)

        except Exception as e:
            if conn is not None:
                try:
                    conn.rollback()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
            logger.error(f'Verify error: {e}')
            embed = discord.Embed(title='Fehler', description=f'Ein Fehler ist aufgetreten: {str(e)[:200]}', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)

    def _rollback_verification(self, code: str, user_id: str) -> None:
        """Restore a code if the role assignment failed after the DB commit."""
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                'DELETE FROM discord_links WHERE code = ? AND discord_user_id = ?',
                ('LINKED_' + code, user_id),
            )
            conn.execute('UPDATE verify_codes SET used = FALSE WHERE code = ?', (code,))
            conn.commit()
        finally:
            conn.close()

    @app_commands.command(name='verified', description='Zeige alle verifizierten Discord-User')
    async def cmd_verified(self, interaction: discord.Interaction):
        if not OWNER_ID or interaction.user.id != OWNER_ID:
            return await interaction.response.send_message('⛔ Nur für den Bot-Owner.', ephemeral=True)
        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT discord_user_id, discord_username, website_username, created_at FROM discord_links WHERE confirmed = TRUE ORDER BY created_at DESC'
            )
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                embed = discord.Embed(
                    title='Verifizierte User',
                    description='Noch keine verifizierten User gefunden.',
                    color=discord.Color.greyple()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            lines = []
            for i, row in enumerate(rows, 1):
                created = row['created_at'][:10] if row['created_at'] else '?'
                lines.append(f'**{i}.** {row["discord_username"]} ({row["discord_user_id"]}) → {row["website_username"]} | {created}')

            description = '\n'.join(lines)
            if len(description) > 4000:
                description = description[:4000] + '\n...'

            embed = discord.Embed(
                title=f'Verifizierte User ({len(rows)})',
                description=description,
                color=discord.Color.green()
            )
            embed.set_footer(text=f'Database: discord_verify.db')
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Verified list error: {e}')
            embed = discord.Embed(title='Fehler', description=str(e)[:200], color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='verify-link', description='Verknüpfe deinen Website-Account mit Discord')
    @app_commands.describe(username='Dein Scratch-Benutzername auf der Website')
    async def cmd_verify_link(self, interaction: discord.Interaction, username: str):
        user_id = str(interaction.user.id)
        clean_username = username.strip()

        if len(clean_username) < 2 or len(clean_username) > 30:
            embed = discord.Embed(title='Ungültiger Name', description='Der Benutzername muss 2-30 Zeichen lang sein.', color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        try:
            conn = get_db()
            cursor = conn.cursor()

            cursor.execute(
                'SELECT * FROM discord_links WHERE discord_user_id = ? AND confirmed = TRUE',
                (user_id,)
            )
            existing = cursor.fetchone()
            if existing:
                conn.close()
                embed = discord.Embed(
                    title='Bereits verknüpft',
                    description=f'Du bist bereits mit **{existing["website_username"]}** verknüpft.',
                    color=discord.Color.orange()
                )
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            cursor.execute(
                'DELETE FROM discord_links WHERE website_username = ? AND confirmed = FALSE',
                (clean_username,)
            )
            expires_at = datetime.now() + timedelta(hours=24)
            cursor.execute(
                'INSERT INTO discord_links (code, website_username, discord_username, discord_user_id, confirmed, expires_at) VALUES (?, ?, ?, ?, FALSE, ?)',
                (f'LINK_{user_id}_{int(time.time())}', clean_username, str(interaction.user), user_id, expires_at)
            )
            conn.commit()
            conn.close()

            embed = discord.Embed(
                title='Verknuepfung angefordert!',
                description=(
                    f'Die Verknuepfung mit **{clean_username}** wurde angefordert.\n\n'
                    f'**Discord:** {interaction.user}\n'
                    f'**Website:** {clean_username}\n\n'
                    f'Gehe auf die Website und bestaetige die Verknuepfung mit deinem Code.'
                ),
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Verify-link error: {e}')
            embed = discord.Embed(title='Fehler', description=str(e)[:200], color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='verify-unlink', description='Löse die Verknüpfung mit deinem Website-Account')
    @app_commands.guild_only()
    async def cmd_verify_unlink(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id)

        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM discord_links WHERE discord_user_id = ? AND confirmed = TRUE',
                (user_id,)
            )
            row = cursor.fetchone()
            if not row:
                conn.close()
                embed = discord.Embed(title='Nicht verknüpft', description='Du bist mit keinem Website-Account verknüpft.', color=discord.Color.orange())
                await interaction.response.send_message(embed=embed, ephemeral=True)
                return

            website_username = row['website_username']
            cursor.execute('DELETE FROM discord_links WHERE discord_user_id = ? AND confirmed = TRUE', (user_id,))
            conn.commit()
            conn.close()

            guild = interaction.guild
            role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME) if guild else None
            if role and isinstance(interaction.user, discord.Member):
                try:
                    await interaction.user.remove_roles(role)
                except Exception:
                    pass

            embed = discord.Embed(
                title='Verknüpfung gelöst',
                description=f'Die Verknüpfung mit **{website_username}** wurde gelöst.',
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Unlink error: {e}')
            embed = discord.Embed(title='Fehler', description=str(e)[:200], color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='verify-check', description='Prüfe ob ein User verifiziert ist')
    @app_commands.describe(user='Discord-User zum Prüfen')
    async def cmd_verify_check(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
        if target.id != interaction.user.id:
            member = interaction.user
            if not (
                (OWNER_ID and member.id == OWNER_ID)
                or (isinstance(member, discord.Member) and (
                    member.guild_permissions.administrator
                    or member.guild_permissions.manage_guild
                ))
            ):
                return await interaction.response.send_message(
                    '⛔ Du darfst nur deinen eigenen Verifizierungsstatus prüfen.', ephemeral=True
                )
        user_id = str(target.id)

        try:
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT * FROM discord_links WHERE discord_user_id = ? AND confirmed = TRUE',
                (user_id,)
            )
            row = cursor.fetchone()
            conn.close()

            if row:
                embed = discord.Embed(
                    title=f'{target.display_name} ist verifiziert',
                    description=(
                        f'**Website-Account:** {row["website_username"]}\n'
                        f'**Seit:** {row["created_at"][:10] if row["created_at"] else "?"}'
                    ),
                    color=discord.Color.green()
                )
            else:
                embed = discord.Embed(
                    title=f'{target.display_name} ist nicht verifiziert',
                    description='Dieser User hat noch keine Website-Verknüpfung.',
                    color=discord.Color.greyple()
                )
            await interaction.response.send_message(embed=embed, ephemeral=True)

        except Exception as e:
            logger.error(f'Check error: {e}')
            embed = discord.Embed(title='Fehler', description=str(e)[:200], color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VerifyCog(bot))
