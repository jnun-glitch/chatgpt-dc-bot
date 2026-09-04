"""Isolierte SQLite-Schema- und Persistenztests."""
from __future__ import annotations

import sqlite3

import pytest

import core.db as db_module


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Ersetzt die globale DB-Verbindung durch eine temporäre Testdatenbank."""
    if db_module._conn is not None:
        try:
            db_module._conn.close()
        except Exception:
            pass
    monkeypatch.setattr(db_module, "_conn", None)
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.sqlite3")
    db_module.init_db()
    yield db_module.get_db()
    if db_module._conn is not None:
        db_module._conn.close()
    db_module._conn = None


def test_init_db_creates_core_tables(temp_db):
    rows = temp_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {row[0] for row in rows}
    assert {"tickets", "user_xp", "user_warns", "bad_word_log", "reminders"} <= names


def test_ticket_row_round_trip(temp_db):
    temp_db.execute(
        "INSERT INTO tickets(ticket_number, channel_id, user_id, username, betreff) VALUES (?, ?, ?, ?, ?)",
        (42, "100", "200", "Tester", "Testticket"),
    )
    temp_db.commit()
    row = temp_db.execute(
        "SELECT ticket_number, username, betreff FROM tickets WHERE ticket_number=?",
        (42,),
    ).fetchone()
    assert tuple(row) == (42, "Tester", "Testticket")


def test_duplicate_unique_fields_are_rejected(temp_db):
    temp_db.execute(
        "INSERT INTO reaction_roles(guild_id, channel_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?, ?)",
        ("1", "2", "3", "✅", "4"),
    )
    temp_db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        temp_db.execute(
            "INSERT INTO reaction_roles(guild_id, channel_id, message_id, emoji, role_id) VALUES (?, ?, ?, ?, ?)",
            ("1", "2", "3", "✅", "5"),
        )


def test_indexes_exist(temp_db):
    rows = temp_db.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    names = {row[0] for row in rows}
    assert "idx_tickets_channel" in names
    assert "idx_tickets_status" in names
    assert "idx_bad_word_log_user" in names


def test_connection_uses_row_factory(temp_db):
    row = temp_db.execute("SELECT 1 AS value").fetchone()
    assert isinstance(row, sqlite3.Row)
    assert row["value"] == 1
