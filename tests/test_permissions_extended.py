from types import SimpleNamespace

from core.permissions import can_manage_bot, can_manage_channel, is_staff


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


def test_staff_role_matching_is_case_insensitive():
    assert is_staff(make_member(roles=("MoDeRaToR",))) is True
    assert is_staff(make_member(roles=("SUPPORT",))) is True


def test_unknown_role_is_not_staff():
    assert is_staff(make_member(roles=("VIP",))) is False


def test_manage_channels_allows_channel_management():
    assert can_manage_channel(make_member(manage_channels=True)) is True


def test_manage_guild_does_not_grant_channel_check_indirectly():
    assert can_manage_channel(make_member(manage_guild=True)) is True


def test_regular_member_cannot_manage_bot():
    assert can_manage_bot(make_member()) is False
