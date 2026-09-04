"""Datenbank: Verbindung, Schema und alle DB-Helper (Tickets, XP, Reminder, Modes)."""
import sqlite3
import json
import threading
import time as _time
from datetime import datetime, timedelta, timezone
from core.config import DB_PATH, OWNER_ID, ADMIN_LOG_CHANNEL_ID
from core.logging import logger

import discord


class _CachedConn:
    """Proxy um die gecachte SQLite-Connection: close() ist ein No-Op,
    damit bestehende Aufrufer (conn.close()) die wiederverwendete
    Verbindung nicht schließen. Alive-Check + Reconnect beim nächsten Zugriff."""
    __slots__ = ('_conn',)

    def __init__(self, conn):
        self._conn = conn

    def cursor(self):
        return self._conn.cursor()

    def commit(self):
        self._conn.commit()

    def execute(self, sql, params=()):
        return self._conn.execute(sql, params)

    def executescript(self, sql):
        return self._conn.executescript(sql)

    def close(self):
        pass

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._conn.row_factory = value


_conn = None
_conn_lock = threading.Lock()


def _open_raw():
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_db():
    """Liefert die gecachte, thread-sichere Connection (statt einer neuen pro Aufruf)."""
    global _conn
    with _conn_lock:
        try:
            if _conn is None:
                _conn = _open_raw()
            else:
                _conn.execute('SELECT 1')
        except Exception:
            _conn = _open_raw()
        return _CachedConn(_conn)


def _set_pragmas():
    """Performance-Optimierungen für SQLite."""
    global _conn
    with _conn_lock:
        try:
            if _conn is None:
                _conn = _open_raw()
            for pragma, value in (
                ('journal_mode', 'WAL'),
                ('synchronous', 'NORMAL'),
                ('busy_timeout', 5000),
                ('cache_size', -16000),
            ):
                _conn.execute(f'PRAGMA {pragma} = {value}')
        except Exception as e:
            logger.warning(f'PRAGMA Setup fehlgeschlagen: {e}')


