"""Private Voice Channels: !vcpanel erstellt ein Panel mit VC-Erstell-Button."""
import asyncio

import discord
from discord.ext import commands
from core.logging import logger

_PREFIX = 'PV-'
_EMPTY_DELETE_AFTER = 30


class PrivateVCPanelView(discord.ui.View):
    """Persistentes Panel: Button erstellt einen temporären privaten VC."""

    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label='➕ VC erstellen', style=discord.ButtonStyle.primary, custom_id='pv_panel_create')
    async def create_vc(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        if not guild:
            return
        member = interaction.user
        category = interaction.channel.category if getattr(interaction.channel, 'category', None) else None
        name = f'{_PREFIX}{member.display_name[:28]}'
        try:
            channel = await guild.create_voice_channel(
                name,
                category=category,
                reason=f'Private VC von {member}'
            )
        except Exception as e:
            logger.error(f'Private VC Erstellung fehlgeschlagen: {e}')
            await interaction.response.send_message('⚠️ VC konnte nicht erstellt werden.', ephemeral=True)
            return
        self.bot._temp_vcs.add(channel.id)
        try:
            await member.move_to(channel)
        except Exception:
            pass
        view = PrivateVCOwnerView(channel, self.bot)
        embed = discord.Embed(
            title='🔊 Dein privater Voice-Channel',
            description=f'{channel.mention}\n\nSteuere deinen VC über die Buttons:',
            color=discord.Color.blurple()
        )
        try:
            await member.send(embed=embed, view=view)
        except Exception:
            pass
        await interaction.response.send_message(f'✅ VC erstellt: {channel.mention}', ephemeral=True)


class VCLimitModal(discord.ui.Modal, title='Benutzerlimit setzen'):
    limit = discord.ui.TextInput(label='Maximale User', placeholder='0 = unbegrenzt', min_length=1, max_length=3)

    def __init__(self, channel, on_submit_cb):
        super().__init__()
        self._channel = channel
        self._on_submit_cb = on_submit_cb

    async def on_submit(self, interaction: discord.Interaction):
        value = self.limit.value.strip()
        try:
            limit = max(0, int(value))
        except ValueError:
            await interaction.response.send_message('⚠️ Bitte eine Zahl eingeben.', ephemeral=True)
            return
        try:
            await self._channel.edit(user_limit=limit if limit else None)
            await interaction.response.send_message(
                f'✅ Benutzerlimit gesetzt: {limit if limit else "unbegrenzt"}', ephemeral=True)
        except Exception:
            await interaction.response.send_message('⚠️ Limit konnte nicht gesetzt werden.', ephemeral=True)


class PrivateVCOwnerView(discord.ui.View):
    """DM-Controls für den VC-Besitzer: Lock/Unlock, Limit, Löschen."""

    def __init__(self, channel, bot):
        super().__init__(timeout=None)
        self.channel = channel
        self.bot = bot

    @discord.ui.button(label='🔒 Lock', style=discord.ButtonStyle.secondary, custom_id='pv_owner_lock')
    async def lock(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.channel.set_permissions(self.channel.guild.default_role, connect=False)
            await interaction.response.send_message('🔒 VC gesperrt.', ephemeral=True)
        except Exception:
            await interaction.response.send_message('⚠️ Lock fehlgeschlagen.', ephemeral=True)

    @discord.ui.button(label='🔓 Unlock', style=discord.ButtonStyle.secondary, custom_id='pv_owner_unlock')
    async def unlock(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.channel.set_permissions(self.channel.guild.default_role, connect=None)
            await interaction.response.send_message('🔓 VC entsperrt.', ephemeral=True)
        except Exception:
            await interaction.response.send_message('⚠️ Unlock fehlgeschlagen.', ephemeral=True)

    @discord.ui.button(label='👥 Limit', style=discord.ButtonStyle.secondary, custom_id='pv_owner_limit')
    async def limit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VCLimitModal(self.channel, None))

    @discord.ui.button(label='🗑️ Löschen', style=discord.ButtonStyle.danger, custom_id='pv_owner_delete')
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await self.channel.delete(reason='Private VC gelöscht')
            self.bot._temp_vcs.discard(self.channel.id)
            await interaction.response.send_message('✅ VC gelöscht.', ephemeral=True)
        except Exception:
            await interaction.response.send_message('⚠️ Löschen fehlgeschlagen.', ephemeral=True)


class PrivateVC(commands.Cog):
    """Private Voice Channels mit Panel, Owner-Controls und Auto-Delete."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        if not hasattr(bot, '_temp_vcs'):
            bot._temp_vcs = set()

    @commands.command(name='vcpanel', help='Erstellt ein Panel zum Erstellen privater VCs (Admin)')
    @commands.has_permissions(administrator=True)
    async def cmd_vcpanel(self, ctx: commands.Context):
        embed = discord.Embed(
            title='🔊 Private Voice Channels',
            description='Klicke auf den Button, um deinen eigenen temporären Voice-Channel zu erstellen.\n'
                        'Du erhältst per DM die Steuerung (Lock, Limit, Löschen).\n'
                        'Leere VCs werden automatisch gelöscht.',
            color=discord.Color.blurple()
        )
        view = PrivateVCPanelView(self.bot)
        await ctx.send(embed=embed, view=view)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel and before.channel.id in self.bot._temp_vcs and len(before.channel.members) == 0:
            channel = before.channel
            self.bot._temp_vcs.discard(channel.id)

            async def delayed_delete():
                await asyncio.sleep(_EMPTY_DELETE_AFTER)
                try:
                    fresh = self.bot.get_channel(channel.id)
                    if fresh and len(fresh.members) == 0:
                        await fresh.delete(reason='Private VC leer')
                except Exception:
                    pass

            self.bot.loop.create_task(delayed_delete())

    @cmd_vcpanel.error
    async def vcpanel_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send('⚠️ Dafür brauchst du Administrator-Rechte.')


async def setup(bot):
    await bot.add_cog(PrivateVC(bot))
