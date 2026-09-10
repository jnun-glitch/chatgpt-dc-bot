"""Persistent AutoMod strike storage.

Keeps escalation state across restarts without storing message content.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.config import DB_PATH
import sqlite3


SCHEMA = """
CREATE TABLE IF NOT EXISTS automod_strikes (
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    strikes INTEGER NOT NULL DEFAULT 0,
    timeout_level INTEGER NOT NULL DEFAULT 0,
    last_reason TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(guild_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_automod_strikes_updated
    ON automod_strikes(updated_at);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_automod_strikes() -> None:
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def get_strike_state(guild_id: int, user_id: int) -> dict[str, Any]:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT guild_id,user_id,strikes,timeout_level,last_reason,updated_at "
            "FROM automod_strikes WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id)),
        ).fetchone()
        if not row:
            return {"guild_id": str(guild_id), "user_id": str(user_id), "strikes": 0, "timeout_level": 0, "last_reason": ""}
        return dict(row)
    finally:
        conn.close()


def record_strike(guild_id: int, user_id: int, reason: str) -> dict[str, Any]:
    state = get_strike_state(guild_id, user_id)
    strikes = int(state.get("strikes", 0)) + 1
    timeout_level = int(state.get("timeout_level", 0))
    if strikes >= 3:
        strikes = 0
        timeout_level += 1
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO automod_strikes(guild_id,user_id,strikes,timeout_level,last_reason,updated_at) "
            "VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET "
            "strikes=excluded.strikes,timeout_level=excluded.timeout_level,"
            "last_reason=excluded.last_reason,updated_at=excluded.updated_at",
            (str(guild_id), str(user_id), strikes, timeout_level, reason[:200], now),
        )
        conn.commit()
    finally:
        conn.close()
    state.update({"strikes": strikes, "timeout_level": timeout_level, "last_reason": reason[:200], "updated_at": now})
    return state


def reset_strikes(guild_id: int, user_id: int) -> None:
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM automod_strikes WHERE guild_id=? AND user_id=?",
            (str(guild_id), str(user_id)),
        )
        conn.commit()
    finally:
        conn.close()
