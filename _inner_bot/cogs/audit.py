"""Umfassendes Audit-Logging für Nachrichten, Moderation und Serveränderungen."""

import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands

from cogs.dashboard import log_audit_event
from core.channelnames import find_channel, styled_text_name

AUDIT_BASE = "audit-log"
AUDIT_LOOKBACK_SECONDS = 15


class AuditLogger(commands.Cog):
    """Zeichnet wichtige Serverereignisse auf und ermittelt nach Möglichkeit den Ausführer."""

    def __init__(self, bot):
        self.bot = bot
        self._cache = {}  # message_id -> dict

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
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

    @staticmethod
    def _utcnow():
        return datetime.now(timezone.utc)

    @staticmethod
    def _entry_target_id(entry):
        target = getattr(entry, "target", None)
        return getattr(target, "id", None)

    async def _find_executor(self, guild, action, *, target_id=None, channel_id=None):
        """Findet einen passenden aktuellen Audit-Log-Eintrag.

        Discord-Audit-Logs sind nicht immer sofort konsistent, deshalb wird kurz
        mehrfach versucht. Falls View Audit Log fehlt oder kein passender Eintrag
        gefunden wird, wird None zurückgegeben.
        """
        try:
            for attempt in range(3):
                now = self._utcnow()
                async for entry in guild.audit_logs(limit=12, action=action):
                    created = entry.created_at
                    if (now - created).total_seconds() > AUDIT_LOOKBACK_SECONDS:
                        break
                    if target_id is not None and self._entry_target_id(entry) != target_id:
                        continue

                    extra = getattr(entry, "extra", None)
                    if channel_id is not None and extra is not None:
                        entry_channel = getattr(extra, "channel", None)
                        entry_channel_id = getattr(entry_channel, "id", None)
                        if entry_channel_id is not None and entry_channel_id != channel_id:
                            continue

                    return entry
                if attempt < 2:
                    await asyncio.sleep(0.45)
        except (discord.Forbidden, discord.HTTPException, AttributeError):
            return None
        return None

    @staticmethod
    def _executor_text(entry):
        if not entry or not getattr(entry, "user", None):
            return "Unbekannt / nicht im Audit Log"
        return f"{entry.user.mention} ({entry.user} · {entry.user.id})"

    async def _executor_field(self, guild, action, *, target_id=None, channel_id=None):
        entry = await self._find_executor(
            guild, action, target_id=target_id, channel_id=channel_id
        )
        return self._executor_text(entry), entry

    @staticmethod
    def _add_executor(embed, text):
        embed.add_field(name="Ausgeführt von", value=text, inline=True)

    @staticmethod
    def _add_reason(embed, entry):
        reason = getattr(entry, "reason", None) if entry else None
        if reason:
            embed.add_field(name="Grund", value=reason[:1024], inline=False)

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        self._cache[message.id] = {
            "author": message.author,
            "channel": message.channel,
            "content": message.content,
            "timestamp": message.created_at,
            "attachments": [a.filename for a in message.attachments[:10]],
        }
        if len(self._cache) > 5000:
            for key in list(self._cache.keys())[:1000]:
                self._cache.pop(key, None)

        embed = discord.Embed(
            title="💬 Nachricht",
            description=message.content[:4000] if message.content else "*[Kein Text]*",
            color=discord.Color.greyple(),
            timestamp=message.created_at,
        )
        embed.set_author(
            name=f"{message.author.display_name} ({message.author.id})",
            icon_url=message.author.display_avatar.url,
        )
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        if message.attachments:
            files = ", ".join(a.filename for a in message.attachments[:10])
            embed.add_field(name="Dateien", value=files[:1024], inline=True)
        if message.reference:
            ref = message.reference.resolved
            if isinstance(ref, discord.Message):
                ref_text = f"{ref.author.mention}: {ref.content[:300]}"
                embed.add_field(name="Antwort auf", value=ref_text[:1024], inline=False)
        embed.set_footer(text=f"#{message.channel.name}")
        await self._log(message.guild, embed)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        if payload.data.get("author"):
            author_id = payload.data["author"].get("id")
            if author_id and self.bot.user and int(author_id) == self.bot.user.id:
                return

        channel = self.bot.get_channel(payload.channel_id)
        if not channel or not getattr(channel, "guild", None):
            return
        guild = channel.guild
        old = self._cache.get(int(payload.message_id))
        new_content = payload.data.get("content", "")

        if old:
            author = old["author"]
            old_content = old["content"] or "*[Kein Text]*"
            timestamp = old["timestamp"]
            author_text = f"{author.mention} ({author} · {author.id})"
        else:
            author = None
            old_content = "*[Nicht im Cache – z. B. vor Bot-Neustart]*"
            timestamp = self._utcnow()
            author_text = "Unbekannt"

        embed = discord.Embed(
            title="📝 Nachricht bearbeitet",
            color=discord.Color.yellow(),
            timestamp=timestamp,
        )
        embed.add_field(name="Bearbeitet von", value=author_text, inline=True)
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        embed.add_field(name="Vorher", value=old_content[:1000], inline=False)
        embed.add_field(
            name="Nachher",
            value=(new_content or "*[Kein Text]*")[:1000],
            inline=False,
        )
        embed.set_footer(text="Nachrichtenänderungen haben keinen eigenen Discord-Audit-Log-Eintrag.")
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        old = self._cache.pop(int(payload.message_id), None)
        author_id = old["author"].id if old else None
        ch = guild.get_channel(payload.channel_id)
        channel_mention = ch.mention if ch else f"<#{payload.channel_id}>"
        executor_text, entry = await self._executor_field(
            guild,
            discord.AuditLogAction.message_delete,
            target_id=author_id,
            channel_id=payload.channel_id,
        )

        embed = discord.Embed(
            title="🗑️ Nachricht gelöscht",
            color=discord.Color.red(),
            timestamp=old["timestamp"] if old else self._utcnow(),
        )
        embed.set_author(
            name=f'{old["author"].display_name} ({old["author"].id})' if old else "Unbekannter Autor"
        )
        embed.add_field(
            name="Inhalt",
            value=(old["content"] if old and old["content"] else "*[Kein Inhalt]*")[:2000]
            if old
            else "*[Nicht im Cache – z. B. vor Bot-Neustart]*",
            inline=False,
        )
        embed.add_field(name="Channel", value=channel_mention, inline=True)
        self._add_executor(embed, executor_text)
        if old and old.get("attachments"):
            embed.add_field(
                name="Dateien",
                value=", ".join(old["attachments"])[:1024],
                inline=False,
            )
        self._add_reason(embed, entry)
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        executor_text, entry = await self._executor_field(
            guild,
            discord.AuditLogAction.message_bulk_delete,
            channel_id=payload.channel_id,
        )
        embed = discord.Embed(
            title="🗑️ Bulk-Nachrichten gelöscht",
            description=f"{len(payload.message_ids)} Nachrichten wurden gelöscht.",
            color=discord.Color.dark_red(),
            timestamp=self._utcnow(),
        )
        embed.add_field(name="Channel", value=f"<#{payload.channel_id}>", inline=True)
        self._add_executor(embed, executor_text)
        self._add_reason(embed, entry)
        await self._log(guild, embed)

    # ------------------------------------------------------------------
    # Reactions
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        embed = discord.Embed(
            title="😊 Reaction hinzugefügt",
            description=f"{user.mention} hat {reaction.emoji} zu einer Nachricht hinzugefügt",
            color=discord.Color.teal(),
            timestamp=self._utcnow(),
        )
        embed.add_field(name="Channel", value=reaction.message.channel.mention, inline=True)
        embed.add_field(name="Nachricht", value=f"[Öffnen]({reaction.message.jump_url})", inline=True)
        await self._log(reaction.message.guild, embed)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        embed = discord.Embed(
            title="😟 Reaction entfernt",
            description=f"{user.mention} hat {reaction.emoji} von einer Nachricht entfernt",
            color=discord.Color.orange(),
            timestamp=self._utcnow(),
        )
        embed.add_field(name="Channel", value=reaction.message.channel.mention, inline=True)
        embed.add_field(name="Nachricht", value=f"[Öffnen]({reaction.message.jump_url})", inline=True)
        await self._log(reaction.message.guild, embed)

    @commands.Cog.listener()
    async def on_reaction_clear(self, reaction, users):
        if not reaction.message.guild:
            return
        embed = discord.Embed(
            title="🧹 Reactions gelöscht",
            description=f"Alle Reactions auf einer Nachricht wurden entfernt ({len(users)} User).",
            color=discord.Color.light_grey(),
            timestamp=self._utcnow(),
        )
        embed.add_field(name="Channel", value=reaction.message.channel.mention, inline=True)
        await self._log(reaction.message.guild, embed)

    # ------------------------------------------------------------------
    # Members / moderation
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_member_join(self, member):
        embed = discord.Embed(
            title="📥 Member beigetreten",
            color=discord.Color.green(),
            timestamp=self._utcnow(),
        )
        embed.set_author(name=f"{member.display_name} ({member.id})", icon_url=member.display_avatar.url)
        embed.add_field(name="Account erstellt", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        embed.add_field(name="Member #", value=str(member.guild.member_count), inline=True)
        if member.bot:
            embed.add_field(name="Typ", value="🤖 Bot", inline=True)
        await self._log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        roles = [r.mention for r in member.roles if r != member.guild.default_role]
        kick_text, kick_entry = await self._executor_field(
            member.guild,
            discord.AuditLogAction.kick,
            target_id=member.id,
        )
        embed = discord.Embed(
            title="📤 Member verlassen",
            color=discord.Color.red(),
            timestamp=self._utcnow(),
        )
        embed.set_author(name=f"{member.display_name} ({member.id})", icon_url=member.display_avatar.url)
        embed.add_field(name="Ausgeführt von", value=kick_text, inline=True)
        if kick_entry:
            embed.add_field(name="Aktion", value="🥾 Kick erkannt", inline=True)
            self._add_reason(embed, kick_entry)
            log_audit_event("kick", {
                "executor": str(kick_entry.user),
                "target": str(member),
                "reason": kick_entry.reason or "",
            })
        else:
            embed.add_field(name="Aktion", value="👋 Normaler Leave oder Kick nicht ermittelbar", inline=True)
        if roles:
            embed.add_field(name="Rollen beim Verlassen", value=", ".join(roles[:10]), inline=False)
        await self._log(member.guild, embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        executor_text, entry = await self._executor_field(
            guild, discord.AuditLogAction.ban, target_id=user.id
        )
        embed = discord.Embed(title="🔨 User gebannt", color=discord.Color.dark_red(), timestamp=self._utcnow())
        embed.set_author(name=f"{user.display_name} ({user.id})", icon_url=user.display_avatar.url)
        self._add_executor(embed, executor_text)
        self._add_reason(embed, entry)
        if entry:
            log_audit_event("ban", {
                "executor": str(entry.user),
                "target": str(user),
                "reason": entry.reason or "",
            })
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        executor_text, entry = await self._executor_field(
            guild, discord.AuditLogAction.unban, target_id=user.id
        )
        embed = discord.Embed(title="✅ User entbannt", color=discord.Color.green(), timestamp=self._utcnow())
        embed.set_author(name=f"{user.display_name} ({user.id})", icon_url=user.display_avatar.url)
        self._add_executor(embed, executor_text)
        self._add_reason(embed, entry)
        await self._log(guild, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        role_changed = before.roles != after.roles
        nick_changed = before.nick != after.nick
        timeout_changed = before.timed_out_until != after.timed_out_until
        if not (role_changed or nick_changed or timeout_changed):
            return

        embed = discord.Embed(title="👤 Member aktualisiert", color=discord.Color.blurple(), timestamp=self._utcnow())
        embed.set_author(name=f"{after.display_name} ({after.id})")
        if nick_changed:
            embed.add_field(
                name="Nickname",
                value=f"{before.nick or before.name} → {after.nick or after.name}",
                inline=False,
            )
        added = set(after.roles) - set(before.roles)
        removed = set(before.roles) - set(after.roles)
        if added:
            text, entry = await self._executor_field(
                after.guild,
                discord.AuditLogAction.member_role_update,
                target_id=after.id,
            )
            embed.add_field(name="Rollen hinzugefügt", value=", ".join(r.mention for r in added), inline=False)
            embed.add_field(name="Ausgeführt von", value=text, inline=True)
            self._add_reason(embed, entry)
        if removed:
            text, entry = await self._executor_field(
                after.guild,
                discord.AuditLogAction.member_role_update,
                target_id=after.id,
            )
            embed.add_field(name="Rollen entfernt", value=", ".join(r.mention for r in removed), inline=False)
            embed.add_field(name="Ausgeführt von", value=text, inline=True)
            self._add_reason(embed, entry)
        if timeout_changed:
            action = "🔇 Timeout gesetzt" if after.timed_out_until else "✅ Timeout aufgehoben"
            embed.add_field(name="Timeout", value=action, inline=False)
            text, entry = await self._executor_field(
                after.guild,
                discord.AuditLogAction.member_update,
                target_id=after.id,
            )
            embed.add_field(name="Ausgeführt von", value=text, inline=True)
            self._add_reason(embed, entry)
            if after.timed_out_until:
                log_audit_event("mute", {
                    "executor": str(entry.user) if entry else "Unbekannt",
                    "target": str(after),
                    "reason": entry.reason if entry else f"Timeout bis {after.timed_out_until}",
                })
        if nick_changed and not (added or removed or timeout_changed):
            text, entry = await self._executor_field(
                after.guild,
                discord.AuditLogAction.member_update,
                target_id=after.id,
            )
            embed.add_field(name="Ausgeführt von", value=text, inline=True)
            self._add_reason(embed, entry)
        await self._log(after.guild, embed)

    # ------------------------------------------------------------------
    # Voice
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        changes = []
        action = None
        if before.channel != after.channel:
            if before.channel:
                changes.append(f"**Verlassen:** {before.channel.name}")
            if after.channel:
                changes.append(f"**Beigetreten:** {after.channel.name}")
        if before.self_mute != after.self_mute:
            changes.append(f"Self-Mute: {'An' if after.self_mute else 'Aus'}")
        if before.self_deaf != after.self_deaf:
            changes.append(f"Self-Deafen: {'An' if after.self_deaf else 'Aus'}")
        if not changes:
            return

        embed = discord.Embed(title="🔊 Voice-Aktivität", description="\n".join(changes), color=discord.Color.purple(), timestamp=self._utcnow())
        embed.set_author(name=f"{member.display_name} ({member.id})")
        if before.channel != after.channel and after.channel:
            action = discord.AuditLogAction.member_move
        elif before.channel != after.channel and not after.channel:
            action = discord.AuditLogAction.member_move
        if action:
            text, entry = await self._executor_field(member.guild, action, target_id=member.id)
            self._add_executor(embed, text)
            self._add_reason(embed, entry)
        await self._log(member.guild, embed)

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_channel_create(self, channel):
        if not getattr(channel, "guild", None):
            return
        text, entry = await self._executor_field(channel.guild, discord.AuditLogAction.channel_create, target_id=channel.id)
        embed = discord.Embed(title="➕ Channel erstellt", description=f"{channel.mention} ({channel.name})", color=discord.Color.green(), timestamp=self._utcnow())
        embed.add_field(name="Typ", value=str(channel.type), inline=True)
        self._add_executor(embed, text)
        if channel.category:
            embed.add_field(name="Kategorie", value=channel.category.name, inline=True)
        self._add_reason(embed, entry)
        await self._log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_channel_delete(self, channel):
        if not getattr(channel, "guild", None):
            return
        text, entry = await self._executor_field(channel.guild, discord.AuditLogAction.channel_delete, target_id=channel.id)
        embed = discord.Embed(title="➖ Channel gelöscht", description=channel.name, color=discord.Color.red(), timestamp=self._utcnow())
        embed.add_field(name="Typ", value=str(channel.type), inline=True)
        self._add_executor(embed, text)
        self._add_reason(embed, entry)
        await self._log(channel.guild, embed)

    @commands.Cog.listener()
    async def on_channel_update(self, before, after):
        if not getattr(before, "guild", None):
            return
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")
        if before.topic != after.topic:
            changes.append("Topic geändert")
        if before.category_id != after.category_id:
            cat_before = before.category.name if before.category else "Keine"
            cat_after = after.category.name if after.category else "Keine"
            changes.append(f"Kategorie: `{cat_before}` → `{cat_after}`")
        if before.overwrites != after.overwrites:
            changes.append("Berechtigungen/Overwrites geändert")
        if before.slowmode_delay != after.slowmode_delay:
            changes.append(f"Slowmode: `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")
        if not changes:
            return

        text, entry = await self._executor_field(before.guild, discord.AuditLogAction.channel_update, target_id=after.id)
        embed = discord.Embed(title="✏️ Channel aktualisiert", description="\n".join(changes), color=discord.Color.yellow(), timestamp=self._utcnow())
        embed.add_field(name="Channel", value=after.mention, inline=True)
        self._add_executor(embed, text)
        self._add_reason(embed, entry)
        await self._log(after.guild, embed)

    # ------------------------------------------------------------------
    # Roles
    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_role_create(self, role):
        text, entry = await self._executor_field(role.guild, discord.AuditLogAction.role_create, target_id=role.id)
        embed = discord.Embed(title="🏷️ Rolle erstellt", description=f"{role.mention} (`{role.name}`)", color=role.color if role.color != discord.Color.default() else discord.Color.greyple(), timestamp=self._utcnow())
        embed.add_field(name="Farbe", value=str(role.color), inline=True)
        self._add_executor(embed, text)
        self._add_reason(embed, entry)
        await self._log(role.guild, embed)

    @commands.Cog.listener()
    async def on_role_delete(self, role):
        text, entry = await self._executor_field(role.guild, discord.AuditLogAction.role_delete, target_id=role.id)
        embed = discord.Embed(title="🏷️ Rolle gelöscht", description=f"`{role.name}`", color=discord.Color.red(), timestamp=self._utcnow())
        self._add_executor(embed, text)
        self._add_reason(embed, entry)
        await self._log(role.guild, embed)

    @commands.Cog.listener()
    async def on_role_update(self, before, after):
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")
        if before.color != after.color:
            changes.append(f"Farbe: `{before.color}` → `{after.color}`")
        if before.permissions != after.permissions:
            changes.append("Berechtigungen geändert")
        if before.hoist != after.hoist:
            changes.append(f"Anzeige: {'Ja' if after.hoist else 'Nein'}")
        if before.mentionable != after.mentionable:
            changes.append(f"Mentionable: {'Ja' if after.mentionable else 'Nein'}")
        if not changes:
            return
        text, entry = await self._executor_field(after.guild, discord.AuditLogAction.role_update, target_id=after.id)
        embed = discord.Embed(title="🏷️ Rolle aktualisiert", description="\n".join(changes), color=discord.Color.yellow(), timestamp=self._utcnow())
        embed.add_field(name="Rolle", value=after.mention, inline=True)
        self._add_executor(embed, text)
        self._add_reason(embed, entry)
        await self._log(after.guild, embed)


async def setup(bot):
    await bot.add_cog(AuditLogger(bot))
