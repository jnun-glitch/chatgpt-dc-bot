"""Konfigurierbare Level-Rollen: !setlevelrole, !remlevelrole, !levelroles."""
import discord
from discord.ext import commands
from core.db import get_level_roles, set_level_role, remove_level_role
from core.config import LEVEL_ROLES


class LevelRoles(commands.Cog):
    """Server-spezifische Level-Rollen statt fest verdrahteter Defaults."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='setlevelrole', help='Setzt Level-Rolle: !setlevelrole <level> <@role> (Admin)')
    @commands.has_permissions(administrator=True)
    async def cmd_set_level_role(self, ctx: commands.Context, level: int, role: discord.Role):
        if level < 1:
            return await ctx.send('⚠️ Level muss mindestens 1 sein.')
        if not set_level_role(ctx.guild.id, level, role.id):
            return await ctx.send('⚠️ Speichern fehlgeschlagen.')
        embed = discord.Embed(
            title='✅ Level-Rolle gesetzt',
            description=f'**Level {level}** → {role.mention}',
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name='remlevelrole', help='Entfernt Level-Rolle: !remlevelrole <level> (Admin)')
    @commands.has_permissions(administrator=True)
    async def cmd_remove_level_role(self, ctx: commands.Context, level: int):
        roles = get_level_roles(ctx.guild.id)
        if level not in roles:
            return await ctx.send('⚠️ Für dieses Level ist keine Rolle konfiguriert.')
        if not remove_level_role(ctx.guild.id, level):
            return await ctx.send('⚠️ Entfernen fehlgeschlagen.')
        await ctx.send(f'✅ Level-Rolle für **Level {level}** entfernt.')

    @commands.command(name='levelroles', help='Zeigt die konfigurierten Level-Rollen')
    async def cmd_list_level_roles(self, ctx: commands.Context):
        roles = get_level_roles(ctx.guild.id)
        if roles:
            lines = []
            for level, role_id in sorted(roles.items()):
                role = ctx.guild.get_role(int(role_id))
                lines.append(f'**Level {level}** → {role.mention if role else f"`{role_id}` (nicht gefunden)"}')
            embed = discord.Embed(
                title='📊 Level-Rollen',
                description='\n'.join(lines),
                color=discord.Color.blurple()
            )
            embed.set_footer(text='Mit !setlevelrole <level> <@role> anpassen')
        else:
            defaults = '\n'.join(f'**Level {lvl}** → `{name}`' for lvl, name in sorted(LEVEL_ROLES.items()))
            embed = discord.Embed(
                title='📊 Level-Rollen',
                description=f'Keine eigene Konfiguration – es gelten die Defaults:\n{defaults}',
                color=discord.Color.blurple()
            )
            embed.set_footer(text='Mit !setlevelrole <level> <@role> eine eigene Konfiguration anlegen')
        await ctx.send(embed=embed)

    @cmd_set_level_role.error
    async def set_role_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send('⚠️ Dafür brauchst du Administrator-Rechte.')
        elif isinstance(error, commands.BadArgument):
            await ctx.send('⚠️ Nutze: `!setlevelrole <level> <@rolle>`')


async def setup(bot):
    await bot.add_cog(LevelRoles(bot))