def init_db():
    _set_pragmas()
    conn = get_db()
    cursor = conn.cursor()
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS verify_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            username TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL,
            used BOOLEAN DEFAULT FALSE
        );
        CREATE TABLE IF NOT EXISTS discord_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            website_username TEXT NOT NULL,
            discord_username TEXT DEFAULT '',
            discord_user_id TEXT DEFAULT '',
            confirmed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rate_limits (
            user_id TEXT PRIMARY KEY,
            attempts INTEGER DEFAULT 1,
            last_attempt TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS verification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            code TEXT NOT NULL,
            success BOOLEAN NOT NULL,
            reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_number INTEGER NOT NULL,
            channel_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            username TEXT NOT NULL,
            betreff TEXT NOT NULL,
            kategorie TEXT DEFAULT 'Sonstiges',
            status TEXT DEFAULT 'open',
            ai_verdict TEXT DEFAULT '',
            ai_analyzed BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed_at TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_tickets_channel ON tickets(channel_id);
        CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
        CREATE INDEX IF NOT EXISTS idx_verify_codes_code ON verify_codes(code);
        CREATE INDEX IF NOT EXISTS idx_discord_links_code ON discord_links(code);
        CREATE TABLE IF NOT EXISTS user_xp (
            user_id TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            messages INTEGER DEFAULT 0,
            last_xp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, guild_id)
        );
        CREATE TABLE IF NOT EXISTS user_warns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            grund TEXT NOT NULL,
            von TEXT NOT NULL,
            zeit TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bad_word_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            word TEXT NOT NULL,
            content TEXT NOT NULL,
            zeit TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_bad_word_log_user ON bad_word_log(user_id, guild_id);
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            remind_at TIMESTAMP NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent BOOLEAN DEFAULT FALSE
        );
        CREATE TABLE IF NOT EXISTS guild_modes (
            guild_id TEXT PRIMARY KEY,
            mode TEXT DEFAULT 'all'
        );
        CREATE TABLE IF NOT EXISTS guild_config (
            guild_id TEXT PRIMARY KEY,
            welcome_channel_id TEXT,
            join_role_id TEXT,
            ticket_category_id TEXT,
            member_count_channel TEXT
        );
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS command_usage (
            command TEXT PRIMARY KEY,
            used INTEGER DEFAULT 0,
            last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS member_history (
            guild_id TEXT NOT NULL,
            snapshot TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            count INTEGER NOT NULL,
            PRIMARY KEY (guild_id, snapshot)
        );
        CREATE TABLE IF NOT EXISTS update_log (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            last_hash TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS prefill_log (
            channel_id TEXT NOT NULL,
            marker TEXT NOT NULL,
            message_id TEXT NOT NULL,
            PRIMARY KEY (channel_id, marker)
        );
        CREATE TABLE IF NOT EXISTS reaction_roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            emoji TEXT NOT NULL,
            role_id TEXT NOT NULL,
            UNIQUE(guild_id, channel_id, message_id, emoji)
        );
        CREATE TABLE IF NOT EXISTS rules_gate (
            guild_id TEXT PRIMARY KEY,
            enabled BOOLEAN DEFAULT FALSE,
            rules_channel_id TEXT,
            rules_message_id TEXT,
            member_role_id TEXT
        );
        CREATE TABLE IF NOT EXISTS schematics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            category TEXT DEFAULT '',
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            uploaded_by TEXT DEFAULT '',
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS automod_config (
            guild_id TEXT NOT NULL,
            filter_name TEXT NOT NULL,
            enabled BOOLEAN DEFAULT TRUE,
            limit_value INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, filter_name)
        );
        CREATE TABLE IF NOT EXISTS giveaways (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            prize TEXT NOT NULL,
            description TEXT DEFAULT '',
            host_id TEXT NOT NULL,
            winner_id TEXT,
            end_time TIMESTAMP NOT NULL,
            ended BOOLEAN DEFAULT FALSE
        );
        CREATE TABLE IF NOT EXISTS giveaway_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            giveaway_id INTEGER NOT NULL,
            user_id TEXT NOT NULL,
            UNIQUE(giveaway_id, user_id),
            FOREIGN KEY (giveaway_id) REFERENCES giveaways(id)
        );
        CREATE INDEX IF NOT EXISTS idx_suggestions_guild ON suggestions(guild_id);
        CREATE INDEX IF NOT EXISTS idx_suggestions_status ON suggestions(guild_id, status);
        CREATE INDEX IF NOT EXISTS idx_reminders_pending ON reminders(remind_at, sent);
        CREATE INDEX IF NOT EXISTS idx_giveaways_guild ON giveaways(guild_id, ended);
        CREATE INDEX IF NOT EXISTS idx_giveaway_entries_giveaway ON giveaway_entries(giveaway_id);
        CREATE INDEX IF NOT EXISTS idx_user_xp_leaderboard ON user_xp(guild_id, level DESC, xp DESC);
        CREATE INDEX IF NOT EXISTS idx_user_warns_user ON user_warns(user_id, guild_id);
        CREATE INDEX IF NOT EXISTS idx_reaction_roles_msg ON reaction_roles(channel_id, message_id);
        CREATE INDEX IF NOT EXISTS idx_verification_log_user ON verification_log(user_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_bad_word_log_zeit ON bad_word_log(zeit);
        CREATE INDEX IF NOT EXISTS idx_member_history_snapshot ON member_history(snapshot);
        CREATE INDEX IF NOT EXISTS idx_rate_limits_last ON rate_limits(last_attempt);
        CREATE TABLE IF NOT EXISTS message_config (
            guild_id TEXT NOT NULL,
            msg_key TEXT NOT NULL,
            msg_value TEXT NOT NULL,
            PRIMARY KEY (guild_id, msg_key)
        );
    ''')
    # Migration: category-Spalte für Schematics (falls alte DB ohne Spalte)
    cols = {row[1] for row in cursor.execute('PRAGMA table_info(schematics)').fetchall()}
    if 'category' not in cols:
        cursor.execute("ALTER TABLE schematics ADD COLUMN category TEXT DEFAULT ''")

    # Migration: guild_config-Spalten für MC-Status, Starboard, Level-Rollen
    cfg_cols = {row[1] for row in cursor.execute('PRAGMA table_info(guild_config)').fetchall()}
    for col, ddl in (
        ('server_ip', 'server_ip TEXT'),
        ('server_port', 'server_port TEXT'),
        ('starboard_channel_id', 'starboard_channel_id TEXT'),
        ('starboard_threshold', 'starboard_threshold TEXT'),
        ('level_roles', 'level_roles TEXT'),
    ):
        if col not in cfg_cols:
            cursor.execute(f'ALTER TABLE guild_config ADD COLUMN {ddl}')

    # ── Starboard-Posts ─────────────────────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS starboard_posts (
            message_id TEXT PRIMARY KEY,
            guild_id TEXT NOT NULL,
            starboard_message_id TEXT NOT NULL
        );
    ''')

    # ── Guild-Settings (key/value) ──────────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            PRIMARY KEY (guild_id, key)
        );
    ''')

    # ── Polls ────────────────────────────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS polls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id TEXT NOT NULL,
            channel_id TEXT,
            message_id TEXT,
            question TEXT NOT NULL,
            options TEXT NOT NULL,
            votes TEXT NOT NULL,
            created_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ends_at TIMESTAMP
        );
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_polls_guild ON polls(guild_id)')

    # ── AFK ──────────────────────────────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS afk_users (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            reason TEXT DEFAULT '',
            afk_since TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, user_id)
        );
    ''')

    # ── Counting Game ────────────────────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS counting (
            guild_id TEXT NOT NULL PRIMARY KEY,
            channel_id TEXT,
            current_number INTEGER DEFAULT 0,
            highest_number INTEGER DEFAULT 0,
            last_user_id TEXT
        );
    ''')

    # ── Tags ─────────────────────────────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tags (
            guild_id TEXT NOT NULL,
            name TEXT NOT NULL,
            content TEXT NOT NULL,
            created_by TEXT,
            uses INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (guild_id, name)
        );
    ''')

    # ── Birthdays ────────────────────────────────────────────────────────────
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS birthdays (
            guild_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            birthday TEXT NOT NULL,
            last_wished INTEGER DEFAULT 0,
            PRIMARY KEY (guild_id, user_id)
        );
    ''')

    conn.commit()
    conn.close()
    run_retention()


def run_retention():
    """Löscht alte Log-Daten, damit die DB nicht unbegrenzt wächst.
    Bei jedem Bot-Start ausgeführt (Werte in Tagen)."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM bad_word_log WHERE zeit < datetime('now', '-30 days')")
        cursor.execute("DELETE FROM member_history WHERE snapshot < datetime('now', '-180 days')")
        cursor.execute("DELETE FROM verification_log WHERE timestamp < datetime('now', '-90 days')")
        # rate_limits: nur das 15-Minuten-Fenster ist relevant, Rest kann weg
        cursor.execute("DELETE FROM rate_limits WHERE last_attempt < datetime('now', '-1 hour')")
        conn.commit()
        conn.close()
        logger.info('Retention-Lauf abgeschlossen (bad_word_log 30d, member_history 180d, verification_log 90d, rate_limits 1h)')
    except Exception as e:
        logger.warning(f'Retention-Lauf fehlgeschlagen: {e}')


# ── Ticket DB Helpers ──────────────────────────────────────────────────────────
def get_ticket_by_channel(channel_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tickets WHERE channel_id = ? AND status = ?', (channel_id, 'open'))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_next_ticket_number():
    """Lädt die nächste Ticket-Nummer aus der DB (statt In-Memory Counter)."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT MAX(ticket_number) FROM tickets')
    row = cursor.fetchone()
    conn.close()
    max_num = row[0] if row and row[0] else 0
    return max_num + 1


def save_ticket(ticket_number: int, channel_id: str, user_id: str, username: str, betreff: str, kategorie: str = 'Sonstiges') -> int:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO tickets (ticket_number, channel_id, user_id, username, betreff, kategorie) VALUES (?, ?, ?, ?, ?, ?)',
        (ticket_number, channel_id, user_id, username, betreff, kategorie)
    )
    ticket_db_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return ticket_db_id


def update_ticket_ai(channel_id: str, ai_verdict: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'UPDATE tickets SET ai_verdict = ?, ai_analyzed = TRUE WHERE channel_id = ?',
        (ai_verdict, channel_id)
    )
    conn.commit()
    conn.close()


def close_ticket_db(channel_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE tickets SET status = 'closed', closed_at = CURRENT_TIMESTAMP WHERE channel_id = ?",
        (channel_id,)
    )
    conn.commit()
    conn.close()


def get_open_tickets() -> list:
    """Liefert alle offenen Tickets."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tickets WHERE status = 'open'")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_ticket_stats() -> dict:
    """Liefert Statistiken über alle Tickets."""
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('SELECT COUNT(*) FROM tickets')
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'open'")
    open_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM tickets WHERE status = 'closed'")
    closed_count = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT AVG(julianday(closed_at) - julianday(created_at)) * 24 
        FROM tickets WHERE status = 'closed' AND closed_at IS NOT NULL
    """)
    avg_hours = cursor.fetchone()[0]
    
    cursor.execute('''
        SELECT kategorie, COUNT(*) as count FROM tickets GROUP BY kategorie ORDER BY count DESC
    ''')
    categories = {row['kategorie']: row['count'] for row in cursor.fetchall()}
    
    conn.close()
    
    return {
        'total': total,
        'open': open_count,
        'closed': closed_count,
        'avg_close_hours': round(avg_hours, 1) if avg_hours else 0,
        'categories': categories
    }


# ── Rate Limiting ─────────────────────────────────────────────────────────────
def check_rate_limit(user_id: str) -> tuple:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM rate_limits WHERE user_id = ?', (user_id,))
    row = cursor.fetchone()

    if not row:
        cursor.execute(
            'INSERT INTO rate_limits (user_id, attempts, last_attempt) VALUES (?, 1, CURRENT_TIMESTAMP)',
            (user_id,)
        )
        conn.commit()
        conn.close()
        return False, 0

    attempts = row['attempts']
    last_attempt = datetime.fromisoformat(row['last_attempt'])
    # DB speichert CURRENT_TIMESTAMP in UTC -> Vergleich mit UTC, nicht mit Lokalzeit
    time_since = datetime.now(timezone.utc).replace(tzinfo=None) - last_attempt

    # Fenster abgelaufen: Zähler zurücksetzen, damit keine dauerhafte Sperre entsteht
    if time_since >= timedelta(minutes=15):
        cursor.execute('UPDATE rate_limits SET attempts = 0 WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()
        return False, 0

    if attempts >= 5:
        remaining = timedelta(minutes=15) - time_since
        conn.close()
        return True, int(remaining.total_seconds())

    conn.close()
    return False, 0


def increment_rate_limit(user_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO rate_limits (user_id, attempts, last_attempt)
        VALUES (?, 1, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
        attempts = attempts + 1,
        last_attempt = CURRENT_TIMESTAMP
    ''', (user_id,))
    conn.commit()
    conn.close()


