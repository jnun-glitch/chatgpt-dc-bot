"""Zentrale Permission-Helfer im Stil eines modularen Discord-Bots."""
from __future__ import annotations

import discord


STAFF_ROLE_NAMES = {"admin", "administrator", "moderator", "mod", "support", "staff"}


def is_staff(member: discord.Member) -> bool:
    """True für Server-Admins oder bekannte Staff-Rollen."""
    if member.guild_permissions.administrator or member.guild_permissions.manage_guild:
        return True
    role_names = {role.name.casefold() for role in member.roles}
    return bool(role_names & STAFF_ROLE_NAMES)


def can_manage_bot(member: discord.Member) -> bool:
    """Permission für Bot-/Server-Konfiguration."""
    return member.guild_permissions.administrator or member.guild_permissions.manage_guild


def can_manage_channel(member: discord.Member) -> bool:
    return member.guild_permissions.manage_channels or is_staff(member)
