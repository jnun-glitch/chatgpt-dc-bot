"""AFK-System: !afk Grund, auto-entfernt bei Nachricht, Erwähnung-Info."""
import discord
from discord.ext import commands
from datetime import datetime


class AFK(commands.Cog):
    """AFK-System mit auto-Entfernung (Text Commands)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='afk', help='Markiere dich als AFK')
    async def cmd_afk(self, ctx: commands.Context, *, grund: str = 'AFK'):
        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO afk_users (guild_id, user_id, reason, afk_since)
            VALUES (?, ?, ?, ?)
        ''', (str(ctx.guild.id), str(ctx.author.id), grund, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()

        try:
            nick = f'[AFK] {ctx.author.display_name[:25]}'
            if len(nick) > 32:
                nick = nick[:32]
            await ctx.author.edit(nick=nick)
        except Exception:
            pass

        embed = discord.Embed(
            title='💤 Du bist jetzt AFK',
            description=f'Grund: **{grund}**\nIch entferne den AFK-Status automatisch, wenn du schreibst.',
            color=discord.Color.greyple()
        )
        await ctx.send(embed=embed, delete_after=10)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute('SELECT reason FROM afk_users WHERE guild_id = ? AND user_id = ?',
                       (str(message.guild.id), str(message.author.id)))
        row = cursor.fetchone()

        if row:
            cursor.execute('DELETE FROM afk_users WHERE guild_id = ? AND user_id = ?',
                           (str(message.guild.id), str(message.author.id)))
            conn.commit()

            try:
                nick = message.author.display_name
                if nick.startswith('[AFK] '):
                    nick = nick[6:]
                if len(nick) > 32:
                    nick = nick[:32]
                await message.author.edit(nick=nick)
            except Exception:
                pass

            embed = discord.Embed(
                title='✅ Willkommen zurück!',
                description='Dein AFK-Status wurde entfernt.',
                color=discord.Color.green()
            )
            try:
                await message.channel.send(embed=embed, delete_after=5)
            except Exception:
                pass

        for user in message.mentions:
            if user.bot or user.id == message.author.id:
                continue

            cursor.execute('SELECT reason, afk_since FROM afk_users WHERE guild_id = ? AND user_id = ?',
                           (str(message.guild.id), str(user.id)))
            afk_row = cursor.fetchone()
            conn.close()

            if afk_row:
                reason = afk_row[0] or 'AFK'
                since = afk_row[1]
                try:
                    since_dt = datetime.fromisoformat(since)
                    ago = (datetime.utcnow() - since_dt)
                    minutes = int(ago.total_seconds() / 60)
                    if minutes < 60:
                        time_str = f'vor {minutes} Minuten'
                    elif minutes < 1440:
                        time_str = f'vor {minutes // 60} Stunden'
                    else:
                        time_str = f'vor {minutes // 1440} Tagen'
                except Exception:
                    time_str = 'seit unbekannt'

                embed = discord.Embed(
                    title=f'💤 {user.display_name} ist AFK',
                    description=f'Grund: **{reason}**\nSeit: {time_str}',
                    color=discord.Color.greyple()
                )
                try:
                    await message.channel.send(embed=embed, delete_after=8)
                except Exception:
                    pass
                return

        conn.close()


async def setup(bot: commands.Bot):
    await bot.add_cog(AFK(bot))
