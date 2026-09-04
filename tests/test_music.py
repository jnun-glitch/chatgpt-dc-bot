from types import SimpleNamespace

from cogs.music import MusicCog, _is_enabled


def make_voice(channel_id, connected=True):
    return SimpleNamespace(
        channel=SimpleNamespace(id=channel_id),
    ) if connected else SimpleNamespace(channel=None)


def make_player(channel_id, connected=True):
    return SimpleNamespace(
        vc=SimpleNamespace(
            channel=SimpleNamespace(id=channel_id),
            is_connected=lambda: connected,
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


def test_missing_player_is_denied():
    interaction = SimpleNamespace(user=SimpleNamespace(voice=make_voice(123)))
    assert MusicCog._same_voice_channel(interaction, None) is False


def test_disconnected_player_is_denied():
    interaction = SimpleNamespace(user=SimpleNamespace(voice=make_voice(123)))
    assert MusicCog._same_voice_channel(interaction, make_player(123, connected=False)) is False


def test_music_enabled_is_boolean():
    assert isinstance(_is_enabled(), bool)
