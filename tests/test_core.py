import sys
from pathlib import Path

import discord

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "_inner_bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from core.permissions import can_manage_bot, is_staff  # noqa: E402


def make_member(*, administrator=False, manage_guild=False, roles=()):
    member = object.__new__(discord.Member)
    member._roles = []
    member._state = None
    member.guild = None
    member.user = None
    member.id = 1
    member.guild_permissions = type(
        "PermissionsStub",
        (),
        {"administrator": administrator, "manage_guild": manage_guild, "manage_channels": False},
    )()
    member.roles = [type("RoleStub", (), {"name": role})() for role in roles]
    return member


def test_admin_can_manage_bot():
    assert can_manage_bot(make_member(administrator=True)) is True


def test_manage_guild_can_manage_bot():
    assert can_manage_bot(make_member(manage_guild=True)) is True


def test_support_role_is_staff():
    assert is_staff(make_member(roles=("Support",))) is True


def test_regular_member_is_not_staff():
    assert is_staff(make_member(roles=("Member",))) is False
