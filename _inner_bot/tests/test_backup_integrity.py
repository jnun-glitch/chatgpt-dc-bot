import sqlite3
from pathlib import Path

from core.backup import create_backup, verify_backup


def test_backup_roundtrip_is_verified(tmp_path: Path):
    db = tmp_path / "database.sqlite3"
    transcripts = tmp_path / "transcripts"
    backups = tmp_path / "backups"
    transcripts.mkdir()

    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE demo (id INTEGER PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO demo(value) VALUES ('ok')")
    conn.commit()
    conn.close()
    (transcripts / "2026-09-09.txt").write_text("test transcript\n", encoding="utf-8")

    backup = create_backup(db_path=db, transcripts_dir=transcripts, backup_dir=backups)
    valid, errors = verify_backup(backup)

    assert valid is True
    assert errors == []
