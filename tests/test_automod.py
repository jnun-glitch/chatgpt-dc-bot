import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "_inner_bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from cogs.automod import (  # noqa: E402
    _clean_duplicate_text,
    _extract_urls,
    _is_suspicious_url,
    _url_host,
)


def test_extracts_regular_and_markdown_urls():
    urls = _extract_urls("hello https://example.com/test and [site](https://github.com/test)")
    assert "https://example.com/test" in urls
    assert "https://github.com/test" in urls


def test_url_host_normalizes_www():
    assert _url_host("https://www.GitHub.com/path") == "github.com"


def test_suspicious_url_detects_ip():
    assert _is_suspicious_url("http://192.0.2.10/login") is True


def test_suspicious_url_detects_punycode():
    assert _is_suspicious_url("https://xn--example-dk9c.com") is True


def test_duplicate_normalization():
    assert _clean_duplicate_text("  HELLO   world ") == "hello world"
