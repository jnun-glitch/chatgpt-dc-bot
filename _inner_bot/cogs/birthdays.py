"""Birthday Tracker: !birthday, Auto-Gratulation (Text Commands)."""
import discord
from discord.ext import commands, tasks
from datetime import datetime


class Birthdays(commands.Cog):
    """Birthday Tracker (Text Commands)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.birthday_check.start()

    def cog_unload(self):
        self.birthday_check.cancel()

    @tasks.loop(hours=1)
    async def birthday_check(self):
        today = datetime.utcnow()
        if today.hour != 9:
            return

        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM birthdays')
        rows = cursor.fetchall()
        conn.close()

        for row in rows:
            try:
                bday = datetime.strptime(row['birthday'], '%Y-%m-%d')
                if bday.month == today.month and bday.day == today.day:
                    if row['last_wished'] == today.year:
                        continue

                    guild = self.bot.get_guild(int(row['guild_id']))
                    if not guild:
                        continue
                    member = guild.get_member(int(row['user_id']))
                    if not member:
                        continue

                    channel = None
                    for ch in guild.text_channels:
                        if 'general' in ch.name.lower() or 'chat' in ch.name.lower():
                            channel = ch
                            break
                    if not channel:
                        channel = guild.system_channel or guild.text_channels[0]

                    embed = discord.Embed(
                        title='🎂 Alles Gute zum Geburtstag!',
                        description=f'Heute hat **{member.display_name}** Geburtstag!\n\n🎉 **Happy Birthday!** 🎂🎈🎁',
                        color=discord.Color.gold()
                    )
                    embed.set_thumbnail(url=member.display_avatar.url)

                    try:
                        await channel.send(content=member.mention, embed=embed)
                        conn2 = get_db()
                        c2 = conn2.cursor()
                        c2.execute('UPDATE birthdays SET last_wished = ? WHERE guild_id = ? AND user_id = ?',
                                   (today.year, row['guild_id'], row['user_id']))
                        conn2.commit()
                        conn2.close()
                    except Exception:
                        pass
            except Exception:
                continue

    @birthday_check.before_loop
    async def before_birthday_check(self):
        await self.bot.wait_until_ready()

    @commands.command(name='birthday', help='Speichere deinen Geburtstag: !birthday TT.MM.JJJJ')
    async def cmd_birthday(self, ctx: commands.Context, datum: str):
        try:
            bday = datetime.strptime(datum, '%d.%m.%Y')
        except ValueError:
            return await ctx.send('❌ Format: `!birthday TT.MM.JJJJ` (z.B. `!birthday 15.03.1995`)')

        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('INSERT OR REPLACE INTO birthdays (guild_id, user_id, birthday, last_wished) VALUES (?, ?, ?, 0)',
                       (str(ctx.guild.id), str(ctx.author.id), bday.strftime('%Y-%m-%d')))
        conn.commit()
        conn.close()
        await ctx.send(f'🎂 Geburtstag gespeichert: **{bday.day}.{bday.month}.{bday.year}**!')

    @commands.command(name='birthday-remove', help='Entferne deinen Geburtstag')
    async def cmd_birthday_remove(self, ctx: commands.Context):
        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM birthdays WHERE guild_id = ? AND user_id = ?',
                       (str(ctx.guild.id), str(ctx.author.id)))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        await ctx.send('✅ Geburtstag entfernt.' if deleted else '❌ Kein Geburtstag gespeichert.')

    @commands.command(name='birthdays', help='Zeigt alle Geburtstage')
    async def cmd_birthdays(self, ctx: commands.Context):
        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM birthdays WHERE guild_id = ? ORDER BY birthday',
                       (str(ctx.guild.id),))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return await ctx.send('Keine Geburtstage gespeichert.')

        today = datetime.utcnow()
        upcoming = []
        for row in rows:
            try:
                bday = datetime.strptime(row['birthday'], '%Y-%m-%d')
                next_bday = bday.replace(year=today.year)
                if next_bday < today:
                    next_bday = bday.replace(year=today.year + 1)
                days_until = (next_bday - today).days
                member = ctx.guild.get_member(int(row['user_id']))
                name = member.display_name if member else f'User {row["user_id"]}'
                upcoming.append((days_until, name, bday))
            except Exception:
                continue

        upcoming.sort(key=lambda x: x[0])
        lines = []
        for days, name, bday in upcoming[:15]:
            if days == 0:
                text = '🎉 **Heute!**'
            elif days == 1:
                text = '📅 **Morgen!**'
            else:
                text = f'in {days} Tagen'
            lines.append(f'**{name}** — {bday.day}.{bday.month} — {text}')

        embed = discord.Embed(title='🎂 Geburtstage', description='\n'.join(lines), color=discord.Color.pink())
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Birthdays(bot))
