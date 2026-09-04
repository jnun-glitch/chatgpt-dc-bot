"""Counting Game: !counting setup, auto-detect numbers, Stats."""
import discord
from discord.ext import commands


class Counting(commands.Cog):
    """Counting Game (Text Commands)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.group(name='counting', invoke_without_command=True)
    async def counting(self, ctx: commands.Context):
        from core.db import get_db, get_guild_config
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM counting WHERE guild_id = ?', (str(ctx.guild.id),))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return await ctx.send('❌ Counting-Game nicht eingerichtet. Nutze `!counting setup #channel`')

        enabled = get_guild_config(ctx.guild.id).get('counting_enabled', '1') != '0'
        embed = discord.Embed(
            title='🔢 Counting-Statistiken',
            color=discord.Color.blue()
        )
        embed.add_field(name='Status', value='🟢 Aktiv' if enabled else '🔴 Pausiert', inline=True)
        embed.add_field(name='Aktuelle Zahl', value=str(row['current_number']), inline=True)
        embed.add_field(name='Rekord', value=str(row['highest_number']), inline=True)
        channel = ctx.guild.get_channel(int(row['channel_id']))
        embed.add_field(name='Channel', value=channel.mention if channel else 'Unbekannt', inline=True)
        embed.set_footer(text='!counting toggle · !counting reset')
        await ctx.send(embed=embed)

    @counting.command(name='setup')
    @commands.has_permissions(administrator=True)
    async def counting_setup(self, ctx: commands.Context, channel: discord.TextChannel):
        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO counting (guild_id, channel_id, current_number, highest_number, last_user_id)
            VALUES (?, ?, 0, 0, NULL)
        ''', (str(ctx.guild.id), str(channel.id)))
        conn.commit()
        conn.close()

        embed = discord.Embed(
            title='🔢 Counting-Game aktiviert',
            description=f'Channel: {channel.mention}\n\n**Regeln:**\n• Zähle hoch: 1, 2, 3, 4, ...\n• Nur eine Zahl pro User\n• Gleiche Zahl zweimal = Reset',
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @counting.command(name='toggle')
    @commands.has_permissions(administrator=True)
    async def counting_toggle(self, ctx: commands.Context):
        from core.db import get_guild_config, set_guild_config, get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT 1 FROM counting WHERE guild_id = ?', (str(ctx.guild.id),))
        exists = cursor.fetchone()
        conn.close()
        if not exists:
            return await ctx.send('❌ Counting-Game nicht eingerichtet. Nutze `!counting setup #channel`')

        enabled = get_guild_config(ctx.guild.id).get('counting_enabled', '1') != '0'
        new_state = '0' if enabled else '1'
        set_guild_config(ctx.guild.id, 'counting_enabled', new_state)
        embed = discord.Embed(
            title='🔢 Counting-Game ' + ('pausiert' if new_state == '0' else 'fortgesetzt'),
            description='Der Bot zählt im Counting-Channel ' + ('**nicht** mehr mit.' if new_state == '0' else 'wieder mit.'),
            color=discord.Color.orange() if new_state == '0' else discord.Color.green()
        )
        await ctx.send(embed=embed)

    @counting.command(name='reset')
    @commands.has_permissions(administrator=True)
    async def counting_reset(self, ctx: commands.Context):
        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE counting SET current_number = 0, highest_number = 0, last_user_id = NULL WHERE guild_id = ?',
                       (str(ctx.guild.id),))
        conn.commit()
        conn.close()
        await ctx.send('✅ Counting-Stand wurde zurückgesetzt (0 / Rekord 0).')

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        from core.db import get_db, get_guild_config
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM counting WHERE guild_id = ?', (str(message.guild.id),))
        row = cursor.fetchone()

        if not row or str(message.channel.id) != row['channel_id']:
            conn.close()
            return

        if get_guild_config(message.guild.id).get('counting_enabled', '1') == '0':
            conn.close()
            return

        content = message.content.strip()
        if not content.isdigit():
            conn.close()
            return

        number = int(content)
        current = row['current_number']
        expected = current + 1
        last_user = row['last_user_id']

        if number != expected:
            cursor.execute('UPDATE counting SET current_number = 0, last_user_id = NULL WHERE guild_id = ?',
                           (str(message.guild.id),))
            conn.commit()
            conn.close()
            await message.add_reaction('❌')
            try:
                await message.channel.send(
                    f'❌ **{message.author.mention}** hat **{number}** geschrieben. Erwartet: **{expected}**.\nZurückgesetzt auf 0!',
                    delete_after=5)
            except Exception:
                pass
            return

        if str(message.author.id) == last_user:
            cursor.execute('UPDATE counting SET current_number = 0, last_user_id = NULL WHERE guild_id = ?',
                           (str(message.guild.id),))
            conn.commit()
            conn.close()
            await message.add_reaction('❌')
            try:
                await message.channel.send(
                    f'❌ **{message.author.mention}** hat zweimal in Folge gezählt. Zurückgesetzt!',
                    delete_after=5)
            except Exception:
                pass
            return

        new_highest = max(row['highest_number'], number)
        cursor.execute('UPDATE counting SET current_number = ?, highest_number = ?, last_user_id = ? WHERE guild_id = ?',
                       (number, new_highest, str(message.author.id), str(message.guild.id)))
        conn.commit()
        conn.close()
        await message.add_reaction('✅')

        if number in [10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000]:
            try:
                await message.channel.send(f'🎉 **Meilenstein {number}** erreicht von {message.author.mention}!', delete_after=10)
            except Exception:
                pass

        if number > row['highest_number']:
            try:
                await message.channel.send(f'🏆 **Neuer Rekord: {number}** von {message.author.mention}!', delete_after=10)
            except Exception:
                pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Counting(bot))
