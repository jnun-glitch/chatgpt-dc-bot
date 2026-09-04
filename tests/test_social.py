import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "_inner_bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

import pytest

from cogs.social import latest_unseen, normalize_account  # noqa: E402


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
