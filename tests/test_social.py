import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "_inner_bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

import pytest

from cogs.social import (
    latest_unseen,
    make_twitch_embed,
    make_youtube_embed,
    normalize_account,
    twitch_should_notify,
    youtube_initial_marker,
    youtube_kind,
    youtube_thumbnail,
)


def test_normalize_youtube_channel_url():
    assert normalize_account("youtube", "https://www.youtube.com/channel/UC1234567890123456789012") == "UC1234567890123456789012"


def test_normalize_youtube_handle():
    assert normalize_account("youtube", "@CreatorName") == "CreatorName"


def test_normalize_youtube_trailing_slash():
    assert normalize_account("youtube", "https://www.youtube.com/@CreatorName/") == "CreatorName"


def test_normalize_twitch_handle_and_url():
    assert normalize_account("twitch", "https://twitch.tv/TestStreamer/") == "teststreamer"
    assert normalize_account("twitch", "@TestStreamer") == "teststreamer"


def test_normalize_x_handle_and_url():
    assert normalize_account("x", "https://x.com/TestUser/") == "testuser"
    assert normalize_account("x", "@TestUser") == "testuser"


def test_normalize_rejects_unknown_provider():
    with pytest.raises(ValueError):
        normalize_account("unknown", "creator")


def test_normalize_rejects_empty_account():
    with pytest.raises(ValueError):
        normalize_account("twitch", "   ")


def test_normalize_trims_whitespace():
    assert normalize_account("twitch", "  @TestStreamer  ") == "teststreamer"


def test_latest_unseen_sorts_oldest_first():
    items = [
        {"id": "3", "published": "2026-01-03"},
        {"id": "1", "published": "2026-01-01"},
        {"id": "2", "published": "2026-01-02"},
    ]
    assert [item["id"] for item in latest_unseen(items, "1")] == ["2", "3"]


def test_latest_unseen_drops_empty_ids():
    items = [{"id": "", "published": "2026-01-01"}, {"id": "2", "published": "2026-01-02"}]
    assert [item["id"] for item in latest_unseen(items, None)] == ["2"]


def test_latest_unseen_accepts_first_poll():
    items = [{"id": "10", "published": "2026-01-01"}, {"id": "11", "published": "2026-01-02"}]
    assert [item["id"] for item in latest_unseen(items, None)] == ["10", "11"]


def test_latest_unseen_does_not_repost_items_before_seen_marker():
    items = [
        {"id": "10", "published": "2026-01-01"},
        {"id": "11", "published": "2026-01-02"},
        {"id": "12", "published": "2026-01-03"},
    ]
    assert [item["id"] for item in latest_unseen(items, "11")] == ["12"]


def test_latest_unseen_handles_missing_dates():
    items = [{"id": "2"}, {"id": "1", "published": "2026-01-01"}]
    assert [item["id"] for item in latest_unseen(items, None)] == ["1", "2"]


def test_latest_unseen_collapses_duplicate_ids():
    items = [
        {"id": "1", "published": "2026-01-01"},
        {"id": "1", "published": "2026-01-02"},
        {"id": "2", "published": "2026-01-03"},
    ]
    assert [item["id"] for item in latest_unseen(items, None)] == ["1", "2"]


def test_twitch_notifies_only_for_new_stream_session():
    assert twitch_should_notify(None, "123") is True
    assert twitch_should_notify("offline", "123") is True
    assert twitch_should_notify("123", "123") is False
    assert twitch_should_notify("456", "123") is True
    assert twitch_should_notify("123", "") is False


def test_youtube_kind_distinguishes_live_and_video():
    assert youtube_kind({"is_live_content": True, "is_live_now": True}) == "live"
    assert youtube_kind({"is_live_content": True, "is_live_now": False}) == "video"
    assert youtube_kind({"is_live_content": False, "is_live_now": False}) == "video"


def test_youtube_initial_marker_picks_newest():
    items = [
        {"id": "old", "published": "2026-01-01"},
        {"id": "new", "published": "2026-01-03"},
        {"id": "mid", "published": "2026-01-02"},
    ]
    assert youtube_initial_marker(items) == "new"


def test_youtube_initial_marker_empty_feed():
    assert youtube_initial_marker([]) is None


def test_youtube_thumbnail_uses_video_id():
    assert youtube_thumbnail("abc123") == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"


def test_youtube_video_embed_has_thumbnail_and_link():
    embed = make_youtube_embed({
        "id": "abc123",
        "title": "Testvideo",
        "url": "https://youtu.be/abc123",
        "creator": "Creator",
    })
    assert embed.title == "📺 Neues YouTube-Video"
    assert embed.url == "https://youtu.be/abc123"
    assert embed.image.url.endswith("/abc123/hqdefault.jpg")


def test_youtube_live_embed_has_live_title():
    embed = make_youtube_embed({
        "id": "abc123",
        "title": "Livestream",
        "url": "https://youtu.be/abc123",
        "creator": "Creator",
    }, kind="live")
    assert embed.title == "🔴 YouTube ist LIVE!"


def test_twitch_embed_contains_stream_details():
    embed = make_twitch_embed({
        "title": "Minecraft",
        "game_name": "Minecraft",
        "viewer_count": 42,
        "user_name": "Streamer",
    }, "streamer")
    assert embed.title == "🔴 Twitch ist LIVE!"
    assert "Minecraft" in embed.description
    assert embed.url == "https://twitch.tv/streamer"
