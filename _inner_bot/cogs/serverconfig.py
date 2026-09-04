"""Per-server configuration with centralized permission checks."""
import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from core.db import (
    add_suggestion,
    get_automod_config,
    get_guild_config,
    get_rules_gate,
    set_automod_config,
    set_guild_config,
    set_rules_gate,
)
from core.images import make_welcome_card
from core.permissions import can_manage_bot


RESETTABLE = {
    "welcome_channel_id": "Willkommens-Channel",
    "join_role_id": "Auto-Rolle",
    "ticket_category_id": "Ticket-Kategorie",
}


class ServerConfigCog(commands.Cog):
    """Server settings. Configuration changes are admin/manage-guild only."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @staticmethod
    def _require_manager(interaction: discord.Interaction) -> bool:
        return bool(interaction.guild and isinstance(interaction.user, discord.Member) and can_manage_bot(interaction.user))

    @app_commands.command(name="config", description="Zeigt die aktuelle Server-Konfiguration")
    async def cmd_config_show(self, interaction: discord.Interaction):
        cfg = get_guild_config(interaction.guild_id)

        def ch(key):
            value = cfg.get(key)
            return f"<#{value}>" if value else "Nicht gesetzt"

        def rl(key):
            value = cfg.get(key)
            return f"<@&{value}>" if value else "Nicht gesetzt"

        embed = discord.Embed(title="⚙️ Server-Konfiguration", color=discord.Color.blurple())
        embed.add_field(name="Willkommen", value=f"Channel: {ch('welcome_channel_id')}\nAuto-Rolle: {rl('join_role_id')}", inline=False)
        embed.add_field(name="Tickets", value=f"Kategorie: {ch('ticket_category_id')}", inline=False)
        gate = get_rules_gate(interaction.guild_id)
        embed.add_field(name="Verification", value=f"Rules Gate: {'Aktiviert' if gate.get('enabled') else 'Deaktiviert'}\nRules-Channel: {f'<#{gate.get("rules_channel_id")}>' if gate.get('rules_channel_id') else 'Nicht gesetzt'}", inline=False)
        automod = get_automod_config(interaction.guild_id)
        embed.add_field(
            name="AutoMod",
            value=(
                f"Spam: {'AN' if automod.get('spam', {}).get('enabled') else 'AUS'}\n"
                f"Links: {'AN' if automod.get('links', {}).get('enabled') else 'AUS'}\n"
                f"Bad Words: {'AN' if automod.get('badwords', {}).get('enabled') else 'AUS'}"
            ),
            inline=False,
        )
        embed.add_field(name="Warnungen", value=f"Timeout ab: {cfg.get('warn_timeout_at') or 3}\nKick ab: {cfg.get('warn_kick_at') or 5}\nTimeout: {cfg.get('warn_timeout_minutes') or 60} Min.", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="config-set", description="Setzt eine Server-Einstellung")
    @app_commands.describe(option="Welche Einstellung?", wert="Wert (Kanal/Rolle mention oder ID)")
    @app_commands.choices(option=[
        app_commands.Choice(name="Willkommens-Channel", value="welcome_channel_id"),
        app_commands.Choice(name="Auto-Rolle", value="join_role_id"),
        app_commands.Choice(name="Ticket-Kategorie", value="ticket_category_id"),
        app_commands.Choice(name="Rules-Channel", value="rules_channel_id"),
        app_commands.Choice(name="Rules Gate AN", value="rules_gate_enabled_1"),
        app_commands.Choice(name="Rules Gate AUS", value="rules_gate_enabled_0"),
        app_commands.Choice(name="Spam-Schutz AN", value="automod_spam_1"),
        app_commands.Choice(name="Spam-Schutz AUS", value="automod_spam_0"),
        app_commands.Choice(name="Link-Schutz AN", value="automod_links_1"),
        app_commands.Choice(name="Link-Schutz AUS", value="automod_links_0"),
        app_commands.Choice(name="Bad-Word-Filter AN", value="automod_badwords_1"),
        app_commands.Choice(name="Bad-Word-Filter AUS", value="automod_badwords_0"),
        app_commands.Choice(name="Warn-Timeout ab", value="warn_timeout_at"),
        app_commands.Choice(name="Warn-Kick ab", value="warn_kick_at"),
        app_commands.Choice(name="Warn-Timeout Dauer", value="warn_timeout_minutes"),
    ])
    async def cmd_config_set(self, interaction: discord.Interaction, option: app_commands.Choice[str], wert: str | None = None):
        if not self._require_manager(interaction):
            await interaction.response.send_message("⛔ Nur Administratoren bzw. Benutzer mit Server-Verwaltung dürfen die Konfiguration ändern.", ephemeral=True)
            return

        value = option.value
        if value.endswith("_1") or value.endswith("_0"):
            key = value.rsplit("_", 1)[0]
            enabled = value.endswith("_1")
            if key == "rules_gate_enabled":
                gate = get_rules_gate(interaction.guild_id)
                ok = set_rules_gate(interaction.guild_id, enabled=enabled, rules_channel_id=gate.get("rules_channel_id"), rules_message_id=gate.get("rules_message_id"), member_role_id=gate.get("member_role_id"))
            elif key.startswith("automod_"):
                filter_name = {"automod_spam": "spam", "automod_links": "links", "automod_badwords": "badwords"}[key]
                existing = get_automod_config(interaction.guild_id).get(filter_name, {})
                ok = set_automod_config(interaction.guild_id, filter_name, enabled=enabled, limit_value=existing.get("limit_value", 0))
            else:
                ok = False
            await interaction.response.send_message("✅ Einstellung aktualisiert." if ok else "❌ Speichern fehlgeschlagen.", ephemeral=True)
            return

        if value in {"warn_timeout_at", "warn_kick_at", "warn_timeout_minutes"}:
            try:
                number = int(wert or "")
                if number < 1:
                    raise ValueError
            except ValueError:
                await interaction.response.send_message("❌ Bitte eine positive ganze Zahl angeben.", ephemeral=True)
                return
            if value == "warn_kick_at":
                current_timeout = int(get_guild_config(interaction.guild_id).get("warn_timeout_at") or 3)
                if number <= current_timeout:
                    await interaction.response.send_message("❌ Kick-Schwelle muss größer als die Timeout-Schwelle sein.", ephemeral=True)
                    return
            ok = set_guild_config(interaction.guild_id, value, str(number))
            await interaction.response.send_message("✅ Einstellung gespeichert." if ok else "❌ Speichern fehlgeschlagen.", ephemeral=True)
            return

        if not wert:
            await interaction.response.send_message("❌ Bitte einen Kanal-/Rollen-Mention oder eine ID angeben.", ephemeral=True)
            return
        if wert.startswith("<#") and wert.endswith(">"):
            target_id = wert[2:-1]
        elif wert.startswith("<@&") and wert.endswith(">"):
            target_id = wert[3:-1]
        else:
            try:
                target_id = str(int(wert))
            except ValueError:
                await interaction.response.send_message("❌ Ungültige ID.", ephemeral=True)
                return

        if value == "rules_channel_id":
            gate = get_rules_gate(interaction.guild_id)
            ok = set_rules_gate(interaction.guild_id, enabled=bool(gate.get("enabled")), rules_channel_id=target_id, rules_message_id=gate.get("rules_message_id"), member_role_id=gate.get("member_role_id"))
        else:
            ok = set_guild_config(interaction.guild_id, value, target_id)
        await interaction.response.send_message("✅ Einstellung gespeichert." if ok else "❌ Speichern fehlgeschlagen.", ephemeral=True)

    @app_commands.command(name="config-reset", description="Setzt eine Konfiguration zurück")
    @app_commands.describe(option="Welche Einstellung zurücksetzen?")
    @app_commands.choices(option=[app_commands.Choice(name=label, value=key) for key, label in RESETTABLE.items()])
    async def cmd_config_reset(self, interaction: discord.Interaction, option: app_commands.Choice[str]):
        if not self._require_manager(interaction):
            await interaction.response.send_message("⛔ Keine Berechtigung.", ephemeral=True)
            return
        value = RESETTABLE.get(option.value)
        if not value:
            await interaction.response.send_message("❌ Ungültige Einstellung.", ephemeral=True)
            return
        ok = set_guild_config(interaction.guild_id, option.value, None)
        await interaction.response.send_message(f"✅ **{value}** wurde zurückgesetzt." if ok else "❌ Zurücksetzen fehlgeschlagen.", ephemeral=True)

    @app_commands.command(name="suggestion", description="Schlage eine Verbesserung vor")
    @app_commands.describe(idee="Deine Idee")
    async def cmd_suggest(self, interaction: discord.Interaction, idee: str):
        if len(idee) > 1000:
            await interaction.response.send_message("Max. 1000 Zeichen.", ephemeral=True)
            return
        if add_suggestion(interaction.guild_id, interaction.user.id, idee):
            embed = discord.Embed(title="💡 Vorschlag", description=idee, color=discord.Color.gold())
            embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("❌ Fehler beim Speichern.", ephemeral=True)

    @app_commands.command(name="welcome-preview", description="Zeigt eine Vorschau der Willkommens-Karte")
    async def cmd_welcome_preview(self, interaction: discord.Interaction):
        card = await asyncio.to_thread(make_welcome_card, interaction.user, interaction.guild.member_count, interaction.guild.name)
        if card:
            await interaction.response.send_message(file=discord.File(card, filename="welcome_preview.png"), ephemeral=True)
        else:
            await interaction.response.send_message("Bild-Generierung nicht verfügbar.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ServerConfigCog(bot))