def reset_rate_limit(user_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM rate_limits WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()


def log_verification(user_id: str, code: str, success: bool, reason: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO verification_log (user_id, code, success, reason) VALUES (?, ?, ?, ?)',
        (user_id, code, success, reason)
    )
    conn.commit()
    conn.close()


# ── XP System ────────────────────────────────────────────────────────────────
import random

def _xp_for_level(level):
    return int(100 * (1.5 ** (level - 1)))


_xp_cooldowns = {}
_XP_COOLDOWN_MAX = 2000


def _prune_xp_cooldowns(now):
    """Entfernt abgelaufene XP-Cooldown-Einträge, falls der Cache zu groß wird."""
    if len(_xp_cooldowns) <= _XP_COOLDOWN_MAX:
        return
    cutoff = now - 30
    for k in [k for k, last in _xp_cooldowns.items() if last < cutoff]:
        _xp_cooldowns.pop(k, None)


def _is_weekend() -> bool:
    """Prüft ob der aktuelle Wochentag Samstag (5) oder Sonntag (6) ist."""
    return datetime.now().weekday() in (5, 6)


def _add_xp(user_id: str, guild_id: str):
    try:
        now = _time.time()
        _prune_xp_cooldowns(now)
        key = f'{user_id}:{guild_id}'
        last = _xp_cooldowns.get(key, 0)
        if now - last < 30:
            return None
        _xp_cooldowns[key] = now

        conn = get_db()
        cursor = conn.cursor()
        xp_gain = random.randint(15, 25)
        if _is_weekend():
            xp_gain *= 2
        cursor.execute('''
            INSERT INTO user_xp (user_id, guild_id, xp, level, messages, last_xp)
            VALUES (?, ?, ?, 1, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET
            xp = xp + ?, messages = messages + 1, last_xp = CURRENT_TIMESTAMP
        ''', (str(user_id), str(guild_id), xp_gain, xp_gain))
        cursor.execute('SELECT xp, level FROM user_xp WHERE user_id = ? AND guild_id = ?',
                       (str(user_id), str(guild_id)))
        row = cursor.fetchone()
        if row:
            current_xp = row['xp']
            current_level = row['level']
            needed = _xp_for_level(current_level)
            if current_xp >= needed:
                cursor.execute('UPDATE user_xp SET level = level + 1 WHERE user_id = ? AND guild_id = ?',
                               (str(user_id), str(guild_id)))
                conn.commit()
                conn.close()
                return current_level + 1
        conn.commit()
        conn.close()
    except Exception:
        pass
    return None


def _get_xp(user_id: str, guild_id: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user_xp WHERE user_id = ? AND guild_id = ?',
                       (str(user_id), str(guild_id)))
        row = cursor.fetchone()
        conn.close()
        if row:
            return dict(row)
    except Exception:
        pass
    return None


def _get_leaderboard(guild_id: str, limit: int = 10):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM user_xp WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT ?',
                       (str(guild_id), limit))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        pass
    return []


