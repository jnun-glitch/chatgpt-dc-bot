from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from core import tickets


class _Avatar:
    url = 'https://cdn.example/avatar?a=1&b=2'


class _Author:
    display_name = '<Admin>'
    bot = False
    display_avatar = _Avatar()


class _Message:
    content = '<script>alert(1)</script> & "hello"'
    author = _Author()
    embeds = []
    attachments = []
    created_at = __import__('datetime').datetime(2026, 9, 10, 9, 0, 0)


class _Channel:
    id = 123
    name = 'ticket-test'
    topic = 'Ticket von user | <Betreff> | Kategorie: Support'

    async def history(self, **kwargs):
        yield _Message()


class _Guild:
    def get_channel(self, channel_id):
        return _Channel()


def test_ticket_transcript_escapes_html(tmp_path, monkeypatch):
    monkeypatch.setattr(tickets, 'TRANSCRIPTS_DIR', tmp_path)

    path = asyncio.run(tickets.save_ticket_transcript('123', _Guild()))
    html = Path(path).read_text(encoding='utf-8')

    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert '&lt;Betreff&gt;' in html
    assert '&amp;' in html
