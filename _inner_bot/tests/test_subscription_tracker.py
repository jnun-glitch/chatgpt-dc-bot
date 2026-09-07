from cogs.subscription_tracker import make_count_embed, should_announce, subscriber_delta


def test_subscriber_delta_increase_and_decrease():
    assert subscriber_delta(1000, 1012) == 12
    assert subscriber_delta(1012, 1000) == -12
    assert subscriber_delta(None, 1000) == 0


def test_first_observation_does_not_announce():
    assert should_announce(None, 1000) is False
    assert should_announce(1000, 1000) is False
    assert should_announce(1000, 1001) is True


def test_count_embed_contains_provider_and_change():
    embed = make_count_embed("youtube", "TestChannel", 1000, 1015)
    assert "YouTube" in embed.title
    assert "1,015" in embed.description
    assert "+15" in embed.description


def test_count_embed_handles_drop():
    embed = make_count_embed("twitch", "TestStreamer", 500, 492)
    assert "Twitch" in embed.title
    assert "-8" in embed.description
