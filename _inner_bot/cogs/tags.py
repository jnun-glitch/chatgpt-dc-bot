"""Tags: Custom Commands via Text-Commands, !tag, !tag create, etc."""
import discord
from discord.ext import commands


class Tags(commands.Cog):
    """Tags / Custom Commands (Text Commands)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.group(name='tag', invoke_without_command=True, help='Rufe ein Tag auf: !tag <name>')
    async def tag(self, ctx: commands.Context, *, name: str = None):
        if not name:
            return await ctx.send('Nutze: `!tag <name>` oder `!tag list`')

        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT content, uses FROM tags WHERE guild_id = ? AND name = ?',
                       (str(ctx.guild.id), name.lower()))
        row = cursor.fetchone()

        if not row:
            return await ctx.send(f'❌ Tag `{name}` nicht gefunden.')

        cursor.execute('UPDATE tags SET uses = uses + 1 WHERE guild_id = ? AND name = ?',
                       (str(ctx.guild.id), name.lower()))
        conn.commit()
        conn.close()
        await ctx.send(row['content'])

    @tag.command(name='create', help='Erstelle ein Tag: !tag create <name> <content>')
    @commands.has_permissions(administrator=True)
    async def tag_create(self, ctx: commands.Context, name: str, *, content: str):
        if len(name) > 50:
            return await ctx.send('❌ Tag-Name max. 50 Zeichen.')
        if len(content) > 2000:
            return await ctx.send('❌ Tag-Inhalt max. 2000 Zeichen.')

        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT name FROM tags WHERE guild_id = ? AND name = ?',
                       (str(ctx.guild.id), name.lower()))
        if cursor.fetchone():
            conn.close()
            return await ctx.send(f'❌ Tag `{name}` existiert bereits.')

        cursor.execute('INSERT INTO tags (guild_id, name, content, created_by) VALUES (?, ?, ?, ?)',
                       (str(ctx.guild.id), name.lower(), content, str(ctx.author.id)))
        conn.commit()
        conn.close()
        await ctx.send(f'✅ Tag **{name}** erstellt!')

    @tag.command(name='edit', help='Bearbeite ein Tag: !tag edit <name> <neuer Inhalt>')
    async def tag_edit(self, ctx: commands.Context, name: str, *, content: str):
        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT created_by FROM tags WHERE guild_id = ? AND name = ?',
                       (str(ctx.guild.id), name.lower()))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return await ctx.send(f'❌ Tag `{name}` nicht gefunden.')

        if row['created_by'] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            conn.close()
            return await ctx.send('⛔ Nur der Ersteller oder Admins.')

        cursor.execute('UPDATE tags SET content = ? WHERE guild_id = ? AND name = ?',
                       (content, str(ctx.guild.id), name.lower()))
        conn.commit()
        conn.close()
        await ctx.send(f'✅ Tag `{name}` aktualisiert.')

    @tag.command(name='delete', help='Lösche ein Tag: !tag delete <name>')
    async def tag_delete(self, ctx: commands.Context, *, name: str):
        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT created_by FROM tags WHERE guild_id = ? AND name = ?',
                       (str(ctx.guild.id), name.lower()))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return await ctx.send(f'❌ Tag `{name}` nicht gefunden.')

        if row['created_by'] != str(ctx.author.id) and not ctx.author.guild_permissions.administrator:
            conn.close()
            return await ctx.send('⛔ Nur der Ersteller oder Admins.')

        cursor.execute('DELETE FROM tags WHERE guild_id = ? AND name = ?',
                       (str(ctx.guild.id), name.lower()))
        conn.commit()
        conn.close()
        await ctx.send(f'✅ Tag `{name}` gelöscht.')

    @tag.command(name='list', help='Zeigt alle Tags')
    async def tag_list(self, ctx: commands.Context):
        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT name, uses FROM tags WHERE guild_id = ? ORDER BY uses DESC',
                       (str(ctx.guild.id),))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return await ctx.send('Keine Tags vorhanden.')

        lines = [f'`{r["name"]}` — {r["uses"]}x benutzt' for r in rows[:30]]
        embed = discord.Embed(title='🏷️ Tags', description='\n'.join(lines), color=discord.Color.blue())
        embed.set_footer(text=f'{len(rows)} Tags | !tag <name> zum Aufrufen')
        await ctx.send(embed=embed)

    @tag.command(name='info', help='Info über ein Tag: !tag info <name>')
    async def tag_info(self, ctx: commands.Context, *, name: str):
        from core.db import get_db
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM tags WHERE guild_id = ? AND name = ?',
                       (str(ctx.guild.id), name.lower()))
        row = cursor.fetchone()
        conn.close()

        if not row:
            return await ctx.send(f'❌ Tag `{name}` nicht gefunden.')

        creator = ctx.guild.get_member(int(row['created_by']))
        creator_name = creator.display_name if creator else 'Unbekannt'
        embed = discord.Embed(title=f'🏷️ {row["name"]}', color=discord.Color.blue())
        embed.add_field(name='Erstellt von', value=creator_name, inline=True)
        embed.add_field(name='Benutzt', value=f'{row["uses"]}x', inline=True)
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Tags(bot))
