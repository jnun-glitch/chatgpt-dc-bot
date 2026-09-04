"""Verifizierung: verify, verified, verify-link, verify-unlink, verify-check."""
import time
from datetime import datetime, timedelta
import discord
from discord import app_commands
from discord.ext import commands
from core.config import VERIFY_CHANNEL_ID, VERIFIED_ROLE_NAME
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

        try:
            conn = get_db()
            cursor = conn.cursor()

            cursor.execute('SELECT * FROM verify_codes WHERE code = ?', (clean_code,))
            row = cursor.fetchone()

            if not row:
                conn.close()
                increment_rate_limit(user_id)
                log_verification(user_id, clean_code, False, 'Code not found')
                embed = discord.Embed(title='Verifizierung fehlgeschlagen', description='Code nicht gefunden. Überprüfe den Code auf der Website.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
                return

            if row['used']:
                conn.close()
                increment_rate_limit(user_id)
                log_verification(user_id, clean_code, False, 'Already used')
                embed = discord.Embed(title='Verifizierung fehlgeschlagen', description='Dieser Code wurde bereits benutzt.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
                return

            if datetime.fromisoformat(row['expires_at']) < datetime.now():
                conn.close()
                increment_rate_limit(user_id)
                log_verification(user_id, clean_code, False, 'Expired')
                embed = discord.Embed(title='Verifizierung fehlgeschlagen', description='Dieser Code ist abgelaufen. Bitte generiere einen neuen Code auf der Website.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
                return

            cursor.execute('UPDATE verify_codes SET used = TRUE WHERE code = ?', (clean_code,))

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

            reset_rate_limit(user_id)
            log_verification(user_id, clean_code, True, f'Website user: {website_username}')

            guild = interaction.guild
            role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)

            if role is None:
                embed = discord.Embed(title='Fehler', description='Verified-Rolle nicht gefunden. Bitte admin informieren.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
                return

            try:
                await interaction.user.add_roles(role)
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
            except discord.Forbidden:
                embed = discord.Embed(title='Fehler', description='Keine Berechtigung für Rollenzuweisung.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)
            except Exception as e:
                logger.error(f'Role assignment failed: {e}')
                embed = discord.Embed(title='Fehler', description='Ein Fehler ist aufgetreten.', color=discord.Color.red())
                await interaction.edit_original_response(embed=embed)

        except Exception as e:
            logger.error(f'Verify error: {e}')
            embed = discord.Embed(title='Fehler', description=f'Ein Fehler ist aufgetreten: {str(e)[:200]}', color=discord.Color.red())
            await interaction.edit_original_response(embed=embed)

    @app_commands.command(name='verified', description='Zeige alle verifizierten Discord-User')
    async def cmd_verified(self, interaction: discord.Interaction):
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
                await interaction.response.send_message(embed=embed)
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
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f'Verified list error: {e}')
            embed = discord.Embed(title='Fehler', description=str(e)[:200], color=discord.Color.red())
            await interaction.response.send_message(embed=embed)

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
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f'Verify-link error: {e}')
            embed = discord.Embed(title='Fehler', description=str(e)[:200], color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='verify-unlink', description='Löse die Verknüpfung mit deinem Website-Account')
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
            role = discord.utils.get(guild.roles, name=VERIFIED_ROLE_NAME)
            if role:
                try:
                    await interaction.user.remove_roles(role)
                except Exception:
                    pass

            embed = discord.Embed(
                title='Verknüpfung gelöst',
                description=f'Die Verknüpfung mit **{website_username}** wurde gelöst.',
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f'Unlink error: {e}')
            embed = discord.Embed(title='Fehler', description=str(e)[:200], color=discord.Color.red())
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name='verify-check', description='Prüfe ob ein User verifiziert ist')
    @app_commands.describe(user='Discord-User zum Prüfen')
    async def cmd_verify_check(self, interaction: discord.Interaction, user: discord.Member = None):
        target = user or interaction.user
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
            await interaction.response.send_message(embed=embed)

        except Exception as e:
            logger.error(f'Check error: {e}')
            embed = discord.Embed(title='Fehler', description=str(e)[:200], color=discord.Color.red())
            await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(VerifyCog(bot))
