"""Tests für Normalisierung, Bypass-Erkennung und False Positives."""
from core.badwords import _build_patterns, _normalize_text, find_bad_word


def test_normalize_unicode_and_case():
    assert _normalize_text("  IDIOT  ") == "idiot"


def test_normalize_leetspeak_variants():
    assert _normalize_text("1d10t") == "idiot"


def test_normalize_removes_separators():
    assert _normalize_text("i.d.i.o.t") == "idiot"


def test_build_patterns_handles_short_and_long_words():
    patterns = _build_patterns(["abc", "idiot"])
    assert len(patterns) == 2
    assert patterns[0].search("abc")
    assert patterns[1].search("xidioty")


def test_find_bad_word_detects_normal_word():
    assert find_bad_word("Das ist ein Idiot") == "idiot"


def test_find_bad_word_detects_case_insensitively():
    assert find_bad_word("IDIOT") == "idiot"


def test_find_bad_word_detects_separator_evasion():
    assert find_bad_word("i.d.i.o.t") == "idiot"


def test_find_bad_word_detects_leetspeak():
    assert find_bad_word("1d10t") == "idiot"


def test_find_bad_word_returns_none_for_clean_text():
    assert find_bad_word("Heute bauen wir ein Minecraft-Haus") is None


def test_find_bad_word_empty_text():
    assert find_bad_word("") is None


def test_find_bad_word_whitespace_text():
    assert find_bad_word(" \n\t ") is None


def test_find_bad_word_short_word_does_not_match_inside_long_word():
    assert find_bad_word("sexistisch") is None
