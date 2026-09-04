"""Isolierte SQLite-Schema-, Integritäts- und Persistenztests."""
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
    rows = temp_db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {row[0] for row in rows}
    assert {"tickets", "user_xp", "user_warns", "bad_word_log", "reminders", "polls", "afk_users", "counting", "tags", "birthdays"} <= names


def test_ticket_row_round_trip(temp_db):
    temp_db.execute(
        "INSERT INTO tickets(ticket_number, channel_id, user_id, username, betreff) VALUES (?, ?, ?, ?, ?)",
        (42, "100", "200", "Tester", "Testticket"),
    )
    temp_db.commit()
    row = temp_db.execute("SELECT ticket_number, username, betreff FROM tickets WHERE ticket_number=?", (42,)).fetchone()
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


def test_giveaway_entry_unique_constraint(temp_db):
    temp_db.execute(
        "INSERT INTO giveaways(guild_id, channel_id, message_id, prize, host_id, end_time) VALUES (?, ?, ?, ?, ?, datetime('now'))",
        ("1", "2", "3", "Prize", "4"),
    )
    giveaway_id = temp_db.execute("SELECT id FROM giveaways").fetchone()[0]
    temp_db.execute("INSERT INTO giveaway_entries(giveaway_id, user_id) VALUES (?, ?)", (giveaway_id, "55"))
    temp_db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        temp_db.execute("INSERT INTO giveaway_entries(giveaway_id, user_id) VALUES (?, ?)", (giveaway_id, "55"))


def test_primary_keys_prevent_duplicate_user_xp_rows(temp_db):
    temp_db.execute("INSERT INTO user_xp(user_id, guild_id, xp, level) VALUES (?, ?, ?, ?)", ("1", "2", 10, 2))
    temp_db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        temp_db.execute("INSERT INTO user_xp(user_id, guild_id, xp, level) VALUES (?, ?, ?, ?)", ("1", "2", 20, 3))


def test_primary_keys_prevent_duplicate_afk_rows(temp_db):
    temp_db.execute("INSERT INTO afk_users(guild_id, user_id, reason) VALUES (?, ?, ?)", ("1", "2", "pause"))
    temp_db.commit()
    with pytest.raises(sqlite3.IntegrityError):
        temp_db.execute("INSERT INTO afk_users(guild_id, user_id, reason) VALUES (?, ?, ?)", ("1", "2", "again"))


def test_indexes_exist(temp_db):
    rows = temp_db.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    names = {row[0] for row in rows}
    assert {"idx_tickets_channel", "idx_tickets_status", "idx_bad_word_log_user", "idx_giveaway_entries_giveaway"} <= names


def test_connection_uses_row_factory(temp_db):
    row = temp_db.execute("SELECT 1 AS value").fetchone()
    assert isinstance(row, sqlite3.Row)
    assert row["value"] == 1


def test_cached_connection_is_reused(temp_db):
    first = db_module.get_db()._conn
    second = db_module.get_db()._conn
    assert first is second


def test_database_survives_reopen(temp_db, tmp_path, monkeypatch):
    temp_db.execute("INSERT INTO tickets(ticket_number, channel_id, user_id, username, betreff) VALUES (?, ?, ?, ?, ?)", (7, "1", "2", "persist", "yes"))
    temp_db.commit()
    db_module._conn.close()
    db_module._conn = None
    reopened = db_module.get_db()
    row = reopened.execute("SELECT username FROM tickets WHERE ticket_number=7").fetchone()
    assert row[0] == "persist"


def test_guild_settings_upsert_shape(temp_db):
    temp_db.execute("INSERT INTO guild_settings(guild_id, key, value) VALUES (?, ?, ?)", ("1", "mode", "strict"))
    temp_db.commit()
    temp_db.execute("UPDATE guild_settings SET value=? WHERE guild_id=? AND key=?", ("relaxed", "1", "mode"))
    temp_db.commit()
    assert temp_db.execute("SELECT value FROM guild_settings WHERE guild_id=? AND key=?", ("1", "mode")).fetchone()[0] == "relaxed"
