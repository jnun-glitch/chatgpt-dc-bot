"""ScratchAI Custom Commands.

Design:
- One global application-command root: /custom.
- User-created commands are resolved from Discord messages as !<name>.
- No dynamic slash command is registered for each custom command.
- Permissions, role/channel rules, cooldowns, aliases, responses, stats and
  audit history are stored in the dedicated normalized SQLite schema.

The response system is intentionally template/action based. It does not
execute Python, shell commands, SQL supplied by users, or arbitrary plugins.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from core.custom_commands_db import (
    add_audit,
    add_response,
    check_and_touch_cooldown,
    create_command,
    delete_command,
    delete_response,
    get_command,
    get_command_by_id,
    get_cooldown,
    get_invocation,
    init_custom_commands_db,
    list_aliases,
    list_audit,
    list_channel_rules,
    list_commands,
    list_manager_roles,
    list_responses,
    list_role_rules,
    record_use,
    remove_alias,
    remove_channel_rule,
    remove_role_rule,
    retention,
    search_commands,
    set_alias,
    set_channel_rule,
    set_cooldown,
    set_manager_role,
    set_role_rule,
    update_command,
)


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_.]+)\}")
MAX_RESPONSES_PER_COMMAND = 100
MAX_COMMANDS_PER_GUILD = 1000


class CustomCommands(commands.Cog):
    """Slash-managed, database-backed custom commands."""

    custom = app_commands.Group(
        name="custom",
        description="Custom Commands verwalten und testen",
    )
    response = app_commands.Group(
        name="response",
        description="Antworten eines Custom Commands verwalten",
        parent=custom,
    )
    role = app_commands.Group(
        name="role",
        description="Rollenregeln für Custom Commands verwalten",
        parent=custom,
    )
    channel = app_commands.Group(
        name="channel",
        description="Kanalregeln für Custom Commands verwalten",
        parent=custom,
    )
    manager = app_commands.Group(
        name="manager",
        description="Manager-Rollen für Custom Commands verwalten",
        parent=custom,
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        init_custom_commands_db()
        retention()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _name(raw: str) -> str:
        return raw.strip().casefold()

    def _valid_name(self, name: str) -> bool:
        return bool(NAME_RE.fullmatch(self._name(name)))

    def _is_manager(self, member: discord.Member) -> bool:
        if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
            return True
        manager_roles = set(list_manager_roles(member.guild.id))
        return any(str(role.id) in manager_roles for role in member.roles)

    def _is_admin(self, member: discord.Member) -> bool:
        return member.guild_permissions.administrator

    async def _require_manager(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("❌ Dieser Command funktioniert nur auf einem Server.", ephemeral=True)
            return False
        if not self._is_manager(interaction.user):
            await interaction.response.send_message(
                "⛔ Du brauchst **Administrator**, **Server verwalten** oder eine konfigurierte Custom-Manager-Rolle.",
                ephemeral=True,
            )
            return False
        return True

    async def _get_or_error(self, interaction: discord.Interaction, name: str) -> dict[str, Any] | None:
        command = get_command(interaction.guild_id, self._name(name))
        if not command:
            await interaction.response.send_message(f"❌ `!{name}` wurde nicht gefunden.", ephemeral=True)
            return None
        return command

    @staticmethod
    def _role_text(guild: discord.Guild, role_rows: list[dict[str, Any]], rule: str) -> str:
        ids = [str(row["role_id"]) for row in role_rows if row["rule"] == rule]
        mentions = []
        for role_id in ids:
            role = guild.get_role(int(role_id))
            mentions.append(role.mention if role else f"`{role_id}`")
        return ", ".join(mentions) or "—"

    @staticmethod
    def _channel_text(guild: discord.Guild, rows: list[dict[str, Any]], rule: str) -> str:
        ids = [str(row["channel_id"]) for row in rows if row["rule"] == rule]
        result = []
        for channel_id in ids:
            channel = guild.get_channel(int(channel_id))
            result.append(channel.mention if channel else f"`{channel_id}`")
        return ", ".join(result) or "—"

    @staticmethod
    def _build_embed(data: dict[str, Any]) -> discord.Embed | None:
        raw = data.get("embed_json")
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            return None
        embed = discord.Embed()
        if payload.get("title"):
            embed.title = payload["title"]
        if payload.get("description"):
            embed.description = payload["description"]
        if payload.get("url"):
            embed.url = payload["url"]
        if payload.get("footer"):
            embed.set_footer(text=payload["footer"])
        return embed

    @staticmethod
    def _placeholder_values(message: discord.Message, args: list[str]) -> dict[str, str]:
        guild = message.guild
        channel = message.channel
        user = message.author
        values = {
            "user": user.mention,
            "user.mention": user.mention,
            "user.id": str(user.id),
            "user.name": user.name,
            "user.display_name": getattr(user, "display_name", user.name),
            "username": user.name,
            "display_name": getattr(user, "display_name", user.name),
            "mention": user.mention,
            "author": user.mention,
            "author.mention": user.mention,
            "author.id": str(user.id),
            "author.name": user.name,
            "server": guild.name if guild else "DM",
            "server.name": guild.name if guild else "DM",
            "server.id": str(guild.id) if guild else "",
            "server.member_count": str(guild.member_count or 0) if guild else "0",
            "guild": guild.name if guild else "DM",
            "guild.name": guild.name if guild else "DM",
            "guild.id": str(guild.id) if guild else "",
            "channel": channel.mention if hasattr(channel, "mention") else "#channel",
            "channel.name": getattr(channel, "name", ""),
            "channel.id": str(channel.id),
            "message": message.content,
            "message.id": str(message.id),
            "args": " ".join(args),
        }
        for index, value in enumerate(args):
            values[f"args.{index}"] = value
            values[f"arg{index}"] = value
            values[str(index)] = value
        return values

    @classmethod
    def _render(cls, text: str, message: discord.Message, args: list[str]) -> str:
        values = cls._placeholder_values(message, args)

        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            return values.get(key, match.group(0))

        return PLACEHOLDER_RE.sub(replace, text)

    @staticmethod
    def _allowed_mentions(command: dict[str, Any]) -> discord.AllowedMentions:
        return discord.AllowedMentions(
            everyone=bool(command["allow_everyone_mentions"]),
            roles=bool(command["allow_role_mentions"]),
            users=bool(command["allow_user_mentions"]),
        )

    @staticmethod
    def _matches_role_policy(command_id: int, member: discord.Member) -> bool:
        rules = list_role_rules(command_id)
        deny_ids = {str(row["role_id"]) for row in rules if row["rule"] == "deny"}
        allow_ids = {str(row["role_id"]) for row in rules if row["rule"] == "allow"}
        if any(str(role.id) in deny_ids for role in member.roles):
            return False
        if allow_ids and not any(str(role.id) in allow_ids for role in member.roles):
            return False
        return True

    @staticmethod
    def _matches_channel_policy(command_id: int, channel_id: int) -> bool:
        rules = list_channel_rules(command_id)
        channel = str(channel_id)
        deny_ids = {str(row["channel_id"]) for row in rules if row["rule"] == "deny"}
        allow_ids = {str(row["channel_id"]) for row in rules if row["rule"] == "allow"}
        if channel in deny_ids:
            return False
        if allow_ids and channel not in allow_ids:
            return False
        return True

    async def _send_response(self, message: discord.Message, command: dict[str, Any], response: dict[str, Any], args: list[str]):
        content = self._render(response.get("content") or "", message, args)
        embed = self._build_embed(response)
        if embed:
            if embed.title:
                embed.title = self._render(embed.title, message, args)
            if embed.description:
                embed.description = self._render(embed.description, message, args)
            if embed.footer and embed.footer.text:
                embed.set_footer(text=self._render(embed.footer.text, message, args))
        if not content and not embed:
            return None

        sent = await message.channel.send(
            content=content or None,
            embed=embed,
            allowed_mentions=self._allowed_mentions(command),
        )

        if command.get("delete_trigger") and message.guild and message.channel.permissions_for(message.guild.me).manage_messages:
            try:
                await message.delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

        delay = command.get("delete_reply_after")
        if delay and int(delay) > 0:
            asyncio.create_task(self._delete_later(sent, int(delay)))
        return sent

    @staticmethod
    async def _delete_later(message: discord.Message, delay: int) -> None:
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

    @staticmethod
    def _weighted_response(responses: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not responses:
            return None
        weights = [max(1, int(row.get("weight") or 1)) for row in responses]
        return random.choices(responses, weights=weights, k=1)[0]

    # ------------------------------------------------------------------
    # /custom overview and lifecycle
    # ------------------------------------------------------------------
    @custom.command(name="panel", description="Zeigt das Custom-Command Dashboard")
    async def cmd_panel(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Nur auf einem Server.", ephemeral=True)
        rows = list_commands(interaction.guild_id)
        active = sum(1 for row in rows if row["enabled"])
        total_uses = sum(int(row["uses"] or 0) for row in rows)
        most_used = max(rows, key=lambda row: int(row["uses"] or 0), default=None)
        embed = discord.Embed(title="🧩 ScratchAI Custom Commands", color=discord.Color.blurple())
        embed.description = (
            "Ein zentral verwaltetes Custom-Command-System.\n\n"
            "**Ausführung:** `!name`\n"
            "**Verwaltung:** `/custom ...`\n"
            "**Slash-Slots:** Nur ein `/custom`-Root-Command."
        )
        embed.add_field(name="Commands", value=f"**{len(rows)}** insgesamt\n🟢 {active} aktiv", inline=True)
        embed.add_field(name="Nutzung", value=f"**{total_uses:,}** Ausführungen", inline=True)
        embed.add_field(name="Top Command", value=f"`!{most_used['name']}`" if most_used else "—", inline=True)
        embed.set_footer(text="/custom list • /custom create • /custom info")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @custom.command(name="create", description="Erstellt einen neuen Custom Command")
    @app_commands.describe(
        name="Name ohne !, z.B. welcome",
        response_text="Antwort. Platzhalter: {user}, {mention}, {server}, {channel}, {args}, {args.0}...",
        description="Kurze Beschreibung des Commands",
    )
    async def cmd_create(self, interaction: discord.Interaction, name: str, response_text: str, description: str = ""):
        if not await self._require_manager(interaction):
            return
        normalized = self._name(name)
        if not self._valid_name(normalized):
            return await interaction.response.send_message(
                "❌ Name ungültig. Erlaubt sind `a-z`, `0-9`, `_` und `-` (max. 32 Zeichen).", ephemeral=True
            )
        if len(response_text) > 2000:
            return await interaction.response.send_message("❌ Die Antwort darf maximal 2000 Zeichen haben.", ephemeral=True)
        if len(list_commands(interaction.guild_id)) >= MAX_COMMANDS_PER_GUILD:
            return await interaction.response.send_message("❌ Serverlimit von 1000 Custom Commands erreicht.", ephemeral=True)
        if self.bot.get_command(normalized):
            return await interaction.response.send_message(
                f"❌ `!{normalized}` ist bereits ein normaler ScratchAI-Command und kann nicht überschrieben werden.",
                ephemeral=True,
            )
        if get_command(interaction.guild_id, normalized):
            return await interaction.response.send_message(f"❌ `!{normalized}` existiert bereits.", ephemeral=True)

        try:
            command_id = create_command(interaction.guild_id, normalized, description[:500], interaction.user.id)
            add_response(command_id, response_text)
            add_audit(interaction.guild_id, command_id, "create", interaction.user.id, f"name={normalized}")
        except Exception as exc:
            return await interaction.response.send_message(f"❌ Erstellen fehlgeschlagen: `{type(exc).__name__}`", ephemeral=True)

        await interaction.response.send_message(
            f"✅ **`!{normalized}` erstellt!**\n\n"
            f"**Antwort:** {response_text[:500]}\n"
            f"**Beschreibung:** {description or '—'}\n\n"
            f"Verwalte ihn mit `/custom info name:{normalized}`.",
            ephemeral=True,
        )

    @custom.command(name="edit", description="Bearbeitet Beschreibung oder Status")
    @app_commands.describe(
        name="Name des Custom Commands",
        description="Neue Beschreibung",
        enabled="Aktiv oder deaktiviert",
    )
    async def cmd_edit(self, interaction: discord.Interaction, name: str, description: str | None = None, enabled: bool | None = None):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        fields: dict[str, Any] = {}
        if description is not None:
            fields["description"] = description[:500]
        if enabled is not None:
            fields["enabled"] = int(enabled)
        if not fields:
            return await interaction.response.send_message("ℹ️ Nichts zum Ändern angegeben.", ephemeral=True)
        update_command(interaction.guild_id, command["name"], interaction.user.id, **fields)
        add_audit(interaction.guild_id, command["id"], "edit", interaction.user.id, json.dumps(fields, ensure_ascii=False))
        await interaction.response.send_message(f"✅ `!{command['name']}` aktualisiert.", ephemeral=True)

    @custom.command(name="delete", description="Löscht einen Custom Command")
    @app_commands.describe(name="Name des Custom Commands")
    async def cmd_delete(self, interaction: discord.Interaction, name: str):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        deleted = delete_command(interaction.guild_id, command["name"])
        if deleted:
            add_audit(interaction.guild_id, None, "delete", interaction.user.id, f"deleted={command['name']}")
        await interaction.response.send_message(f"🗑️ `!{command['name']}` gelöscht.", ephemeral=True)

    @custom.command(name="enable", description="Aktiviert einen Custom Command")
    @app_commands.describe(name="Name des Custom Commands")
    async def cmd_enable(self, interaction: discord.Interaction, name: str):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        update_command(interaction.guild_id, command["name"], interaction.user.id, enabled=1)
        add_audit(interaction.guild_id, command["id"], "enable", interaction.user.id)
        await interaction.response.send_message(f"🟢 `!{command['name']}` aktiviert.", ephemeral=True)

    @custom.command(name="disable", description="Deaktiviert einen Custom Command")
    @app_commands.describe(name="Name des Custom Commands")
    async def cmd_disable(self, interaction: discord.Interaction, name: str):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        update_command(interaction.guild_id, command["name"], interaction.user.id, enabled=0)
        add_audit(interaction.guild_id, command["id"], "disable", interaction.user.id)
        await interaction.response.send_message(f"🔴 `!{command['name']}` deaktiviert.", ephemeral=True)

    @custom.command(name="list", description="Listet Custom Commands auf")
    @app_commands.describe(show_disabled="Auch deaktivierte Commands anzeigen")
    async def cmd_list(self, interaction: discord.Interaction, show_disabled: bool = True):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Nur auf einem Server.", ephemeral=True)
        rows = list_commands(interaction.guild_id, include_disabled=show_disabled)
        if not rows:
            return await interaction.response.send_message("📭 Noch keine Custom Commands vorhanden.", ephemeral=True)

        lines = []
        for row in rows[:100]:
            status = "🟢" if row["enabled"] else "🔴"
            lines.append(f"{status} `!{row['name']}` — {int(row['uses'] or 0):,}x")
        embed = discord.Embed(title="🧩 Custom Commands", description="\n".join(lines), color=discord.Color.blurple())
        embed.set_footer(text=f"{len(rows)} Commands • /custom info name:<name>")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @custom.command(name="search", description="Sucht Custom Commands")
    @app_commands.describe(query="Suchtext")
    async def cmd_search(self, interaction: discord.Interaction, query: str):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Nur auf einem Server.", ephemeral=True)
        rows = search_commands(interaction.guild_id, query[:100], limit=25)
        if not rows:
            return await interaction.response.send_message("🔎 Keine Treffer.", ephemeral=True)
        embed = discord.Embed(
            title=f"🔎 Suche: {query[:80]}",
            description="\n".join(f"`!{row['name']}` — {row['description'] or 'Keine Beschreibung'}" for row in rows),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @custom.command(name="info", description="Zeigt alle Einstellungen eines Custom Commands")
    @app_commands.describe(name="Name des Custom Commands")
    async def cmd_info(self, interaction: discord.Interaction, name: str):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Nur auf einem Server.", ephemeral=True)
        command = get_command(interaction.guild_id, self._name(name))
        if not command:
            return await interaction.response.send_message(f"❌ `!{name}` wurde nicht gefunden.", ephemeral=True)
        responses = list_responses(command["id"])
        aliases = list_aliases(command["id"])
        role_rules = list_role_rules(command["id"])
        channel_rules = list_channel_rules(command["id"])
        cooldown = get_cooldown(command["id"])
        embed = discord.Embed(title=f"🧩 !{command['name']}", color=discord.Color.green() if command["enabled"] else discord.Color.red())
        embed.add_field(name="Status", value="🟢 Aktiv" if command["enabled"] else "🔴 Deaktiviert", inline=True)
        embed.add_field(name="Nutzung", value=f"{int(command['uses'] or 0):,}", inline=True)
        embed.add_field(name="Antworten", value=str(len(responses)), inline=True)
        embed.add_field(name="Beschreibung", value=command["description"] or "—", inline=False)
        embed.add_field(name="Aliase", value=", ".join(f"`!{a}`" for a in aliases) or "—", inline=False)
        embed.add_field(name="Rollen erlaubt", value=self._role_text(interaction.guild, role_rules, "allow"), inline=True)
        embed.add_field(name="Rollen blockiert", value=self._role_text(interaction.guild, role_rules, "deny"), inline=True)
        embed.add_field(name="Kanäle erlaubt", value=self._channel_text(interaction.guild, channel_rules, "allow"), inline=True)
        embed.add_field(name="Kanäle blockiert", value=self._channel_text(interaction.guild, channel_rules, "deny"), inline=True)
        embed.add_field(name="Cooldown", value=f"{cooldown['seconds']}s / {cooldown['scope']}" if cooldown else "Keiner", inline=True)
        embed.add_field(name="Trigger löschen", value="Ja" if command["delete_trigger"] else "Nein", inline=True)
        embed.add_field(name="Antwort löschen", value=f"nach {command['delete_reply_after']}s" if command["delete_reply_after"] else "Nein", inline=True)
        embed.add_field(
            name="Mentions",
            value=f"User: {'✅' if command['allow_user_mentions'] else '❌'} | Rollen: {'✅' if command['allow_role_mentions'] else '❌'} | Everyone: {'✅' if command['allow_everyone_mentions'] else '❌'}",
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @custom.command(name="test", description="Testet einen Custom Command")
    @app_commands.describe(name="Name des Custom Commands", argumente="Optionale Test-Argumente")
    async def cmd_test(self, interaction: discord.Interaction, name: str, argumente: str = ""):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        fake_content = f"!{command['name']} {argumente}".strip()
        # Build a lightweight preview without mutating usage/cooldown state.
        class Preview:
            def __init__(self, source: discord.Interaction, content: str):
                self.author = source.user
                self.guild = source.guild
                self.channel = source.channel
                self.content = content
                self.id = 0

        fake = Preview(interaction, fake_content)
        args = argumente.split() if argumente else []
        responses = list_responses(command["id"])
        response = self._weighted_response(responses)
        if not response:
            return await interaction.response.send_message("❌ Keine aktive Antwort vorhanden.", ephemeral=True)
        # Preview uses a Message-compatible shape for rendering only.
        content = self._render(response.get("content") or "", fake, args)  # type: ignore[arg-type]
        embed = self._build_embed(response)
        if embed and embed.description:
            embed.description = self._render(embed.description, fake, args)  # type: ignore[arg-type]
        preview_embed = discord.Embed(title=f"🧪 Test: !{command['name']}", color=discord.Color.blurple())
        preview_embed.add_field(name="Input", value=f"`{fake_content[:1000]}`", inline=False)
        preview_embed.add_field(name="Antwort", value=(content or "(Embed)" )[:1000], inline=False)
        if embed:
            preview_embed.add_field(name="Embed", value=f"Titel: {embed.title or '—'}\nBeschreibung: {(embed.description or '—')[:500]}", inline=False)
        await interaction.response.send_message(embed=preview_embed, ephemeral=True)

    @custom.command(name="settings", description="Antwort-/Mention-/Lösch-Einstellungen setzen")
    @app_commands.describe(
        name="Name des Custom Commands",
        delete_trigger="Trigger-Nachricht nach Ausführung löschen",
        delete_reply_after="Antwort nach X Sekunden löschen (0 = nie)",
        user_mentions="User-Mentions erlauben",
        role_mentions="Rollen-Mentions erlauben",
        everyone_mentions="@everyone/@here erlauben",
    )
    async def cmd_settings(
        self,
        interaction: discord.Interaction,
        name: str,
        delete_trigger: bool | None = None,
        delete_reply_after: int | None = None,
        user_mentions: bool | None = None,
        role_mentions: bool | None = None,
        everyone_mentions: bool | None = None,
    ):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        fields: dict[str, Any] = {}
        if delete_trigger is not None:
            fields["delete_trigger"] = int(delete_trigger)
        if delete_reply_after is not None:
            if not 0 <= delete_reply_after <= 86400:
                return await interaction.response.send_message("❌ `delete_reply_after` muss zwischen 0 und 86400 liegen.", ephemeral=True)
            fields["delete_reply_after"] = delete_reply_after or None
        if user_mentions is not None:
            fields["allow_user_mentions"] = int(user_mentions)
        if role_mentions is not None:
            fields["allow_role_mentions"] = int(role_mentions)
        if everyone_mentions is not None:
            fields["allow_everyone_mentions"] = int(everyone_mentions)
        if not fields:
            return await interaction.response.send_message("ℹ️ Keine Einstellungen angegeben.", ephemeral=True)
        update_command(interaction.guild_id, command["name"], interaction.user.id, **fields)
        add_audit(interaction.guild_id, command["id"], "settings", interaction.user.id, json.dumps(fields))
        await interaction.response.send_message(f"⚙️ `!{command['name']}` Einstellungen gespeichert.", ephemeral=True)

    @custom.command(name="alias", description="Fügt einen Alias zu einem Custom Command hinzu")
    @app_commands.describe(name="Name des Commands", alias="Alternativer Name")
    async def cmd_alias(self, interaction: discord.Interaction, name: str, alias: str):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        normalized = self._name(alias)
        if not self._valid_name(normalized):
            return await interaction.response.send_message("❌ Ungültiger Alias.", ephemeral=True)
        if self.bot.get_command(normalized):
            return await interaction.response.send_message(f"❌ `!{normalized}` ist ein vorhandener Bot-Command.", ephemeral=True)
        set_alias(command["id"], normalized)
        add_audit(interaction.guild_id, command["id"], "alias_add", interaction.user.id, normalized)
        await interaction.response.send_message(f"✅ Alias `!{normalized}` für `!{command['name']}` gesetzt.", ephemeral=True)

    @custom.command(name="unalias", description="Entfernt einen Alias")
    @app_commands.describe(name="Name des Commands", alias="Alias")
    async def cmd_unalias(self, interaction: discord.Interaction, name: str, alias: str):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        removed = remove_alias(command["id"], self._name(alias))
        if removed:
            add_audit(interaction.guild_id, command["id"], "alias_remove", interaction.user.id, self._name(alias))
        await interaction.response.send_message(f"{'✅' if removed else 'ℹ️'} Alias verarbeitet.", ephemeral=True)

    # ------------------------------------------------------------------
    # Responses
    # ------------------------------------------------------------------
    @response.command(name="add", description="Fügt eine zusätzliche Antwort hinzu")
    @app_commands.describe(
        name="Name des Commands",
        text="Text der Antwort",
        weight="Gewichtung für Random-Auswahl, Standard 1",
    )
    async def response_add(self, interaction: discord.Interaction, name: str, text: str, weight: int = 1):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        if len(list_responses(command["id"], enabled_only=False)) >= MAX_RESPONSES_PER_COMMAND:
            return await interaction.response.send_message("❌ Maximal 100 Antworten pro Command.", ephemeral=True)
        if len(text) > 2000:
            return await interaction.response.send_message("❌ Maximal 2000 Zeichen.", ephemeral=True)
        if not 1 <= weight <= 1000:
            return await interaction.response.send_message("❌ Gewicht muss zwischen 1 und 1000 liegen.", ephemeral=True)
        response_id = add_response(command["id"], text, weight=weight)
        add_audit(interaction.guild_id, command["id"], "response_add", interaction.user.id, f"response_id={response_id}")
        await interaction.response.send_message(f"✅ Antwort **#{response_id}** hinzugefügt.", ephemeral=True)

    @response.command(name="embed", description="Fügt eine Embed-Antwort hinzu")
    @app_commands.describe(
        name="Name des Commands",
        title="Embed-Titel",
        description="Embed-Beschreibung",
        footer="Optionaler Footer",
        url="Optionaler Link",
        weight="Gewichtung für Random-Auswahl",
    )
    async def response_embed(
        self,
        interaction: discord.Interaction,
        name: str,
        title: str = "",
        description: str = "",
        footer: str = "",
        url: str = "",
        weight: int = 1,
    ):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        if not title and not description:
            return await interaction.response.send_message("❌ Mindestens Titel oder Beschreibung angeben.", ephemeral=True)
        if len(title) > 256 or len(description) > 4096 or len(footer) > 2048:
            return await interaction.response.send_message("❌ Embed-Limits überschritten.", ephemeral=True)
        payload = {"title": title, "description": description, "footer": footer, "url": url}
        response_id = add_response(command["id"], "", json.dumps(payload, ensure_ascii=False), weight=weight)
        add_audit(interaction.guild_id, command["id"], "response_embed_add", interaction.user.id, f"response_id={response_id}")
        await interaction.response.send_message(f"✅ Embed-Antwort **#{response_id}** hinzugefügt.", ephemeral=True)

    @response.command(name="delete", description="Löscht eine Antwort")
    @app_commands.describe(name="Name des Commands", response_id="ID aus /custom info")
    async def response_delete(self, interaction: discord.Interaction, name: str, response_id: int):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        deleted = delete_response(command["id"], response_id)
        if deleted:
            add_audit(interaction.guild_id, command["id"], "response_delete", interaction.user.id, str(response_id))
        await interaction.response.send_message(f"{'🗑️' if deleted else 'ℹ️'} Antwort verarbeitet.", ephemeral=True)

    @response.command(name="list", description="Listet die Antworten eines Commands")
    @app_commands.describe(name="Name des Commands")
    async def response_list(self, interaction: discord.Interaction, name: str):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Nur auf einem Server.", ephemeral=True)
        command = get_command(interaction.guild_id, self._name(name))
        if not command:
            return await interaction.response.send_message("❌ Nicht gefunden.", ephemeral=True)
        rows = list_responses(command["id"], enabled_only=False)
        if not rows:
            return await interaction.response.send_message("📭 Keine Antworten.", ephemeral=True)
        lines = []
        for row in rows:
            kind = "🎨 Embed" if row.get("embed_json") else "💬 Text"
            preview = (row.get("content") or "").replace("\n", " ")[:80] or "—"
            lines.append(f"**#{row['id']}** {kind} • Gewicht {row['weight']} • `{preview}`")
        embed = discord.Embed(title=f"💬 Antworten — !{command['name']}", description="\n".join(lines[:100]), color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # Role rules — explicit allow/deny, deny wins, allow list becomes a whitelist.
    # ------------------------------------------------------------------
    @role.command(name="allow", description="Erlaubt einer Rolle die Nutzung")
    @app_commands.describe(name="Custom Command", rolle="Rolle")
    async def role_allow(self, interaction: discord.Interaction, name: str, rolle: discord.Role):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        set_role_rule(command["id"], rolle.id, "allow")
        add_audit(interaction.guild_id, command["id"], "role_allow", interaction.user.id, str(rolle.id))
        await interaction.response.send_message(f"✅ {rolle.mention} darf `!{command['name']}` benutzen.", ephemeral=True)

    @role.command(name="deny", description="Verbietet einer Rolle die Nutzung")
    @app_commands.describe(name="Custom Command", rolle="Rolle")
    async def role_deny(self, interaction: discord.Interaction, name: str, rolle: discord.Role):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        set_role_rule(command["id"], rolle.id, "deny")
        add_audit(interaction.guild_id, command["id"], "role_deny", interaction.user.id, str(rolle.id))
        await interaction.response.send_message(f"🚫 {rolle.mention} darf `!{command['name']}` nicht benutzen.", ephemeral=True)

    @role.command(name="remove", description="Entfernt eine Rollenregel")
    @app_commands.describe(name="Custom Command", rolle="Rolle", regel="allow oder deny")
    @app_commands.choices(regel=[app_commands.Choice(name="Erlauben", value="allow"), app_commands.Choice(name="Verbieten", value="deny")])
    async def role_remove(self, interaction: discord.Interaction, name: str, rolle: discord.Role, regel: str):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        removed = remove_role_rule(command["id"], rolle.id, regel)
        if removed:
            add_audit(interaction.guild_id, command["id"], "role_remove", interaction.user.id, f"{regel}:{rolle.id}")
        await interaction.response.send_message(f"{'✅ Regel entfernt' if removed else 'ℹ️ Regel nicht gefunden'}.", ephemeral=True)

    @role.command(name="list", description="Zeigt Rollenregeln")
    @app_commands.describe(name="Custom Command")
    async def role_list(self, interaction: discord.Interaction, name: str):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Nur auf einem Server.", ephemeral=True)
        command = get_command(interaction.guild_id, self._name(name))
        if not command:
            return await interaction.response.send_message("❌ Nicht gefunden.", ephemeral=True)
        rules = list_role_rules(command["id"])
        embed = discord.Embed(title=f"🛡️ Rollenregeln — !{command['name']}", color=discord.Color.blurple())
        embed.add_field(name="✅ Erlaubt", value=self._role_text(interaction.guild, rules, "allow"), inline=False)
        embed.add_field(name="🚫 Verboten", value=self._role_text(interaction.guild, rules, "deny"), inline=False)
        embed.set_footer(text="Wenn Allow-Rollen gesetzt sind, braucht der Nutzer mindestens eine davon. Deny gewinnt.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # Channel rules
    # ------------------------------------------------------------------
    @channel.command(name="allow", description="Erlaubt die Nutzung in einem Kanal")
    @app_commands.describe(name="Custom Command", kanal="Kanal")
    async def channel_allow(self, interaction: discord.Interaction, name: str, kanal: discord.TextChannel):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        set_channel_rule(command["id"], kanal.id, "allow")
        add_audit(interaction.guild_id, command["id"], "channel_allow", interaction.user.id, str(kanal.id))
        await interaction.response.send_message(f"✅ `!{command['name']}` darf in {kanal.mention} benutzt werden.", ephemeral=True)

    @channel.command(name="deny", description="Verbietet die Nutzung in einem Kanal")
    @app_commands.describe(name="Custom Command", kanal="Kanal")
    async def channel_deny(self, interaction: discord.Interaction, name: str, kanal: discord.TextChannel):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        set_channel_rule(command["id"], kanal.id, "deny")
        add_audit(interaction.guild_id, command["id"], "channel_deny", interaction.user.id, str(kanal.id))
        await interaction.response.send_message(f"🚫 `!{command['name']}` darf nicht in {kanal.mention} benutzt werden.", ephemeral=True)

    @channel.command(name="remove", description="Entfernt eine Kanalregel")
    @app_commands.describe(name="Custom Command", kanal="Kanal", regel="allow oder deny")
    @app_commands.choices(regel=[app_commands.Choice(name="Erlauben", value="allow"), app_commands.Choice(name="Verbieten", value="deny")])
    async def channel_remove(self, interaction: discord.Interaction, name: str, kanal: discord.TextChannel, regel: str):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        removed = remove_channel_rule(command["id"], kanal.id, regel)
        if removed:
            add_audit(interaction.guild_id, command["id"], "channel_remove", interaction.user.id, f"{regel}:{kanal.id}")
        await interaction.response.send_message(f"{'✅ Regel entfernt' if removed else 'ℹ️ Regel nicht gefunden' }.", ephemeral=True)

    @channel.command(name="list", description="Zeigt Kanalregeln")
    @app_commands.describe(name="Custom Command")
    async def channel_list(self, interaction: discord.Interaction, name: str):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Nur auf einem Server.", ephemeral=True)
        command = get_command(interaction.guild_id, self._name(name))
        if not command:
            return await interaction.response.send_message("❌ Nicht gefunden.", ephemeral=True)
        rules = list_channel_rules(command["id"])
        embed = discord.Embed(title=f"📍 Kanalregeln — !{command['name']}", color=discord.Color.blurple())
        embed.add_field(name="✅ Erlaubt", value=self._channel_text(interaction.guild, rules, "allow"), inline=False)
        embed.add_field(name="🚫 Verboten", value=self._channel_text(interaction.guild, rules, "deny"), inline=False)
        embed.set_footer(text="Wenn Allow-Kanäle gesetzt sind, muss der Command dort benutzt werden. Deny gewinnt.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # Manager roles
    # ------------------------------------------------------------------
    @manager.command(name="add", description="Erlaubt einer Rolle die Verwaltung von Custom Commands")
    @app_commands.describe(rolle="Manager-Rolle")
    async def manager_add(self, interaction: discord.Interaction, rolle: discord.Role):
        if not self._is_admin(interaction.user):
            return await interaction.response.send_message("⛔ Nur Administratoren dürfen Manager-Rollen ändern.", ephemeral=True)
        set_manager_role(interaction.guild_id, rolle.id, True)
        add_audit(interaction.guild_id, None, "manager_role_add", interaction.user.id, str(rolle.id))
        await interaction.response.send_message(f"✅ {rolle.mention} kann jetzt Custom Commands verwalten.", ephemeral=True)

    @manager.command(name="remove", description="Entfernt eine Manager-Rolle")
    @app_commands.describe(rolle="Manager-Rolle")
    async def manager_remove(self, interaction: discord.Interaction, rolle: discord.Role):
        if not self._is_admin(interaction.user):
            return await interaction.response.send_message("⛔ Nur Administratoren dürfen Manager-Rollen ändern.", ephemeral=True)
        set_manager_role(interaction.guild_id, rolle.id, False)
        add_audit(interaction.guild_id, None, "manager_role_remove", interaction.user.id, str(rolle.id))
        await interaction.response.send_message(f"✅ {rolle.mention} ist keine Custom-Manager-Rolle mehr.", ephemeral=True)

    @manager.command(name="list", description="Zeigt alle Manager-Rollen")
    async def manager_list(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Nur auf einem Server.", ephemeral=True)
        ids = list_manager_roles(interaction.guild_id)
        mentions = []
        for role_id in ids:
            role = interaction.guild.get_role(int(role_id))
            mentions.append(role.mention if role else f"`{role_id}`")
        embed = discord.Embed(
            title="🛠️ Custom-Manager",
            description="\n".join(mentions) if mentions else "Keine Manager-Rollen konfiguriert.",
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # Cooldowns
    # ------------------------------------------------------------------
    @custom.command(name="cooldown", description="Setzt oder entfernt einen Cooldown")
    @app_commands.describe(name="Custom Command", sekunden="0 = entfernen", scope="user, channel, guild oder global")
    @app_commands.choices(scope=[
        app_commands.Choice(name="Pro Benutzer", value="user"),
        app_commands.Choice(name="Pro Kanal", value="channel"),
        app_commands.Choice(name="Pro Server", value="guild"),
        app_commands.Choice(name="Global", value="global"),
    ])
    async def cmd_cooldown(self, interaction: discord.Interaction, name: str, sekunden: int, scope: str):
        if not await self._require_manager(interaction):
            return
        command = await self._get_or_error(interaction, name)
        if not command:
            return
        if sekunden == 0:
            from core.custom_commands_db import _connect
            conn = _connect()
            try:
                conn.execute("DELETE FROM custom_command_cooldowns WHERE command_id = ?", (command["id"],))
                conn.commit()
            finally:
                conn.close()
            text = "entfernt"
        elif 1 <= sekunden <= 86400:
            set_cooldown(command["id"], scope, sekunden)
            text = f"{sekunden}s / {scope}"
        else:
            return await interaction.response.send_message("❌ Cooldown muss 0 oder 1-86400 Sekunden sein.", ephemeral=True)
        add_audit(interaction.guild_id, command["id"], "cooldown", interaction.user.id, text)
        await interaction.response.send_message(f"⏱️ Cooldown für `!{command['name']}`: **{text}**.", ephemeral=True)

    # ------------------------------------------------------------------
    # Stats and audit
    # ------------------------------------------------------------------
    @custom.command(name="stats", description="Zeigt Nutzungsstatistiken")
    @app_commands.describe(name="Optional: einzelner Custom Command")
    async def cmd_stats(self, interaction: discord.Interaction, name: str | None = None):
        if not interaction.guild:
            return await interaction.response.send_message("❌ Nur auf einem Server.", ephemeral=True)
        if name:
            command = get_command(interaction.guild_id, self._name(name))
            if not command:
                return await interaction.response.send_message("❌ Nicht gefunden.", ephemeral=True)
            rows = list_audit(interaction.guild_id, command["id"], limit=10)
            text = "\n".join(f"`{row['created_at']}` • `{row['action']}` • <@{row['actor_id']}>" for row in rows) or "Keine Audit-Einträge."
            embed = discord.Embed(title=f"📊 !{command['name']}", color=discord.Color.blurple())
            embed.add_field(name="Nutzungen", value=f"{int(command['uses'] or 0):,}", inline=True)
            embed.add_field(name="Letzte Nutzung", value=command["last_used_at"] or "—", inline=True)
            embed.add_field(name="Letzte Änderungen", value=text[:1024], inline=False)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        rows = list_commands(interaction.guild_id)
        top = sorted(rows, key=lambda row: int(row["uses"] or 0), reverse=True)[:10]
        lines = [f"`!{row['name']}` — **{int(row['uses'] or 0):,}**x" for row in top]
        embed = discord.Embed(title="📊 Custom-Command Statistiken", description="\n".join(lines) or "Keine Commands.", color=discord.Color.blurple())
        embed.set_footer(text=f"{len(rows)} Commands insgesamt")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @custom.command(name="audit", description="Zeigt die letzten Änderungen")
    async def cmd_audit(self, interaction: discord.Interaction):
        if not await self._require_manager(interaction):
            return
        rows = list_audit(interaction.guild_id, limit=25)
        if not rows:
            return await interaction.response.send_message("📜 Noch keine Audit-Einträge.", ephemeral=True)
        lines = []
        for row in rows:
            command_id = row.get("command_id")
            command = get_command_by_id(command_id) if command_id else None
            label = f"`!{command['name']}`" if command else "(gelöscht/global)"
            lines.append(f"`{row['created_at']}` • **{row['action']}** • {label} • <@{row['actor_id']}>")
        embed = discord.Embed(title="📜 Custom-Command Audit", description="\n".join(lines)[:4000], color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------
    # Message routing
    # ------------------------------------------------------------------
    @commands.Cog.listener("on_message")
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or not message.content.startswith("!"):
            return

        payload = message.content[1:].strip()
        if not payload:
            return
        parts = payload.split()
        name = self._name(parts[0])
        args = parts[1:]

        # Built-in prefix commands always win. This prevents a custom command
        # from shadowing an existing moderation/system command.
        if self.bot.get_command(name) is not None:
            return

        command = get_invocation(message.guild.id, name)
        if not command or not command["enabled"]:
            return
        if not isinstance(message.author, discord.Member):
            return

        # Administrator bypass is intentional for emergency server management.
        if not message.author.guild_permissions.administrator:
            if not self._matches_role_policy(command["id"], message.author):
                return
            if not self._matches_channel_policy(command["id"], message.channel.id):
                return

        # Channel policy should still apply to normal admins when explicitly denied.
        if message.author.guild_permissions.administrator:
            rules = list_channel_rules(command["id"])
            deny_ids = {str(row["channel_id"]) for row in rules if row["rule"] == "deny"}
            if str(message.channel.id) in deny_ids:
                return

        cooldown = get_cooldown(command["id"])
        if cooldown:
            scope = cooldown["scope"]
            scope_key = {
                "user": f"{message.guild.id}:{message.author.id}",
                "channel": f"{message.guild.id}:{message.channel.id}",
                "guild": str(message.guild.id),
                "global": "global",
            }[scope]
            blocked, _ = check_and_touch_cooldown(command["id"], scope_key, int(cooldown["seconds"]))
            if blocked:
                return

        responses = list_responses(command["id"])
        response = self._weighted_response(responses)
        if not response:
            return

        try:
            await self._send_response(message, command, response, args)
        except (discord.Forbidden, discord.HTTPException):
            return
        except Exception:
            return

        record_use(command["id"], message.guild.id, message.author.id, message.channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(CustomCommands(bot))
