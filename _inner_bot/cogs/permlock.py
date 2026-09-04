"""Permission Lock: Entfernt 'Mitglieder moderaten' von allen Rollen außer Bot."""
import discord
from discord.ext import commands


class PermissionLock(commands.Cog):
    """Locks down mute permissions - only bot owner can mute."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='lock-mute', help='Entfernt "Mitglieder moderaten" von allen Rollen')
    @commands.is_owner()
    async def cmd_lock_mute(self, ctx: commands.Context):
        removed = 0
        for role in ctx.guild.roles:
            if role.permissions.moderate_members:
                try:
                    await role.edit(permissions=discord.Permissions(
                        **role.permissions.dict(),
                        moderate_members=False
                    ), reason='Lock-Mute: Nur Bot darf muten')
                    removed += 1
                except Exception as e:
                    await ctx.send(f'⚠️ Fehler bei {role.name}: {e}')

        embed = discord.Embed(
            title='🔒 Mute-Berechtigungen gesperrt',
            description=f'**{removed}** Rollen hatten "Mitglieder moderaten" und wurden gesperrt.\n'
                       f'Nur noch der Bot (über Owner-ID geprüft) kann Leute muten.',
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name='unlock-mute', help='Gibt "Mitglieder moderaten" an Admin-Rollen zurück')
    @commands.is_owner()
    async def cmd_unlock_mute(self, ctx: commands.Context):
        for role in ctx.guild.roles:
            if role.permissions.administrator:
                try:
                    await role.edit(permissions=discord.Permissions(
                        **role.permissions.dict(),
                        moderate_members=True
                    ), reason='Unlock-Mute: Admin-Rollen bekommen Berechtigung zurück')
                except Exception:
                    pass

        await ctx.send('✅ Admin-Rollen haben "Mitglieder moderaten" zurück.')


async def setup(bot: commands.Bot):
    await bot.add_cog(PermissionLock(bot))