def _get_user_rank(guild_id: str, user_id: str) -> int | None:
    """Liefert die Rangposition (1-basiert) eines Users oder None falls kein XP-Eintrag."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) + 1 AS rank FROM user_xp
            WHERE guild_id = ? AND (level > ? OR (level = ? AND xp > ?))
        ''', (str(guild_id), 0, 0, 0))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute('SELECT level, xp FROM user_xp WHERE user_id = ? AND guild_id = ?',
                       (str(user_id), str(guild_id)))
        user_row = cursor.fetchone()
        if not user_row:
            return None
        cursor.execute('''
            SELECT COUNT(*) + 1 AS rank FROM user_xp
            WHERE guild_id = ? AND (level > ? OR (level = ? AND xp > ?))
        ''', (str(guild_id), user_row['level'], user_row['level'], user_row['xp']))
        rank_row = cursor.fetchone()
        conn.close()
        return rank_row['rank'] if rank_row else None
    except Exception:
        pass
    return None


# ── Reminder Helper ─────────────────────────────────────────────────────────────
def save_reminder(user_id: str, channel_id: str, remind_at, message: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO reminders (user_id, channel_id, remind_at, message) VALUES (?, ?, ?, ?)',
        (str(user_id), str(channel_id), remind_at, message)
    )
    conn.commit()
    conn.close()


def get_pending_reminders():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM reminders WHERE remind_at <= datetime('now') AND sent = FALSE"
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_reminder_sent(reminder_id: int):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('UPDATE reminders SET sent = TRUE WHERE id = ?', (reminder_id,))
    conn.commit()
    conn.close()


def get_user_reminders(user_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM reminders WHERE user_id = ? AND sent = FALSE AND remind_at > datetime('now') ORDER BY remind_at",
        (str(user_id),)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cancel_reminder(reminder_id: int, user_id: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM reminders WHERE id = ? AND user_id = ?', (reminder_id, str(user_id)))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


# ── Bot-Modus pro Server ───────────────────────────────────────────────────────
_mode_cache = {}
_mode_cache_time = {}
_MODE_CACHE_TTL = 30


def get_guild_mode(guild_id) -> str:
    """Liefert den aktiven Bot-Modus eines Servers (default 'all'). Gecacht (30s TTL)."""
    key = str(guild_id)
    cached = _mode_cache.get(key)
    if cached is not None and _time.time() - _mode_cache_time.get(key, 0) < _MODE_CACHE_TTL:
        return cached
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT mode FROM guild_modes WHERE guild_id = ?', (key,))
        row = cursor.fetchone()
        mode = row[0] if row else 'all'
        _mode_cache[key] = mode
        _mode_cache_time[key] = _time.time()
        return mode
    except Exception:
        return 'all'


def set_guild_mode(guild_id, mode: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO guild_modes (guild_id, mode) VALUES (?, ?) '
            'ON CONFLICT(guild_id) DO UPDATE SET mode = excluded.mode',
            (str(guild_id), mode)
        )
        conn.commit()
        key = str(guild_id)
        _mode_cache[key] = mode
        _mode_cache_time[key] = _time.time()
        return True
    except Exception:
        return False


# ── Verifizierung prüfen ───────────────────────────────────────────────────────
def is_verified_discord(discord_user_id: int) -> bool:
    """Prüft ob ein Discord-User in der Website-DB verknüpft ist."""
    try:
        from pathlib import Path
        db_path = Path(__file__).resolve().parent.parent.parent / 'data' / 'discord_verify.db'
        if not db_path.exists():
            db_path = Path(__file__).resolve().parent.parent.parent / 'project' / 'data' / 'discord_verify.db'
        if not db_path.exists():
            return False
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            'SELECT id FROM discord_links WHERE discord_user_id = ? AND confirmed = TRUE',
            (str(discord_user_id),)
        )
        row = cursor.fetchone()
        conn.close()
        return row is not None
    except Exception:
        return False


# ── Guild-Config (Pro-Server-Einstellungen) ────────────────────────────────────
def get_guild_config(guild_id: int) -> dict:
    """Merged Spalten (guild_config) + key/value (guild_settings). Settings gewinnen."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM guild_config WHERE guild_id = ?', (str(guild_id),))
        row = cursor.fetchone()
        config = dict(row) if row else {}
        cursor.execute('SELECT key, value FROM guild_settings WHERE guild_id = ?', (str(guild_id),))
        for r in cursor.fetchall():
            config[r['key']] = r['value']
        conn.close()
        return config
    except Exception:
        return {}


