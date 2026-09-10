from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from cogs.social import latest_unseen, twitch_should_notify
from cogs.music import MusicPlayer


def test_twitch_notification_deduplicates_stream_id():
    assert twitch_should_notify(None, "stream-1") is True
    assert twitch_should_notify("stream-1", "stream-1") is False
    assert twitch_should_notify("stream-1", "stream-2") is True


def test_latest_unseen_returns_only_items_after_marker():
    items = [
        {"id": "2", "published": "2026-09-10T10:00:00Z"},
        {"id": "1", "published": "2026-09-10T09:00:00Z"},
        {"id": "3", "published": "2026-09-10T11:00:00Z"},
        {"id": "3", "published": "2026-09-10T11:00:00Z"},
    ]
    assert [item["id"] for item in latest_unseen(items, "1")] == ["2", "3"]


def test_music_player_queue_advances():
    class FakeVoice:
        def is_connected(self): return True
        def is_playing(self): return False
        def is_paused(self): return False

    async def scenario():
        player = MusicPlayer(1, FakeVoice(), asyncio.get_running_loop())
        player.current = {"title": "one"}
        player.queue.append({"title": "two"})
        player.play_current = lambda: None
        await player.advance()
        assert player.current["title"] == "two"
        assert player.queue == []

    asyncio.run(scenario())
