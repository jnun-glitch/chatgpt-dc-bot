"""Starboard: ⭐-Reaktionen pushen Highlights in einen Starboard-Kanal."""
import discord
from discord.ext import commands
from core.db import (
    get_guild_config, set_guild_config,
    get_starboard_post, set_starboard_post, remove_starboard_post,
)
from core.logging import logger

_STAR = '\N{WHITE MEDIUM STAR}'


def _get_threshold(guild_id: int) -> int:
    cfg = get_guild_config(guild_id)
    try:
        return max(1, int(cfg.get('starboard_threshold') or 5))
    except Exception:
        return 5


def _get_channel_id(guild_id: int):
    cfg = get_guild_config(guild_id)
    cid = cfg.get('starboard_channel_id')
    return int(cid) if cid else None


async def _build_star_embed(message: discord.Message, count: int) -> discord.Embed:
    content = message.content or ''
    embed = discord.Embed(
        title=f'{_STAR} {count}',
        description=content[:2000],
        color=discord.Color.gold(),
        timestamp=message.created_at,
    )
    embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
    if message.attachments:
        img = message.attachments[0]
        if img.content_type and img.content_type.startswith('image/'):
            embed.set_image(url=img.url)
    embed.add_field(name='Quelle', value=f'[Springen]({message.jump_url}) in {message.channel.mention}')
    return embed


async def _recount(message: discord.Message, starboard_channel, threshold: int):
    count = sum(
        r.count for r in message.reactions
        if str(r.emoji) == _STAR
    )
    if count < threshold:
        post = get_starboard_post(message.id)
        if post:
            try:
                old = starboard_channel.get_partial_message(int(post['starboard_message_id']))
                await old.delete()
            except Exception:
                pass
            remove_starboard_post(message.id)
        return

    embed = await _build_star_embed(message, count)
    post = get_starboard_post(message.id)
    if post:
        try:
            old = starboard_channel.get_partial_message(int(post['starboard_message_id']))
            await old.edit(embed=embed)
        except Exception:
            try:
                sent = await starboard_channel.send(embed=embed)
                set_starboard_post(message.id, message.guild.id, sent.id)
            except Exception:
                pass
    else:
        try:
            sent = await starboard_channel.send(embed=embed)
            set_starboard_post(message.id, message.guild.id, sent.id)
        except Exception as e:
            logger.error(f'Starboard post fehlgeschlagen: {e}')


class Starboard(commands.Cog):
    """Starboard: Highlight-Nachrichten bei genug ⭐-Reaktionen."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.group(name='starboard', invoke_without_subcommand=True, help='Starboard-Status anzeigen')
    async def starboard(self, ctx: commands.Context):
        cid = _get_channel_id(ctx.guild.id)
        threshold = _get_threshold(ctx.guild.id)
        ch = ctx.guild.get_channel(cid) if cid else None
        if ch:
            desc = f'**Kanal:** {ch.mention}\n**Schwelle:** {threshold} {_STAR}\n\nMit `!starboard set #kanal` / `!starboard threshold <n>` anpassen.'
        else:
            desc = f'**Kanal:** nicht gesetzt\n**Schwelle:** {threshold} {_STAR}\n\nSetze mit `!starboard set #kanal` ein Starboard ein.'
        embed = discord.Embed(title='⭐ Starboard', description=desc, color=discord.Color.gold())
        await ctx.send(embed=embed)

    @starboard.command(name='set', help='Setzt den Starboard-Kanal (Admin)')
    @commands.has_permissions(administrator=True)
    async def set_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        set_guild_config(ctx.guild.id, 'starboard_channel_id', channel.id)
        await ctx.send(f'✅ Starboard-Kanal: {channel.mention}')

    @starboard.command(name='threshold', help='Setzt die ⭐-Schwelle (Admin)')
    @commands.has_permissions(administrator=True)
    async def set_threshold(self, ctx: commands.Context, count: int):
        if count < 1:
            return await ctx.send('⚠️ Schwelle muss mindestens 1 sein.')
        set_guild_config(ctx.guild.id, 'starboard_threshold', count)
        await ctx.send(f'✅ Schwelle: {count} {_STAR}')

    @starboard.command(name='remove', help='Deaktiviert das Starboard (Admin)')
    @commands.has_permissions(administrator=True)
    async def remove(self, ctx: commands.Context):
        set_guild_config(ctx.guild.id, 'starboard_channel_id', None)
        await ctx.send('✅ Starboard deaktiviert.')

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload, removed=False)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload, removed=True)

    async def _handle_reaction(self, payload, removed: bool):
        if str(payload.emoji) != _STAR:
            return
        if not payload.guild_id:
            return
        cid = _get_channel_id(payload.guild_id)
        if not cid:
            return
        if payload.channel_id == cid:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        starboard_channel = guild.get_channel(cid)
        if not starboard_channel or not isinstance(starboard_channel, discord.TextChannel):
            return
        channel = guild.get_channel(payload.channel_id)
        if not channel or not isinstance(channel, discord.TextChannel):
            return
        try:
            message = await channel.fetch_message(payload.message_id)
        except Exception:
            return
        if message.author.bot:
            return
        try:
            await _recount(message, starboard_channel, _get_threshold(payload.guild_id))
        except Exception as e:
            logger.error(f'Starboard Verarbeitung fehlgeschlagen: {e}')


async def setup(bot):
    await bot.add_cog(Starboard(bot))
