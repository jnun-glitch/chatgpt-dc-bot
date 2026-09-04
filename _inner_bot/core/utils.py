"""Gemeinsame Helper: Verified-Checks, Kanal-Restriktion, Level-Rollen."""
import discord
from core.config import VERIFY_CHANNEL_ID, VERIFIED_ROLE_NAME, LEVEL_ROLES
from core.db import get_level_roles
from core.logging import logger


def _is_allowed_channel(interaction: discord.Interaction) -> bool:
    """If VERIFY_CHANNEL_ID is set, restrict verify to that channel."""
    if VERIFY_CHANNEL_ID == 0:
        return True
    return interaction.channel_id == VERIFY_CHANNEL_ID


def _has_verified_role(interaction: discord.Interaction) -> bool:
    """Prüft ob der User die Verified-Rolle hat."""
    if not interaction.guild:
        return False
    role = discord.utils.get(interaction.guild.roles, name=VERIFIED_ROLE_NAME)
    if role is None:
        return False
    return role in interaction.user.roles


async def _require_verified(interaction: discord.Interaction) -> bool:
    """Sendet eine Fehlermeldung wenn User nicht verifiziert ist. True = OK."""
    if _has_verified_role(interaction):
        return True
    embed = discord.Embed(
        title='Nicht verifiziert',
        description='Du musst dich zuerst verifizieren. Nutze `/verify <code>` oder `/verify-link <name>`.',
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
    return False


async def _assign_level_role(member, guild, new_level):
    """Weist automatisch Level-Rollen zu (Server-Config, sonst Defaults)."""
    configured = get_level_roles(guild.id)
    if configured:
        for needed_level, role_id in sorted(configured.items()):
            if new_level >= needed_level:
                role = guild.get_role(int(role_id))
                if role and role not in member.roles:
                    try:
                        await member.add_roles(role, reason=f'Level {new_level} erreicht')
                    except Exception:
                        pass
        return
    for needed_level, role_name in sorted(LEVEL_ROLES.items()):
        if new_level >= needed_level:
            role = discord.utils.get(guild.roles, name=role_name)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f'Level {new_level} erreicht')
                except Exception:
                    pass
