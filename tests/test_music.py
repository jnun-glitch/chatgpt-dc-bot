from types import SimpleNamespace

from cogs.music import MusicCog


def make_voice(channel_id):
    return SimpleNamespace(channel=SimpleNamespace(id=channel_id))


def make_player(channel_id):
    return SimpleNamespace(
        vc=SimpleNamespace(
            channel=SimpleNamespace(id=channel_id),
            is_connected=lambda: True,
        )
    )


def test_same_voice_channel_is_allowed():
    interaction = SimpleNamespace(user=SimpleNamespace(voice=make_voice(123)))
    assert MusicCog._same_voice_channel(interaction, make_player(123)) is True


def test_other_voice_channel_is_denied():
    interaction = SimpleNamespace(user=SimpleNamespace(voice=make_voice(456)))
    assert MusicCog._same_voice_channel(interaction, make_player(123)) is False


def test_user_not_in_voice_is_denied():
    interaction = SimpleNamespace(user=SimpleNamespace(voice=None))
    assert MusicCog._same_voice_channel(interaction, make_player(123)) is False
