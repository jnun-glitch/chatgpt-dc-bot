"""Erzeugt und prüft atomare Bot-Backups aus SQLite + Transkripten.

Keine Geheimnisse wie .env oder Tokens werden in Backups aufgenommen.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_NAMES = {".env", ".env.local", ".env.production", "secrets.json"}


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _copy_sqlite_consistently(source_path: Path, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    source = sqlite3.connect(str(source_path), check_same_thread=False)
    target = sqlite3.connect(str(destination_path))
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()


def create_backup(*, db_path: Path, transcripts_dir: Path, backup_dir: Path) -> Path:
    """Erzeugt ein vollständiges Daten-Backup als ZIP und gibt dessen Pfad zurück."""
    db_path = Path(db_path)
    transcripts_dir = Path(transcripts_dir)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    final_path = backup_dir / f"scratchai_backup_{stamp}.zip"

    with tempfile.TemporaryDirectory(prefix="scratchai_backup_") as temp_dir:
        staging = Path(temp_dir)
        staged_db = staging / "database.sqlite3"
        if db_path.exists():
            _copy_sqlite_consistently(db_path, staged_db)
        else:
            sqlite3.connect(str(staged_db)).close()

        manifest: dict = {
            "format": 2,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "database": "database.sqlite3",
            "database_sha256": _sha256(staged_db),
            "transcripts": [],
        }

        transcript_root = transcripts_dir.resolve()
        staged_transcripts = staging / "transcripts"
        if transcript_root.exists():
            for source in sorted(p for p in transcript_root.rglob("*") if p.is_file()):
                if source.name in EXCLUDED_NAMES:
                    continue
                relative = _safe_relative(source, transcript_root)
                target = staged_transcripts / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                manifest["transcripts"].append({
                    "path": relative,
                    "size": source.stat().st_size,
                    "sha256": _sha256(source),
                })

        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        temp_zip = backup_dir / f".{final_path.name}.tmp"
        try:
            with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.write(staged_db, "database.sqlite3")
                archive.write(manifest_path, "manifest.json")
                if staged_transcripts.exists():
                    for source in sorted(p for p in staged_transcripts.rglob("*") if p.is_file()):
                        archive.write(source, "transcripts/" + _safe_relative(source, staged_transcripts))
            os.replace(temp_zip, final_path)
        finally:
            if temp_zip.exists():
                temp_zip.unlink(missing_ok=True)

    return final_path


def verify_backup(path: Path) -> tuple[bool, list[str]]:
    """Prüft ZIP, Manifest, Datenbank und alle gespeicherten Transcript-Hashes."""
    path = Path(path)
    errors: list[str] = []
    if not path.is_file():
        return False, [f"Backup fehlt: {path}"]
    try:
        with zipfile.ZipFile(path, "r") as archive:
            bad_member = archive.testzip()
            if bad_member:
                errors.append(f"Defektes ZIP-Mitglied: {bad_member}")
            try:
                manifest = json.loads(archive.read("manifest.json"))
            except (KeyError, json.JSONDecodeError) as exc:
                return False, [f"Manifest ungültig: {exc}"]

            try:
                database_member = manifest.get("database", "database.sqlite3")
                db_bytes = archive.read(database_member)
            except KeyError:
                errors.append("Datenbankdatei fehlt im Backup")
                db_bytes = b""

            expected_db = manifest.get("database_sha256")
            if expected_db and db_bytes:
                actual_db = hashlib.sha256(db_bytes).hexdigest()
                if actual_db != expected_db:
                    errors.append("Datenbank-Hash stimmt nicht mit dem Manifest überein")

            if db_bytes:
                # NamedTemporaryFile remains open on Windows, which prevents
                # sqlite3 from reopening the same file. TemporaryDirectory lets
                # us close the database file before SQLite opens it.
                with tempfile.TemporaryDirectory(prefix="scratchai_verify_") as temp_dir:
                    temp_db = Path(temp_dir) / "database.sqlite3"
                    temp_db.write_bytes(db_bytes)
                    check = None
                    try:
                        check = sqlite3.connect(str(temp_db))
                        result = check.execute("PRAGMA quick_check").fetchone()
                        if not result or str(result[0]).lower() != "ok":
                            detail = str(result[0]) if result else "keine Antwort"
                            errors.append(f"SQLite-Prüfung fehlgeschlagen: {detail}")
                    except (sqlite3.DatabaseError, OSError) as exc:
                        errors.append(f"SQLite-Prüfung fehlgeschlagen: {exc}")
                    finally:
                        if check is not None:
                            check.close()

            for item in manifest.get("transcripts", []):
                member = "transcripts/" + item["path"]
                try:
                    data = archive.read(member)
                except KeyError:
                    errors.append(f"Transcript fehlt: {item['path']}")
                    continue
                if len(data) != int(item.get("size", len(data))):
                    errors.append(f"Transcript-Größe falsch: {item['path']}")
                if item.get("sha256") and hashlib.sha256(data).hexdigest() != item["sha256"]:
                    errors.append(f"Transcript-Hash falsch: {item['path']}")
    except zipfile.BadZipFile:
        return False, ["Backup ist kein gültiges ZIP-Archiv"]
    except OSError as exc:
        return False, [f"Backup konnte nicht gelesen werden: {exc}"]
    return not errors, errors


def prune_backups(backup_dir: Path, keep: int = 288) -> list[Path]:
    """Behält die neuesten `keep` Backups und löscht ältere ZIPs."""
    backup_dir = Path(backup_dir)
    keep = max(1, int(keep))
    backups = sorted(backup_dir.glob("scratchai_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed: list[Path] = []
    for path in backups[keep:]:
        path.unlink(missing_ok=True)
        removed.append(path)
    return removed
