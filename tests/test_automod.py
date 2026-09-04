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


def test_extract_urls_handles_multiple_links():
    urls = _extract_urls("http://one.example https://two.example/a")
    assert urls == ["http://one.example", "https://two.example/a"]


def test_extract_urls_returns_empty_for_clean_text():
    assert _extract_urls("kein link hier") == []


def test_url_host_normalizes_www_and_case():
    assert _url_host("https://www.GitHub.com/path") == "github.com"


def test_url_host_includes_port_only_as_host_without_port():
    assert _url_host("https://example.com:443/path") == "example.com"


def test_suspicious_url_detects_ip():
    assert _is_suspicious_url("http://192.0.2.10/login") is True


def test_suspicious_url_detects_punycode():
    assert _is_suspicious_url("https://xn--example-dk9c.com") is True


def test_suspicious_url_detects_userinfo():
    assert _is_suspicious_url("https://user@example.com/login") is True


def test_suspicious_url_allows_normal_domain():
    assert _is_suspicious_url("https://github.com/project") is False


def test_suspicious_url_detects_suspicious_tld():
    assert _is_suspicious_url("https://example.zip") is True


def test_duplicate_normalization():
    assert _clean_duplicate_text("  HELLO   world ") == "hello world"


def test_duplicate_normalization_collapses_linebreaks():
    assert _clean_duplicate_text("Hello\n\t world") == "hello world"


def test_duplicate_normalization_is_case_insensitive():
    assert _clean_duplicate_text("MiXeD Case") == "mixed case"
