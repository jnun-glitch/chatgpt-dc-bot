"""Audit-Logging: Zeichnet ALLES auf – Nachrichten, Commands, Member, Channels, Voice."""
import discord
from discord.ext import commands, tasks
from discord import app_commands
from datetime import datetime, timezone
from core.logging import logger
from core.channelnames import styled_text_name, find_channel
from cogs.dashboard import log_audit_event

AUDIT_BASE = 'audit-log'


class AuditLogger(commands.Cog):
    """Umfassendes Audit-Logging für den gesamten Server."""

    def __init__(self, bot):
        self.bot = bot
        self._cache = {}  # message_id → (author, channel, content, timestamp)

    def _get_channel(self, guild):
        ch = find_channel(guild, AUDIT_BASE)
        if ch is None:
            ch = discord.utils.get(guild.channels, name=styled_text_name(AUDIT_BASE))
        return ch

    async def _log(self, guild, embed):
        ch = self._get_channel(guild)
        if ch is None:
            return
        try:
            await ch.send(embed=embed)
        except Exception:
            pass

    # ── Messages ────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        # Cache for edit/delete tracking
        self._cache[message.id] = (
            message.author, message.channel, message.content, message.created_at
        )
        # Limit cache size
        if len(self._cache) > 5000:
            oldest = list(self._cache.keys())[:1000]
            for k in oldest:
                del self._cache[k]

        # Log every message
        embed = discord.Embed(
            description=message.content[:4000] if message.content else '*[Kein Text]*',
            color=discord.Color.greyple(),
            timestamp=message.created_at
        )
        embed.set_author(
            name=f'{message.author.display_name} ({message.author.id})',
            icon_url=message.author.display_avatar.url
        )
        embed.add_field(name='Channel', value=message.channel.mention, inline=True)
        if message.attachments:
            files = ', '.join(a.filename for a in message.attachments[:5])
            embed.add_field(name='Dateien', value=files, inline=True)
        if message.reference:
            ref = message.reference.resolved
            if isinstance(ref, discord.Message):
                embed.add_field(name='Antwort auf', value=f'{ref.author.mention}: {ref.content[:100]}', inline=False)
        embed.set_footer(text=f'#{message.channel.name}')
        await self._log(message.guild, embed)

    # ── Message Edit ────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        if payload.data.get('author'):
            author_id = payload.data['author'].get('id')
            if author_id and int(author_id) == self.bot.user.id:
                return
        channel = self.bot.get_channel(payload.channel_id)
        if not channel or not hasattr(channel, 'guild') or not channel.guild:
            return
        guild = channel.guild

        old = self._cache.get(int(payload.message_id))
        new_content = payload.data.get('content', '')
        author_str = 'Unbekannt'
        if old:
            author, old_ch, old_content, ts = old
            author_str = f'{author.display_name} ({author.id})'
        else:
            old_content = '*[Nicht im Cache]*'
            ts = datetime.now(timezone.utc)

        embed = discord.Embed(
            title='📝 Nachricht bearbeitet',
            color=discord.Color.yellow(),
            timestamp=ts
        )
        embed.set_author(name=author_str)
        if old_content:
            embed.add_field(name='Vorher', value=old_content[:1000], inline=False)
        if new_content:
            embed.add_field(name='Nachher', value=new_content[:1000], inline=False)
        embed.add_field(name='Channel', value=channel.mention, inline=True)
        await self._log(guild, embed)

    # ── Message Delete ──────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        old = self._cache.pop(int(payload.message_id), None)
        if old:
            author, ch, content, ts = old
            embed = discord.Embed(
                title='🗑️ Nachricht gelöscht',
                description=content[:2000] if content else '*[Kein Inhalt]*',
                color=discord.Color.red(),
                timestamp=ts
            )
            embed.set_author(name=f'{author.display_name} ({author.id})')
            embed.add_field(name='Channel', value=ch.mention, inline=True)
        else:
            embed = discord.Embed(
                title='🗑️ Nachricht gelöscht',
                description='*[Nicht im Cache – älter als Bot-Restart]*',
                color=discord.Color.red(),
                timestamp=datetime.now(timezone.utc)
            )
            embed.add_field(name='Channel', value=f'<#{payload.channel_id}>', inline=True)
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        embed = discord.Embed(
            title='🗑️ Bulk-Nachrichten gelöscht',
            description=f'{len(payload.message_ids)} Nachrichten wurden gelöscht.',
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name='Channel', value=f'<#{payload.channel_id}>', inline=True)
        await self._log(guild, embed)

    # ── Reactions ───────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        embed = discord.Embed(
            title='😊 Reaction hinzugefügt',
            description=f'{user.mention} hat {reaction.emoji} zu einer Nachricht hinzugefügt',
            color=discord.Color.teal(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name='Channel', value=reaction.message.channel.mention, inline=True)
        embed.add_field(name='Nachricht', value=f'[Link]({reaction.message.jump_url})', inline=True)
        await self._log(reaction.message.guild, embed)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        embed = discord.Embed(
            title='😟 Reaction entfernt',
            description=f'{user.mention} hat {reaction.emoji} von einer Nachricht entfernt',
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name='Channel', value=reaction.message.channel.mention, inline=True)
        await self._log(reaction.message.guild, embed)

    @commands.Cog.listener()
    async def on_reaction_clear(self, reaction, users):
        if not reaction.message.guild:
            return
        embed = discord.Embed(
            title='🧹 Reactionss gelöscht',
            description=f'Alle Reactions auf einer Nachricht wurden zurückgesetzt ({len(users)} User)',
            color=discord.Color.light_grey(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name='Channel', value=reaction.message.channel.mention, inline=True)
        await self._log(reaction.message.guild, embed)

    # ── Member ──────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_member_join(self, member):
        embed = discord.Embed(
            title='📥 Member beigetreten',
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=f'{member.display_name} ({member.id})', icon_url=member.display_avatar.url)
        embed.add_field(name='Account erstellt', value=f'<t:{int(member.created_at.timestamp())}:R>', inline=True)
        embed.add_field(name='Member #', value=str(member.guild.member_count), inline=True)
        if member.bot:
            embed.add_field(name='Typ', value='🤖 Bot', inline=True)
        await self._log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        roles = [r.mention for r in member.roles if r != member.guild.default_role]
        embed = discord.Embed(
            title='📤 Member verlassen',
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=f'{member.display_name} ({member.id})', icon_url=member.display_avatar.url)
        if roles:
            embed.add_field(name='Rollen', value=', '.join(roles[:10]), inline=False)
        await self._log(member.guild, embed)
        try:
            async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                if entry.target.id == member.id:
                    log_audit_event('kick', {
                        'executor': str(entry.user),
                        'target': str(member),
                        'reason': entry.reason or '',
                    })
                    break
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        embed = discord.Embed(
            title='🔨 User gebannt',
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=f'{user.display_name} ({user.id})', icon_url=user.display_avatar.url)
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        embed = discord.Embed(
            title='✅ User entbannt',
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=f'{user.display_name} ({user.id})', icon_url=user.display_avatar.url)
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles == after.roles and before.nick == after.nick and before.timed_out_until == after.timed_out_until:
            return
        embed = discord.Embed(
            title='👤 Member aktualisiert',
            color=discord.Color.blurple(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=f'{after.display_name} ({after.id})')
        if before.nick != after.nick:
            embed.add_field(name='Nickname', value=f'{before.nick or before.name} → {after.nick or after.name}', inline=False)
        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)
        if added:
            embed.add_field(name='Rollen hinzugefügt', value=', '.join(r.mention for r in added), inline=False)
        if removed:
            embed.add_field(name='Rollen entfernt', value=', '.join(r.mention for r in removed), inline=False)
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                embed.add_field(name='🔇 Timeout', value=f'Bis {after.timed_out_until}', inline=False)
                log_audit_event('mute', {
                    'executor': 'Discord',
                    'target': str(after),
                    'reason': f'Timeout bis {after.timed_out_until}',
                })
            else:
                embed.add_field(name='✅ Timeout aufgehoben', value='Danach', inline=False)
        if embed.fields:
            await self._log(before.guild, embed)

    # ── Voice ───────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        changes = []
        if before.channel != after.channel:
            if before.channel:
                changes.append(f'**Verlassen:** {before.channel.name}')
            if after.channel:
                changes.append(f'**Beigetreten:** {after.channel.name}')
        if before.self_mute != after.self_mute:
            changes.append(f'Self-Mute: {"An" if after.self_mute else "Aus"}')
        if before.self_deaf != after.self_deaf:
            changes.append(f'Self-Deafen: {"An" if after.self_deaf else "Aus"}')
        if not changes:
            return
        embed = discord.Embed(
            title='🔊 Voice-Aktivität',
            description='\n'.join(changes),
            color=discord.Color.purple(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_author(name=f'{member.display_name} ({member.id})')
        await self._log(member.guild, embed)

    # ── Channels ────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_channel_create(self, channel):
        if not hasattr(channel, 'guild') or not channel.guild:
            return
        embed = discord.Embed(
            title='➕ Channel erstellt',
            description=f'{channel.mention} ({channel.name})',
            color=discord.Color.green(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name='Typ', value=str(channel.type), inline=True)
        if channel.category:
            embed.add_field(name='Kategorie', value=channel.category.name, inline=True)
        await self._log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_channel_delete(self, channel):
        if not hasattr(channel, 'guild') or not channel.guild:
            return
        embed = discord.Embed(
            title='➖ Channel gelöscht',
            description=f'{channel.name}',
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name='Typ', value=str(channel.type), inline=True)
        await self._log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_channel_update(self, before, after):
        if not hasattr(before, 'guild') or not before.guild:
            return
        changes = []
        if before.name != after.name:
            changes.append(f'Name: `{before.name}` → `{after.name}`')
        if before.topic != after.topic:
            changes.append(f'Topic geändert')
        if before.category_id != after.category_id:
            cat_before = before.category.name if before.category else 'Keine'
            cat_after = after.category.name if after.category else 'Keine'
            changes.append(f'Kategorie: `{cat_before}` → `{cat_after}`')
        if not changes:
            return
        embed = discord.Embed(
            title='✏️ Channel aktualisiert',
            description='\n'.join(changes),
            color=discord.Color.yellow(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name='Channel', value=after.mention, inline=True)
        await self._log(after.guild, embed)

    # ── Roles ───────────────────────────────────────────────────────
    @commands.Cog.listener()
    async def on_role_create(self, role):
        embed = discord.Embed(
            title='🏷️ Rolle erstellt',
            description=f'{role.mention} (`{role.name}`)',
            color=role.color if role.color != discord.Color.default() else discord.Color.greyple(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name='Farbe', value=str(role.color), inline=True)
        await self._log(role.guild, embed)

    @commands.Cog.listener()
    async def on_role_delete(self, role):
        embed = discord.Embed(
            title='🏷️ Rolle gelöscht',
            description=f'`{role.name}`',
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )
        await self._log(role.guild, embed)

    @commands.Cog.listener()
    async def on_role_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f'Name: `{before.name}` → `{after.name}`')
        if before.color != after.color:
            changes.append(f'Farbe: `{before.color}` → `{after.color}`')
        if before.permissions != after.permissions:
            changes.append('Berechtigungen geändert')
        if before.hoist != after.hoist:
            changes.append(f'Anzeige: {"Ja" if after.hoist else "Nein"}')
        if not changes:
            return
        embed = discord.Embed(
            title='🏷️ Rolle aktualisiert',
            description='\n'.join(changes),
            color=discord.Color.yellow(),
            timestamp=datetime.now(timezone.utc)
        )
        embed.add_field(name='Rolle', value=after.mention, inline=True)
        await self._log(after.guild, embed)


async def setup(bot):
    await bot.add_cog(AuditLogger(bot))
