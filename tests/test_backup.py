from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

from core.backup import create_backup, prune_backups


def test_create_backup_contains_database_transcripts_and_manifest(tmp_path: Path):
    db_path = tmp_path / "data" / "discord.sqlite3"
    db_path.parent.mkdir()
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE test(value TEXT)")
    conn.execute("INSERT INTO test(value) VALUES (?)", ("hello",))
    conn.commit()
    conn.close()

    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / "ticket-1.txt").write_text("Transcript", encoding="utf-8")
    (transcripts / ".env").write_text("SECRET=do-not-backup", encoding="utf-8")

    backup_dir = tmp_path / "backups"
    backup = create_backup(db_path=db_path, transcripts_dir=transcripts, backup_dir=backup_dir)

    assert backup.exists()
    with zipfile.ZipFile(backup) as archive:
        names = set(archive.namelist())
        assert {"database.sqlite3", "manifest.json", "transcripts/ticket-1.txt"} <= names
        assert "transcripts/.env" not in names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["database"] == "database.sqlite3"
        assert manifest["transcripts"][0]["path"] == "ticket-1.txt"

        extracted_db = tmp_path / "restored.sqlite3"
        extracted_db.write_bytes(archive.read("database.sqlite3"))

    restored = sqlite3.connect(extracted_db)
    assert restored.execute("SELECT value FROM test").fetchone()[0] == "hello"
    restored.close()


def test_prune_backups_keeps_newest_files(tmp_path: Path):
    files = []
    for index in range(4):
        path = tmp_path / f"scratchai_backup_20260101_00000{index}.zip"
        path.write_bytes(b"backup")
        files.append(path)

    removed = prune_backups(tmp_path, keep=2)

    assert len(removed) == 2
    remaining = sorted(p.name for p in tmp_path.glob("scratchai_backup_*.zip"))
    assert remaining == [files[2].name, files[3].name]
