"""Persistent storage for ScratchAI Custom Commands.

This module intentionally owns the custom-command schema so the existing
core.db module stays stable. All records are guild-scoped and all SQL uses
parameters. The schema is normalized so future features can be added without
turning one command row into a giant JSON blob.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from core.config import DB_PATH


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS custom_commands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    delete_trigger INTEGER NOT NULL DEFAULT 0,
    delete_reply_after INTEGER,
    allow_user_mentions INTEGER NOT NULL DEFAULT 1,
    allow_role_mentions INTEGER NOT NULL DEFAULT 0,
    allow_everyone_mentions INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TEXT,
    uses INTEGER NOT NULL DEFAULT 0,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS custom_command_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id INTEGER NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    embed_json TEXT,
    weight INTEGER NOT NULL DEFAULT 1 CHECK(weight > 0),
    position INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(command_id) REFERENCES custom_commands(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS custom_command_aliases (
    command_id INTEGER NOT NULL,
    alias TEXT NOT NULL,
    PRIMARY KEY(command_id, alias),
    FOREIGN KEY(command_id) REFERENCES custom_commands(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS custom_command_role_rules (
    command_id INTEGER NOT NULL,
    role_id TEXT NOT NULL,
    rule TEXT NOT NULL CHECK(rule IN ('allow', 'deny')),
    PRIMARY KEY(command_id, role_id, rule),
    FOREIGN KEY(command_id) REFERENCES custom_commands(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS custom_command_channel_rules (
    command_id INTEGER NOT NULL,
    channel_id TEXT NOT NULL,
    rule TEXT NOT NULL CHECK(rule IN ('allow', 'deny')),
    PRIMARY KEY(command_id, channel_id, rule),
    FOREIGN KEY(command_id) REFERENCES custom_commands(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS custom_command_cooldowns (
    command_id INTEGER PRIMARY KEY,
    scope TEXT NOT NULL CHECK(scope IN ('user', 'channel', 'guild', 'global')),
    seconds INTEGER NOT NULL CHECK(seconds > 0),
    FOREIGN KEY(command_id) REFERENCES custom_commands(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS custom_command_cooldown_hits (
    command_id INTEGER NOT NULL,
    scope_key TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    PRIMARY KEY(command_id, scope_key),
    FOREIGN KEY(command_id) REFERENCES custom_commands(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS custom_command_manager_roles (
    guild_id TEXT NOT NULL,
    role_id TEXT NOT NULL,
    PRIMARY KEY(guild_id, role_id)
);

CREATE TABLE IF NOT EXISTS custom_command_usage (
    command_id INTEGER NOT NULL,
    guild_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(command_id, user_id, channel_id),
    FOREIGN KEY(command_id) REFERENCES custom_commands(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS custom_command_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL,
    command_id INTEGER,
    action TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(command_id) REFERENCES custom_commands(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_cc_guild_name
    ON custom_commands(guild_id, name);
CREATE INDEX IF NOT EXISTS idx_cc_role_rules
    ON custom_command_role_rules(command_id, rule, role_id);
CREATE INDEX IF NOT EXISTS idx_cc_channel_rules
    ON custom_command_channel_rules(command_id, rule, channel_id);
CREATE INDEX IF NOT EXISTS idx_cc_aliases_alias
    ON custom_command_aliases(alias, command_id);
CREATE INDEX IF NOT EXISTS idx_cc_usage_guild
    ON custom_command_usage(guild_id, command_id, uses DESC);
CREATE INDEX IF NOT EXISTS idx_cc_audit_guild
    ON custom_command_audit(guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_cc_cooldown_hits
    ON custom_command_cooldown_hits(command_id, last_used_at);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_custom_commands_db() -> None:
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _fetchone(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    conn = _connect()
    try:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _fetchall(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def create_command(guild_id: int, name: str, description: str, created_by: int) -> int:
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO custom_commands(guild_id,name,description,created_by) VALUES(?,?,?,?)",
            (str(guild_id), name, description, str(created_by)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def get_command(guild_id: int, name: str) -> dict[str, Any] | None:
    return _fetchone(
        """SELECT c.* FROM custom_commands c
           WHERE c.guild_id = ? AND c.name = ?
           LIMIT 1""",
        (str(guild_id), name.casefold()),
    )


def get_command_by_id(command_id: int) -> dict[str, Any] | None:
    return _fetchone("SELECT * FROM custom_commands WHERE id = ?", (int(command_id),))


def list_commands(guild_id: int, include_disabled: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM custom_commands WHERE guild_id = ?"
    params: list[Any] = [str(guild_id)]
    if not include_disabled:
        sql += " AND enabled = 1"
    sql += " ORDER BY name COLLATE NOCASE"
    return _fetchall(sql, tuple(params))


def search_commands(guild_id: int, query: str, limit: int = 25) -> list[dict[str, Any]]:
    q = f"%{query.casefold()}%"
    return _fetchall(
        """SELECT * FROM custom_commands
           WHERE guild_id = ? AND (name LIKE ? COLLATE NOCASE OR description LIKE ? COLLATE NOCASE)
           ORDER BY CASE WHEN name = ? THEN 0 WHEN name LIKE ? THEN 1 ELSE 2 END, name COLLATE NOCASE
           LIMIT ?""",
        (str(guild_id), q, q, query.casefold(), f"{query.casefold()}%", int(limit)),
    )


def get_invocation(guild_id: int, name: str) -> dict[str, Any] | None:
    return _fetchone(
        """SELECT c.* FROM custom_commands c
           WHERE c.guild_id = ? AND c.enabled = 1 AND c.name = ?
           UNION ALL
           SELECT c.* FROM custom_commands c
           INNER JOIN custom_command_aliases a ON a.command_id = c.id
           WHERE c.guild_id = ? AND c.enabled = 1 AND a.alias = ?
           LIMIT 1""",
        (str(guild_id), name.casefold(), str(guild_id), name.casefold()),
    )


def update_command(guild_id: int, name: str, updated_by: int, **fields: Any) -> bool:
    allowed = {
        "description", "enabled", "delete_trigger", "delete_reply_after",
        "allow_user_mentions", "allow_role_mentions", "allow_everyone_mentions"
    }
    updates = [(key, value) for key, value in fields.items() if key in allowed]
    if not updates:
        return False
    assignments = ", ".join(f"{key} = ?" for key, _ in updates)
    values = [value for _, value in updates]
    values.extend([str(updated_by), str(guild_id), name.casefold()])
    conn = _connect()
    try:
        cur = conn.execute(
            f"UPDATE custom_commands SET {assignments}, updated_by = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE guild_id = ? AND name = ?",
            tuple(values),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_command(guild_id: int, name: str) -> dict[str, Any] | None:
    command = get_command(guild_id, name)
    if not command:
        return None
    conn = _connect()
    try:
        conn.execute("DELETE FROM custom_commands WHERE id = ?", (command["id"],))
        conn.commit()
        return command
    finally:
        conn.close()


def add_response(command_id: int, content: str, embed_json: str | None = None, weight: int = 1) -> int:
    conn = _connect()
    try:
        position = conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM custom_command_responses WHERE command_id = ?",
            (int(command_id),),
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO custom_command_responses(command_id,content,embed_json,weight,position) VALUES(?,?,?,?,?)",
            (int(command_id), content, embed_json, max(1, int(weight)), int(position)),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def list_responses(command_id: int, enabled_only: bool = True) -> list[dict[str, Any]]:
    sql = "SELECT * FROM custom_command_responses WHERE command_id = ?"
    params: list[Any] = [int(command_id)]
    if enabled_only:
        sql += " AND enabled = 1"
    sql += " ORDER BY position, id"
    return _fetchall(sql, tuple(params))


def delete_response(command_id: int, response_id: int) -> bool:
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM custom_command_responses WHERE command_id = ? AND id = ?",
            (int(command_id), int(response_id)),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def set_alias(command_id: int, alias: str) -> bool:
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO custom_command_aliases(command_id,alias) VALUES(?,?)",
            (int(command_id), alias.casefold()),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def remove_alias(command_id: int, alias: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM custom_command_aliases WHERE command_id = ? AND alias = ?",
            (int(command_id), alias.casefold()),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_aliases(command_id: int) -> list[str]:
    rows = _fetchall(
        "SELECT alias FROM custom_command_aliases WHERE command_id = ? ORDER BY alias",
        (int(command_id),),
    )
    return [row["alias"] for row in rows]


def set_role_rule(command_id: int, role_id: int, rule: str) -> None:
    if rule not in {"allow", "deny"}:
        raise ValueError("rule must be allow or deny")
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO custom_command_role_rules(command_id,role_id,rule) VALUES(?,?,?)",
            (int(command_id), str(role_id), rule),
        )
        conn.commit()
    finally:
        conn.close()


def remove_role_rule(command_id: int, role_id: int, rule: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM custom_command_role_rules WHERE command_id = ? AND role_id = ? AND rule = ?",
            (int(command_id), str(role_id), rule),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_role_rules(command_id: int) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT role_id, rule FROM custom_command_role_rules WHERE command_id = ? ORDER BY rule, role_id",
        (int(command_id),),
    )


def set_channel_rule(command_id: int, channel_id: int, rule: str) -> None:
    if rule not in {"allow", "deny"}:
        raise ValueError("rule must be allow or deny")
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO custom_command_channel_rules(command_id,channel_id,rule) VALUES(?,?,?)",
            (int(command_id), str(channel_id), rule),
        )
        conn.commit()
    finally:
        conn.close()


def remove_channel_rule(command_id: int, channel_id: int, rule: str) -> bool:
    conn = _connect()
    try:
        cur = conn.execute(
            "DELETE FROM custom_command_channel_rules WHERE command_id = ? AND channel_id = ? AND rule = ?",
            (int(command_id), str(channel_id), rule),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_channel_rules(command_id: int) -> list[dict[str, Any]]:
    return _fetchall(
        "SELECT channel_id, rule FROM custom_command_channel_rules WHERE command_id = ? ORDER BY rule, channel_id",
        (int(command_id),),
    )


def set_cooldown(command_id: int, scope: str, seconds: int) -> None:
    if scope not in {"user", "channel", "guild", "global"}:
        raise ValueError("invalid cooldown scope")
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO custom_command_cooldowns(command_id,scope,seconds) VALUES(?,?,?) "
            "ON CONFLICT(command_id) DO UPDATE SET scope=excluded.scope, seconds=excluded.seconds",
            (int(command_id), scope, int(seconds)),
        )
        conn.commit()
    finally:
        conn.close()


def get_cooldown(command_id: int) -> dict[str, Any] | None:
    return _fetchone("SELECT * FROM custom_command_cooldowns WHERE command_id = ?", (int(command_id),))


def check_and_touch_cooldown(command_id: int, scope_key: str, seconds: int) -> tuple[bool, int]:
    """Atomic-ish cooldown check using one transaction.

    Returns (blocked, remaining_seconds). The caller should run this only after
    permission checks, so denied users do not consume cooldowns.
    """
    now = datetime.now(timezone.utc)
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT last_used_at FROM custom_command_cooldown_hits WHERE command_id = ? AND scope_key = ?",
            (int(command_id), scope_key),
        ).fetchone()
        if row:
            try:
                last = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
            except ValueError:
                last = now - timedelta(days=1)
            remaining = int(seconds - (now - last).total_seconds())
            if remaining > 0:
                conn.rollback()
                return True, remaining
        conn.execute(
            "INSERT INTO custom_command_cooldown_hits(command_id,scope_key,last_used_at) VALUES(?,?,?) "
            "ON CONFLICT(command_id,scope_key) DO UPDATE SET last_used_at=excluded.last_used_at",
            (int(command_id), scope_key, now.isoformat()),
        )
        conn.commit()
        return False, 0
    finally:
        conn.close()


def set_manager_role(guild_id: int, role_id: int, enabled: bool = True) -> None:
    conn = _connect()
    try:
        if enabled:
            conn.execute(
                "INSERT OR IGNORE INTO custom_command_manager_roles(guild_id,role_id) VALUES(?,?)",
                (str(guild_id), str(role_id)),
            )
        else:
            conn.execute(
                "DELETE FROM custom_command_manager_roles WHERE guild_id = ? AND role_id = ?",
                (str(guild_id), str(role_id)),
            )
        conn.commit()
    finally:
        conn.close()


def list_manager_roles(guild_id: int) -> list[str]:
    rows = _fetchall(
        "SELECT role_id FROM custom_command_manager_roles WHERE guild_id = ? ORDER BY role_id",
        (str(guild_id),),
    )
    return [row["role_id"] for row in rows]


def record_use(command_id: int, guild_id: int, user_id: int, channel_id: int) -> None:
    conn = _connect()
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE custom_commands SET uses = uses + 1, last_used_at = ?, updated_at = updated_at WHERE id = ?",
            (now, int(command_id)),
        )
        conn.execute(
            "INSERT INTO custom_command_usage(command_id,guild_id,user_id,channel_id,uses,last_used_at) VALUES(?,?,?,?,1,?) "
            "ON CONFLICT(command_id,user_id,channel_id) DO UPDATE SET uses=uses+1,last_used_at=excluded.last_used_at",
            (int(command_id), str(guild_id), str(user_id), str(channel_id), now),
        )
        conn.commit()
    finally:
        conn.close()


def add_audit(guild_id: int, command_id: int | None, action: str, actor_id: int, details: str = "") -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO custom_command_audit(guild_id,command_id,action,actor_id,details) VALUES(?,?,?,?,?)",
            (str(guild_id), int(command_id) if command_id is not None else None, action, str(actor_id), details[:4000]),
        )
        conn.commit()
    finally:
        conn.close()


def list_audit(guild_id: int, command_id: int | None = None, limit: int = 25) -> list[dict[str, Any]]:
    if command_id is None:
        return _fetchall(
            "SELECT * FROM custom_command_audit WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
            (str(guild_id), int(limit)),
        )
    return _fetchall(
        "SELECT * FROM custom_command_audit WHERE guild_id = ? AND command_id = ? ORDER BY id DESC LIMIT ?",
        (str(guild_id), int(command_id), int(limit)),
    )


def role_and_channel_rules(command_id: int) -> dict[str, list[dict[str, Any]]]:
    return {
        "roles": list_role_rules(command_id),
        "channels": list_channel_rules(command_id),
    }


def retention(days_audit: int = 180, days_cooldown: int = 1) -> None:
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM custom_command_audit WHERE created_at < datetime('now', ?)",
            (f"-{int(days_audit)} days",),
        )
        conn.execute(
            "DELETE FROM custom_command_cooldown_hits WHERE last_used_at < datetime('now', ?)",
            (f"-{int(days_cooldown)} days",),
        )
        conn.commit()
    finally:
        conn.close()
