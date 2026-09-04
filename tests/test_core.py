import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "_inner_bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from core.permissions import can_manage_bot, can_manage_channel, is_staff  # noqa: E402


def make_member(*, administrator=False, manage_guild=False, manage_channels=False, roles=()):
    perms = SimpleNamespace(
        administrator=administrator,
        manage_guild=manage_guild,
        manage_channels=manage_channels,
    )
    return SimpleNamespace(
        id=1,
        guild_permissions=perms,
        roles=[SimpleNamespace(name=role) for role in roles],
    )


def test_admin_can_manage_bot():
    assert can_manage_bot(make_member(administrator=True)) is True


def test_manage_guild_can_manage_bot():
    assert can_manage_bot(make_member(manage_guild=True)) is True


def test_regular_member_cannot_manage_bot():
    assert can_manage_bot(make_member()) is False


def test_support_role_is_staff():
    assert is_staff(make_member(roles=("Support",))) is True


def test_moderator_role_is_staff_case_insensitive():
    assert is_staff(make_member(roles=("MoDeRaToR",))) is True


def test_manage_guild_marks_member_as_staff():
    assert is_staff(make_member(manage_guild=True)) is True


def test_regular_member_is_not_staff():
    assert is_staff(make_member(roles=("Member",))) is False


def test_channel_manager_permission_allows_manage_channels():
    assert can_manage_channel(make_member(manage_channels=True)) is True


def test_staff_can_manage_channel_without_manage_channels():
    assert can_manage_channel(make_member(roles=("Moderator",))) is True


def test_regular_member_cannot_manage_channel():
    assert can_manage_channel(make_member(roles=("Member",))) is False
