from __future__ import annotations

import discord
from discord import app_commands

from cogs.resourcepacks import ResourcePacksCog, _db_get


async def _better_paintings(interaction: discord.Interaction) -> None:
    """Direkte Auswahl für das vorbereitete Resource Pack Better Paintings."""
    pack = _db_get("Better Paintings")
    if not pack:
        await interaction.response.send_message(
            "🎨 **Better Paintings** ist noch nicht in der Bibliothek. "
            "Nutze `/resourcepacks add` und wähle als Namen **Better Paintings**.",
            ephemeral=True,
        )
        return

    version = pack.get("pack_version_min") or "?"
    if pack.get("pack_version_min") != pack.get("pack_version_max"):
        version += f" – {pack.get('pack_version_max')}"

    embed = discord.Embed(
        title="🎨 Better Paintings",
        description=pack.get("description") or "Better Paintings Resource Pack",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Pack-Version", value=version, inline=True)
    embed.add_field(name="Minecraft", value=pack.get("minecraft_version") or "nicht angegeben", inline=True)
    embed.add_field(name="Größe", value=f"{int(pack.get('file_size', 0)) // 1024} KB", inline=True)
    embed.add_field(name="Icon", value="✅ pack.png" if pack.get("has_icon") else "–", inline=True)
    embed.add_field(name="Kategorie", value=pack.get("category") or "Paintings", inline=True)
    embed.set_footer(text="Better Paintings · geprüfte Resource-Pack-Version")

    await interaction.response.send_message(embed=embed, ephemeral=True)


_command = app_commands.Command(
    name="better-paintings",
    description="Better Paintings Resource Pack auswählen",
    callback=_better_paintings,
)

if not any(command.name == _command.name for command in ResourcePacksCog.group.commands):
    ResourcePacksCog.group.add_command(_command)


async def setup(bot):
    return None
