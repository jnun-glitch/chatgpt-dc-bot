"""Tests for USER > ROLE > DEFAULT custom response priority."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))


def _load_module(monkeypatch, payload):
    monkeypatch.setenv("CUSTOM_RESPONSE_OVERRIDES_JSON", json.dumps(payload))
    import core.custom_command_overrides as module
    return module


def test_user_wins_over_role_and_default(monkeypatch):
    module = _load_module(monkeypatch, {
        "default": {"hi": "default"},
        "roles": {"10": {"hi": "role"}},
        "users": {"123": {"hi": "user"}},
    })
    assert module.resolve_override("hi", 123, [10]) == ("user", "user")


def test_role_wins_over_default(monkeypatch):
    module = _load_module(monkeypatch, {
        "default": {"hi": "default"},
        "roles": {"10": {"hi": "role"}},
        "users": {},
    })
    assert module.resolve_override("hi", 999, [10]) == ("role", "role")


def test_default_is_fallback(monkeypatch):
    module = _load_module(monkeypatch, {
        "default": {"hi": "default"},
        "roles": {"10": {"other": "role"}},
        "users": {},
    })
    assert module.resolve_override("hi", 999, [10]) == ("default", "default")


def test_highest_matching_role_wins(monkeypatch):
    module = _load_module(monkeypatch, {
        "default": {"hi": "default"},
        "roles": {"10": {"hi": "lower"}, "20": {"hi": "higher"}},
        "users": {},
    })
    assert module.resolve_override("hi", 999, [20, 10]) == ("higher", "role")


def test_malformed_env_falls_back_safely(monkeypatch):
    monkeypatch.setenv("CUSTOM_RESPONSE_OVERRIDES_JSON", "not-json")
    import core.custom_command_overrides as module
    assert module.resolve_override("hi", 1, []) == (None, "none")
