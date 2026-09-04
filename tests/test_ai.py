import sys
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "_inner_bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from cogs.ai import _ASK_LIMIT, _ASK_WINDOW, _ask_rate_limit  # noqa: E402
from core.ai import _safe_reply, _looks_like_error_text  # noqa: E402


def test_ai_reply_rejects_raw_json_and_tracebacks():
    assert _looks_like_error_text('{"error":"boom"}') is True
    assert _looks_like_error_text('Traceback (most recent call last): ...') is True
    assert _safe_reply('{"error":"boom"}', 'Fallback') == 'Fallback'


def test_ai_reply_rejects_json_arrays():
    assert _looks_like_error_text('[{"error":"boom"}]') is True


def test_ai_reply_rejects_known_provider_parse_errors():
    assert _looks_like_error_text('json parse failed while reading response') is True
    assert _looks_like_error_text('partial_parse_failed') is True


def test_ai_reply_rejects_unexpected_keyword_errors():
    assert _looks_like_error_text("unexpected keyword argument 'foo'") is True


def test_ai_reply_keeps_normal_text_and_discord_limit():
    text = 'Das ist eine normale Antwort.'
    assert _safe_reply(text, 'Fallback') == text
    assert len(_safe_reply('x' * 5000, 'Fallback')) <= 2000


def test_ai_reply_uses_fallback_for_empty_text():
    assert _safe_reply('', 'Fallback') == 'Fallback'
    assert _safe_reply('   ', 'Fallback') == 'Fallback'


def test_ai_reply_converts_non_string_values():
    assert _safe_reply(12345, 'Fallback') == '12345'


def test_ai_reply_keeps_markdown_text():
    text = '**Fertig**\n```python\nprint(1)\n```'
    assert _safe_reply(text, 'Fallback') == text


def test_ai_reply_keeps_exact_2000_character_response():
    text = 'x' * 2000
    assert _safe_reply(text, 'Fallback') == text
    assert len(_safe_reply(text, 'Fallback')) == 2000


def test_ai_reply_truncates_over_2000_characters():
    text = 'x' * 2001
    assert len(_safe_reply(text, 'Fallback')) == 2000


def test_ai_rate_limit_configuration_is_bounded():
    assert _ASK_LIMIT == 5
    assert _ASK_WINDOW == 60.0
    _ask_rate_limit.clear()
    _ask_rate_limit[(123, 456)] = deque([1.0])
    assert (999, 456) not in _ask_rate_limit
    _ask_rate_limit.clear()
