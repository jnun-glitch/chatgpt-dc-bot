from __future__ import annotations

import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))


def test_automod_strikes_persist_across_reads(tmp_path, monkeypatch):
    import core.automod_strikes as strikes

    db_file = tmp_path / "strikes.db"
    monkeypatch.setattr(strikes, "DB_PATH", db_file)
    strikes.init_automod_strikes()
    strikes.save_strike_state(123, 456, 2, 1, "Spam")

    state = strikes.get_strike_state(123, 456)
    assert state["strikes"] == 2
    assert state["timeout_level"] == 1
    assert state["last_reason"] == "Spam"


def test_automod_strikes_can_reset(tmp_path, monkeypatch):
    import core.automod_strikes as strikes

    db_file = tmp_path / "strikes.db"
    monkeypatch.setattr(strikes, "DB_PATH", db_file)
    strikes.init_automod_strikes()
    strikes.save_strike_state(123, 456, 2, 1, "Spam")
    strikes.reset_strikes(123, 456)

    state = strikes.get_strike_state(123, 456)
    assert state["strikes"] == 0
    assert state["timeout_level"] == 0
