"""Offline simulations for creator notification inputs.

These tests deliberately do NOT contact Twitch, YouTube, X, or Discord.
They feed fake events into the same helper logic used by the alert cog and
verify that the bot can build the expected alert payloads without credentials.
"""

from cogs.social import (
    make_twitch_embed,
    make_youtube_embed,
    latest_unseen,
    twitch_should_notify,
)


def test_fake_twitch_goes_live_once():
    fake_stream = {
        "id": "TEST-TWITCH-001",
        "title": "Test ist LIVE!",
        "game_name": "Test Game",
        "viewer_count": 123,
        "user_name": "Test",
        "thumbnail_url": "https://example.invalid/twitch/{width}x{height}.jpg",
    }

    embed = make_twitch_embed(fake_stream, "Test")

    assert embed.title == "🔴 Twitch ist LIVE!"
    assert "Test ist LIVE!" in (embed.description or "")
    assert twitch_should_notify(None, "TEST-TWITCH-001") is True
    assert twitch_should_notify("TEST-TWITCH-001", "TEST-TWITCH-001") is False


def test_fake_youtube_live_is_seen_as_new_item():
    fake_video = {
        "id": "TEST-YOUTUBE-001",
        "title": "Test ist LIVE!",
        "url": "https://youtu.be/TEST-YOUTUBE-001",
        "creator": "Test",
    }

    embed = make_youtube_embed(fake_video, kind="live")
    unseen = latest_unseen([fake_video], None)

    assert embed.title == "🔴 YouTube ist LIVE!"
    assert len(unseen) == 1
    assert unseen[0]["id"] == "TEST-YOUTUBE-001"


def test_fake_x_post_is_detected_as_unseen():
    old = {"id": "100", "created_at": "2026-09-05T10:00:00Z", "text": "old"}
    new = {"id": "101", "created_at": "2026-09-05T10:01:00Z", "text": "Test ist live!"}

    unseen = latest_unseen([old, new], "100")

    assert [item["id"] for item in unseen] == ["101"]