def set_guild_config(guild_id: int, key: str, value):
    """Speichert einen beliebigen Key im key/value-Store. Ist der Key eine
    bekannte guild_config-Spalte, wird die Spalte zusätzlich synchron gehalten."""
    if value is not None:
        value = str(value)
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO guild_settings (guild_id, key, value) VALUES (?, ?, ?) '
            'ON CONFLICT(guild_id, key) DO UPDATE SET value = excluded.value',
            (str(guild_id), key, value)
        )
        col_names = {r[1] for r in cursor.execute('PRAGMA table_info(guild_config)').fetchall()}
        if key in col_names:
            if value is not None:
                cursor.execute(
                    f'INSERT INTO guild_config (guild_id, {key}) VALUES (?, ?) '
                    f'ON CONFLICT(guild_id) DO UPDATE SET {key} = excluded.{key}',
                    (str(guild_id), value)
                )
            else:
                cursor.execute(f'UPDATE guild_config SET {key} = NULL WHERE guild_id = ?', (str(guild_id),))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_starboard_post(message_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM starboard_posts WHERE message_id = ?', (str(message_id),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def set_starboard_post(message_id, guild_id, starboard_message_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT OR REPLACE INTO starboard_posts (message_id, guild_id, starboard_message_id) VALUES (?, ?, ?)',
            (str(message_id), str(guild_id), str(starboard_message_id))
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def remove_starboard_post(message_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM starboard_posts WHERE message_id = ?', (str(message_id),))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_level_roles(guild_id: int) -> dict:
    """Liest konfigurierte Level-Rollen (level -> role_id). Leer = Defaults."""
    cfg = get_guild_config(guild_id)
    raw = cfg.get('level_roles')
    if not raw:
        return {}
    try:
        import json
        data = json.loads(raw)
        return {int(k): v for k, v in data.items() if v}
    except Exception:
        return {}


def set_level_role(guild_id: int, level: int, role_id) -> bool:
    import json
    roles = get_level_roles(guild_id)
    roles[int(level)] = str(role_id)
    return set_guild_config(guild_id, 'level_roles', json.dumps(roles))


def remove_level_role(guild_id: int, level: int) -> bool:
    import json
    roles = get_level_roles(guild_id)
    if int(level) in roles:
        del roles[int(level)]
    return set_guild_config(guild_id, 'level_roles', json.dumps(roles))
MESSAGE_DEFAULTS = {
    'welcome_title': 'Willkommen {name}! 🎉',
    'welcome_desc': 'Hey {mention}, willkommen im **{server}** Discord!\n\nViel Spaß hier! 💜',
    'welcome_card_title': 'Willkommen {name}!',
    'welcome_card_sub': 'Herzlich willkommen im **{server}** Discord!',
    'welcome_card_footer': 'Du bist Mitglied #{count} 💜',
    'welcome_roles_msg': '📋 **Wähle deine Rollen:**\nKlicke auf die Buttons um Neuigkeiten zu abonnieren!',
    'levelup_msg': '{mention} ist jetzt **Level {level}**! 🎉',
    'levelup_role_msg': '{mention} hat die Rolle **{role}** erhalten!',
    'spam_msg': '✋ {mention} Bitte nicht so viel auf einmal senden!',
    'badword_msg': '🚫 {mention} Bitte keine unangemessene Sprache!',
    'verify_msg': '🚫 Noch nicht verifiziert',
    'verify_desc': 'Hey {mention}, du kannst hier noch nicht schreiben!\n\nLies die **Serverregeln** in {channel} und klicke dort auf **"Regeln akzeptieren"**, um die **Member**-Rolle zu erhalten.',
    'no_perm_msg': '⛔ Keine Berechtigung!',
    'error_msg': 'Ein interner Fehler ist aufgetreten. Bitte versuche es später erneut.',
    'cooldown_msg': 'Cooldown: Warte {seconds}s.',
    'bot_missing_perm_msg': 'Der Bot fehlt nötige Berechtigungen.',
    'ticket_welcome': 'Hallo {mention}! Willkommen im **Support-Ticket** #{number}.\n\n**Betreff:** {subject}\n**Kategorie:** {category}\n\nSchreib hier deine Frage oder dein Problem rein.',
    'ticket_close': 'Ticket wurde geschlossen von {mod}.',
    'ticket_resolve': 'Ticket als gelöst markiert.',
    'autoresponse_hallo': 'Hey! 👋 Nutze `/help` für eine Übersicht aller Befehle.',
    'autoresponse_danke': 'Bitte! 😊 Frag gerne wenn du Hilfe brauchst!',
    'autoresponse_hilfe': 'Nutze `/help` für eine Übersicht aller Befehle.',
    'autoresponse_wie_geht': 'Nutze `/ask` um eine Frage zu stellen!',
    'autoresponse_was_ist': 'Scratch ist eine kostenlose Programmiersprache.',
}


def get_msg(guild_id: int, key: str) -> str:
    """Liest eine angepasste Nachricht aus der DB, oder gibt den Standard zurück."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT msg_value FROM message_config WHERE guild_id = ? AND msg_key = ?',
            (str(guild_id), key)
        )
        row = cursor.fetchone()
        conn.close()
        if row:
            return row['msg_value'] if isinstance(row, dict) else row[0]
    except Exception:
        pass
    return MESSAGE_DEFAULTS.get(key, '')


def set_msg(guild_id: int, key: str, value: str) -> bool:
    """Speichert eine angepasste Nachricht in der DB."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO message_config (guild_id, msg_key, msg_value) VALUES (?, ?, ?) '
            'ON CONFLICT(guild_id, msg_key) DO UPDATE SET msg_value = excluded.msg_value',
            (str(guild_id), key, value)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def del_msg(guild_id: int, key: str) -> bool:
    """Löscht eine angepasste Nachricht (setzt auf Standard zurück)."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'DELETE FROM message_config WHERE guild_id = ? AND msg_key = ?',
            (str(guild_id), key)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_all_msgs(guild_id: int) -> dict:
    """Liest alle angepassten Nachrichten für einen Guild."""
    result = dict(MESSAGE_DEFAULTS)
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT msg_key, msg_value FROM message_config WHERE guild_id = ?',
            (str(guild_id),)
        )
        for row in cursor.fetchall():
            d = dict(row) if not isinstance(row, dict) else row
            result[d['msg_key']] = d['msg_value']
        conn.close()
    except Exception:
        pass
    return result


def format_msg(guild_id: int, key: str, **kwargs) -> str:
    """Liest Nachricht aus DB und formatiert sie mit Platzhaltern."""
    tpl = get_msg(guild_id, key)
    try:
        return tpl.format(**kwargs)
    except (KeyError, IndexError):
        return tpl


# ── Suggestions (Verbesserungsvorschläge) ──────────────────────────────────────
def add_suggestion(guild_id: int, user_id: int, text: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO suggestions (guild_id, user_id, text) VALUES (?, ?, ?)',
            (str(guild_id), str(user_id), text)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ── Statistiken ────────────────────────────────────────────────────────────────
def track_command_usage(command_name: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO command_usage (command, used, last_used) VALUES (?, 1, CURRENT_TIMESTAMP) '
            'ON CONFLICT(command) DO UPDATE SET used = used + 1, last_used = CURRENT_TIMESTAMP',
            (command_name,)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_command_usage(limit: int = 10):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT command, used, last_used FROM command_usage ORDER BY used DESC LIMIT ?', (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def save_member_snapshot(guild_id: int, count: int):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO member_history (guild_id, count) VALUES (?, ?)',
            (str(guild_id), count)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_member_history(guild_id: int, limit: int = 30):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'SELECT snapshot, count FROM member_history WHERE guild_id = ? ORDER BY snapshot DESC LIMIT ?',
            (str(guild_id), limit)
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# ── Update-Log (zuletzt geposteter Commit) ─────────────────────────────────────
def get_last_posted_hash():
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT last_hash FROM update_log WHERE id = 1')
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def set_last_posted_hash(commit_hash: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO update_log (id, last_hash, updated_at) VALUES (1, ?, CURRENT_TIMESTAMP) '
            'ON CONFLICT(id) DO UPDATE SET last_hash = excluded.last_hash, updated_at = CURRENT_TIMESTAMP',
            (commit_hash,)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ── Prefill-Log (gesendete Start-Nachrichten pro Kanal) ────────────────────────
def get_prefill_log(channel_id, marker):
    """Liefert die gespeicherte Message-ID einer Start-Nachricht oder None."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT message_id FROM prefill_log WHERE channel_id = ? AND marker = ?', (str(channel_id), marker))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def set_prefill_log(channel_id, marker, message_id):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO prefill_log (channel_id, marker, message_id) VALUES (?, ?, ?) '
            'ON CONFLICT(channel_id, marker) DO UPDATE SET message_id = excluded.message_id',
            (str(channel_id), marker, str(message_id))
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ── Auto-Moderation (Pro-Server-Filter-Einstellungen) ──────────────────────────
def get_automod_config(guild_id: int) -> dict:
    """Lädt alle AutoMod-Filter-Einstellungen eines Servers als Dict {filter_name: {enabled, limit_value}}."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT filter_name, enabled, limit_value FROM automod_config WHERE guild_id = ?', (str(guild_id),))
        rows = cursor.fetchall()
        conn.close()
        return {row['filter_name']: {'enabled': bool(row['enabled']), 'limit_value': row['limit_value']} for row in rows}
    except Exception:
        return {}


def set_automod_config(guild_id: int, filter_name: str, enabled: bool = True, limit_value: int = 0):
    """Setzt oder aktualisiert einen AutoMod-Filter für einen Server."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO automod_config (guild_id, filter_name, enabled, limit_value) VALUES (?, ?, ?, ?) '
            'ON CONFLICT(guild_id, filter_name) DO UPDATE SET enabled = excluded.enabled, limit_value = excluded.limit_value',
            (str(guild_id), filter_name, enabled, limit_value)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ── Schematics (Bauplan-Bibliothek) ────────────────────────────────────────────
def add_schematic(name: str, description: str, file_path, file_size: int, uploaded_by: str, category: str = ''):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO schematics (name, description, category, file_path, file_size, uploaded_by) VALUES (?, ?, ?, ?, ?, ?)',
            (name, description, category, str(file_path), int(file_size), str(uploaded_by))
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_schematic(schem_id: int):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM schematics WHERE id = ?', (int(schem_id),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def get_schematic_by_name(name: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM schematics WHERE name = ? COLLATE NOCASE', (name,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def list_schematic_categories():
    """Liefert alle Kategorien (nicht-leer) mit Anzahl der Schematics, sortiert nach Anzahl absteigend."""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT category AS name, COUNT(*) AS count FROM schematics WHERE category <> '' GROUP BY category "
            "ORDER BY COUNT(*) DESC, category COLLATE NOCASE"
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def list_schematics(limit: int = 100, category: str = ''):
    try:
        conn = get_db()
        cursor = conn.cursor()
        if category:
            cursor.execute(
                'SELECT * FROM schematics WHERE category = ? COLLATE NOCASE ORDER BY name COLLATE NOCASE LIMIT ?',
                (category, int(limit))
            )
        else:
            cursor.execute('SELECT * FROM schematics ORDER BY name COLLATE NOCASE LIMIT ?', (int(limit),))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def update_schematic_category(schem_id: int, category: str):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('UPDATE schematics SET category = ? WHERE id = ?', (category, int(schem_id)))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def remove_schematic(schem_id: int):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM schematics WHERE id = ?', (int(schem_id),))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ── Rules Gate (Verifizierung über Regeln-Channel) ────────────────────────────
def get_rules_gate(guild_id) -> dict:
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM rules_gate WHERE guild_id = ?', (str(guild_id),))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else {}
    except Exception:
        return {}


def set_rules_gate(guild_id, enabled: bool = True, rules_channel_id=None, rules_message_id=None, member_role_id=None):
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO rules_gate (guild_id, enabled, rules_channel_id, rules_message_id, member_role_id) '
            'VALUES (?, ?, ?, ?, ?) '
            'ON CONFLICT(guild_id) DO UPDATE SET '
            'enabled = excluded.enabled, '
            'rules_channel_id = excluded.rules_channel_id, '
            'rules_message_id = excluded.rules_message_id, '
            'member_role_id = excluded.member_role_id',
            (str(guild_id), 1 if enabled else 0, str(rules_channel_id) if rules_channel_id else None,
             str(rules_message_id) if rules_message_id else None, str(member_role_id) if member_role_id else None)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False
