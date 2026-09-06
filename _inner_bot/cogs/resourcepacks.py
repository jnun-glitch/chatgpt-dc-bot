"""Minecraft Resource-Pack-Bibliothek.

Resource Packs werden als ZIP gespeichert und vor dem Eintrag streng geprüft.
Insbesondere muss pack.mcmeta gültiges JSON enthalten und eine explizite
Pack-Version deklarieren: legacy `pack_format` oder modernes `min_format` +
`max_format`.
"""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from core.config import PROJECT_ROOT, _is_owner
from core.logging import logger

RESOURCEPACKS_DIR = PROJECT_ROOT / "data" / "resourcepacks"
MAX_UPLOAD_MB = 25
MAX_UNCOMPRESSED_MB = 100
MAX_FILES = 20_000
MAX_SINGLE_UNCOMPRESSED_MB = 25
MAX_NAME_LEN = 80
MAX_DESCRIPTION_LEN = 1000


def _db_conn():
    from core.db import get_db
    return get_db()


def _init_resourcepack_db() -> None:
    conn = _db_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS resourcepacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            category TEXT DEFAULT '',
            minecraft_version TEXT DEFAULT '',
            pack_version_min TEXT NOT NULL,
            pack_version_max TEXT NOT NULL,
            legacy_pack_format TEXT DEFAULT '',
            file_path TEXT NOT NULL,
            file_size INTEGER DEFAULT 0,
            uncompressed_size INTEGER DEFAULT 0,
            file_count INTEGER DEFAULT 0,
            has_icon BOOLEAN DEFAULT FALSE,
            uploaded_by TEXT DEFAULT '',
            uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()


def _db_add(data: dict[str, Any]) -> bool:
    try:
        conn = _db_conn()
        conn.execute(
            """
            INSERT INTO resourcepacks
            (name, description, category, minecraft_version,
             pack_version_min, pack_version_max, legacy_pack_format,
             file_path, file_size, uncompressed_size, file_count,
             has_icon, uploaded_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["name"], data["description"], data["category"], data["minecraft_version"],
                data["pack_version_min"], data["pack_version_max"], data["legacy_pack_format"],
                data["file_path"], data["file_size"], data["uncompressed_size"], data["file_count"],
                data["has_icon"], data["uploaded_by"],
            ),
        )
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        return False
    except Exception:
        logger.exception("Resource-Pack DB-Eintrag fehlgeschlagen")
        return False


def _db_get(name: str):
    try:
        conn = _db_conn()
        row = conn.execute("SELECT * FROM resourcepacks WHERE name = ?", (name,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def _db_get_id(pack_id: int):
    try:
        conn = _db_conn()
        row = conn.execute("SELECT * FROM resourcepacks WHERE id = ?", (pack_id,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def _db_list(limit: int = 100):
    try:
        conn = _db_conn()
        rows = conn.execute(
            "SELECT * FROM resourcepacks ORDER BY name COLLATE NOCASE LIMIT ?", (int(limit),)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def _db_remove(pack_id: int) -> bool:
    try:
        conn = _db_conn()
        conn.execute("DELETE FROM resourcepacks WHERE id = ?", (pack_id,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        logger.exception("Resource-Pack DB-Löschung fehlgeschlagen")
        return False


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w\-äöüß]+", "_", name.strip(), flags=re.IGNORECASE)
    return cleaned.strip(" _") or "resourcepack"


def _size_text(size: int) -> str:
    size = max(0, int(size))
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, size // 1024)} KB"


def _format_version(value: Any) -> str | None:
    """Normalisiert pack versions auf 'major.minor'."""
    if isinstance(value, int) and value >= 0:
        return f"{value}.0"
    if isinstance(value, float) and value >= 0:
        return f"{value:g}"
    if isinstance(value, list) and len(value) in (1, 2) and all(isinstance(x, int) and x >= 0 for x in value):
        return f"{value[0]}.{value[1] if len(value) == 2 else 0}"
    return None


def _validate_icon(data: bytes) -> bool:
    """Kleine, nativen PNG-Prüfung ohne zusätzliche Abhängigkeit."""
    return data.startswith(b"\x89PNG\r\n\x1a\n")


def _validate_zip(path: Path) -> dict[str, Any]:
    """Prüft und analysiert eine Resource-Pack-ZIP sicher, ohne sie zu entpacken."""
    max_uncompressed = MAX_UNCOMPRESSED_MB * 1024 * 1024
    max_single = MAX_SINGLE_UNCOMPRESSED_MB * 1024 * 1024
    with zipfile.ZipFile(path, "r") as zf:
        infos = zf.infolist()
        if not infos:
            raise ValueError("Die ZIP ist leer.")
        if len(infos) > MAX_FILES:
            raise ValueError(f"Zu viele Dateien ({len(infos):,}); maximal {MAX_FILES:,}.")

        seen: set[str] = set()
        total_uncompressed = 0
        for info in infos:
            raw_name = info.filename.replace("\\", "/")
            normalized = Path(raw_name)
            if "\x00" in raw_name or normalized.is_absolute() or any(part == ".." for part in normalized.parts):
                raise ValueError(f"Unsicherer ZIP-Pfad erkannt: {info.filename!r}")
            if info.filename in seen:
                raise ValueError(f"Doppelter ZIP-Eintrag: {info.filename!r}")
            seen.add(info.filename)
            # Symlinks/Unix-Sonderdateien nicht akzeptieren.
            mode = (info.external_attr >> 16) & 0o170000
            if mode in (0o120000, 0o010000, 0o020000, 0o060000):
                raise ValueError(f"Nicht unterstützter Sonderdatei-Eintrag: {info.filename!r}")
            if info.file_size < 0:
                raise ValueError(f"Ungültige Dateigröße: {info.filename!r}")
            if info.file_size > max_single:
                raise ValueError(
                    f"Einzelne Datei ist zu groß: {info.filename!r} (> {MAX_SINGLE_UNCOMPRESSED_MB} MB entpackt)."
                )
            total_uncompressed += info.file_size
            if total_uncompressed > max_uncompressed:
                raise ValueError(f"Entpackte ZIP-Größe überschreitet {MAX_UNCOMPRESSED_MB} MB.")

        names = {i.filename.replace("\\", "/").lstrip("/"): i for i in infos if not i.is_dir()}
        # Standardfall: pack.mcmeta direkt im ZIP-Root.
        prefix = ""
        if "pack.mcmeta" not in names:
            candidates = [n for n in names if n.count("/") == 1 and n.endswith("/pack.mcmeta")]
            if len(candidates) == 1:
                prefix = candidates[0][:-len("pack.mcmeta")]
            else:
                raise ValueError("`pack.mcmeta` fehlt im Resource Pack.")
        mcmeta_name = f"{prefix}pack.mcmeta"
        with zf.open(names[mcmeta_name]) as fp:
            raw = fp.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("`pack.mcmeta` ist ungewöhnlich groß.")
        try:
            mcmeta = json.loads(raw.decode("utf-8"))
        except UnicodeDecodeError:
            raise ValueError("`pack.mcmeta` muss UTF-8 sein.")
        except json.JSONDecodeError as exc:
            raise ValueError(f"`pack.mcmeta` enthält ungültiges JSON: {exc.msg}.")

        pack = mcmeta.get("pack") if isinstance(mcmeta, dict) else None
        if not isinstance(pack, dict):
            raise ValueError("`pack.mcmeta` enthält keinen gültigen `pack`-Bereich.")

        legacy = _format_version(pack.get("pack_format"))
        min_v = _format_version(pack.get("min_format"))
        max_v = _format_version(pack.get("max_format"))
        # Absichtlich strenger als Minecraft: irgendeine explizite Version muss vorhanden sein.
        if legacy is None and (min_v is None or max_v is None):
            raise ValueError(
                "Pack-Version fehlt. Erforderlich ist `pack_format` (alte Packs) "
                "oder `min_format` + `max_format` (neues Pack-Format)."
            )
        if legacy is not None:
            min_v = max_v = legacy
        elif min_v is not None and max_v is not None:
            # Vergleich als Versionspaar.
            def pair(v: str) -> tuple[int, int]:
                a, b = v.split(".")
                return int(a), int(b)
            if pair(min_v) > pair(max_v):
                raise ValueError("`min_format` darf nicht größer als `max_format` sein.")

        icon_name = f"{prefix}pack.png"
        has_icon = False
        if icon_name in names:
            with zf.open(names[icon_name]) as fp:
                icon_head = fp.read(32)
            has_icon = _validate_icon(icon_head)
            if not has_icon:
                raise ValueError("`pack.png` ist vorhanden, aber keine gültige PNG-Datei.")

        description = pack.get("description", "")
        if isinstance(description, (dict, list)):
            description = json.dumps(description, ensure_ascii=False)
        description = str(description)[:MAX_DESCRIPTION_LEN]

        return {
            "description": description,
            "pack_version_min": min_v or "",
            "pack_version_max": max_v or "",
            "legacy_pack_format": legacy or "",
            "has_icon": has_icon,
            "uncompressed_size": total_uncompressed,
            "file_count": len(names),
            "prefix": prefix,
        }


def _extract_zip_secure(zip_path: Path, target_dir: Path, prefix: str = "") -> None:
    """Entpackt erst nach erfolgreicher Analyse nochmals sicher."""
    target_dir.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            root = target_dir.resolve()
            for info in zf.infolist():
                raw_name = info.filename.replace("\\", "/")
                if "\x00" in raw_name:
                    raise ValueError("Ungültiger Dateiname in ZIP.")
                rel = raw_name
                if prefix and rel.startswith(prefix):
                    rel = rel[len(prefix):]
                dest = (target_dir / rel).resolve()
                if not str(dest).startswith(str(root) + str(Path("/"))):
                    raise ValueError("ZIP-Eintrag verlässt den Zielordner.")
                if info.is_dir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, dest.open("xb") as out:
                    shutil.copyfileobj(src, out, length=1024 * 1024)
    except Exception:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise


class ResourcePacksCog(commands.Cog):
    """Bibliothek für sichere Minecraft Java Resource Packs."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        _init_resourcepack_db()
        RESOURCEPACKS_DIR.mkdir(parents=True, exist_ok=True)

    group = app_commands.Group(name="resourcepacks", description="Minecraft Resource-Pack-Bibliothek")

    async def _require_manager(self, interaction: discord.Interaction) -> bool:
        allowed = (
            _is_owner(interaction.user)
            or interaction.user.guild_permissions.administrator
            or (interaction.guild is not None and interaction.user.id == interaction.guild.owner_id)
        )
        if not allowed:
            await interaction.response.send_message(
                "Nur der Owner, Server-Owner oder Admins können Resource Packs verwalten.", ephemeral=True
            )
            return False
        return True

    @staticmethod
    def _upload_limit(interaction: discord.Interaction) -> int:
        return int(getattr(interaction, "filesize_limit", 0) or 0) or MAX_UPLOAD_MB * 1024 * 1024

    @group.command(name="add", description="Resource Pack als ZIP hinzufügen und automatisch prüfen")
    @app_commands.describe(
        datei="Resource-Pack ZIP",
        name="Anzeigename (optional, sonst ZIP-Dateiname)",
        kategorie="Kategorie, z.B. SMP, PvP, GUI",
        minecraft_version="Minecraft-Version, z.B. 1.21.11 (optional)",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        datei: discord.Attachment,
        name: str = "",
        kategorie: str = "",
        minecraft_version: str = "",
    ):
        if not await self._require_manager(interaction):
            return
        if not datei or Path(datei.filename or "").suffix.lower() != ".zip":
            await interaction.response.send_message("❌ Es sind nur `.zip` Resource Packs erlaubt.", ephemeral=True)
            return
        limit = self._upload_limit(interaction)
        if datei.size > limit:
            await interaction.response.send_message(
                f"❌ ZIP zu groß. Serverlimit: {limit // (1024 * 1024)} MB.", ephemeral=True
            )
            return

        clean_name = (name.strip() or Path(datei.filename).stem).strip()[:MAX_NAME_LEN]
        if not clean_name:
            await interaction.response.send_message("❌ Ungültiger Name.", ephemeral=True)
            return
        if _db_get(clean_name):
            await interaction.response.send_message(f"❌ **{clean_name}** existiert bereits.", ephemeral=True)
            return

        zip_path = RESOURCEPACKS_DIR / f".{_sanitize_filename(clean_name)}.upload.zip"
        pack_dir = RESOURCEPACKS_DIR / _sanitize_filename(clean_name)
        try:
            await datei.save(zip_path)
            analysis = _validate_zip(zip_path)
            _extract_zip_secure(zip_path, pack_dir, analysis["prefix"])
            final_path = pack_dir

            data = {
                "name": clean_name,
                "description": analysis["description"],
                "category": kategorie.strip()[:80],
                "minecraft_version": minecraft_version.strip()[:40],
                "pack_version_min": analysis["pack_version_min"],
                "pack_version_max": analysis["pack_version_max"],
                "legacy_pack_format": analysis["legacy_pack_format"],
                "file_path": str(final_path),
                "file_size": int(datei.size),
                "uncompressed_size": int(analysis["uncompressed_size"]),
                "file_count": int(analysis["file_count"]),
                "has_icon": bool(analysis["has_icon"]),
                "uploaded_by": str(interaction.user),
            }
            if not _db_add(data):
                shutil.rmtree(pack_dir, ignore_errors=True)
                raise ValueError("Datenbank-Eintrag fehlgeschlagen oder Name bereits vorhanden.")
        except zipfile.BadZipFile:
            shutil.rmtree(pack_dir, ignore_errors=True)
            await interaction.response.send_message("❌ Die Datei ist keine gültige ZIP.", ephemeral=True)
            return
        except Exception as exc:
            try:
                if zip_path.exists():
                    zip_path.unlink()
            except Exception:
                pass
            shutil.rmtree(pack_dir, ignore_errors=True)
            logger.warning("Resource-Pack abgelehnt: %s", exc)
            await interaction.response.send_message(f"❌ Resource Pack abgelehnt: {exc}", ephemeral=True)
            return
        finally:
            try:
                if zip_path.exists():
                    zip_path.unlink()
            except Exception:
                pass

        version_text = analysis["pack_version_min"]
        if analysis["pack_version_min"] != analysis["pack_version_max"]:
            version_text += f" – {analysis['pack_version_max']}"
        embed = discord.Embed(
            title="✅ Resource Pack hinzugefügt",
            description=f"**{clean_name}** wurde sicher geprüft und gespeichert.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Pack-Version", value=version_text, inline=True)
        embed.add_field(name="Minecraft", value=minecraft_version.strip() or "nicht angegeben", inline=True)
        embed.add_field(name="Größe", value=_size_text(datei.size), inline=True)
        embed.add_field(name="Dateien", value=f"{analysis['file_count']:,}", inline=True)
        embed.add_field(name="Entpackt", value=_size_text(analysis["uncompressed_size"]), inline=True)
        embed.add_field(name="Icon", value="✅ pack.png" if analysis["has_icon"] else "– keines", inline=True)
        if analysis["description"]:
            embed.add_field(name="Beschreibung", value=analysis["description"][:1000], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="list", description="Alle Resource Packs anzeigen")
    async def list_cmd(self, interaction: discord.Interaction):
        packs = _db_list(100)
        if not packs:
            await interaction.response.send_message("📭 Noch keine Resource Packs vorhanden.", ephemeral=True)
            return
        embed = discord.Embed(title="🎨 Resource-Pack-Bibliothek", color=discord.Color.teal())
        for pack in packs[:20]:
            version = pack.get("pack_version_min", "?")
            if pack.get("pack_version_min") != pack.get("pack_version_max"):
                version += f" – {pack.get('pack_version_max')}"
            mc = pack.get("minecraft_version") or "MC-Version nicht angegeben"
            icon = " 🖼️" if pack.get("has_icon") else ""
            embed.add_field(
                name=f"{pack['name']}{icon}",
                value=f"🎮 `{mc}`\n🔢 Pack `{version}` · 💾 {_size_text(pack.get('file_size', 0))}",
                inline=True,
            )
        if len(packs) > 20:
            embed.set_footer(text=f"{len(packs)} Packs insgesamt · Anzeige auf 20 begrenzt")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="info", description="Details zu einem Resource Pack anzeigen")
    @app_commands.describe(name="Name des Resource Packs")
    async def info(self, interaction: discord.Interaction, name: str):
        pack = _db_get(name)
        if not pack:
            await interaction.response.send_message("❌ Resource Pack nicht gefunden.", ephemeral=True)
            return
        version = pack["pack_version_min"]
        if pack["pack_version_min"] != pack["pack_version_max"]:
            version += f" – {pack['pack_version_max']}"
        embed = discord.Embed(title=f"🎨 {pack['name']}", color=discord.Color.blurple())
        if pack.get("description"):
            embed.description = pack["description"]
        embed.add_field(name="Pack-Version", value=version, inline=True)
        embed.add_field(name="Minecraft", value=pack.get("minecraft_version") or "nicht angegeben", inline=True)
        embed.add_field(name="Größe", value=_size_text(pack.get("file_size", 0)), inline=True)
        embed.add_field(name="Entpackt", value=_size_text(pack.get("uncompressed_size", 0)), inline=True)
        embed.add_field(name="Dateien", value=f"{pack.get('file_count', 0):,}", inline=True)
        embed.add_field(name="Icon", value="✅ pack.png" if pack.get("has_icon") else "–", inline=True)
        if pack.get("category"):
            embed.add_field(name="Kategorie", value=pack["category"], inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="remove", description="Resource Pack löschen")
    @app_commands.describe(name="Name des Resource Packs")
    async def remove(self, interaction: discord.Interaction, name: str):
        if not await self._require_manager(interaction):
            return
        pack = _db_get(name)
        if not pack:
            await interaction.response.send_message("❌ Resource Pack nicht gefunden.", ephemeral=True)
            return
        try:
            p = Path(pack["file_path"]).resolve()
            root = RESOURCEPACKS_DIR.resolve()
            if p != root and not str(p).startswith(str(root) + str(Path("/"))):
                raise ValueError("Dateipfad liegt außerhalb des Resource-Pack-Ordners.")
            if p.is_dir():
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
        except Exception as exc:
            logger.warning("Resource-Pack-Dateilöschung fehlgeschlagen: %s", exc)
            await interaction.response.send_message("❌ Datei konnte nicht sicher gelöscht werden.", ephemeral=True)
            return
        _db_remove(int(pack["id"]))
        await interaction.response.send_message(f"🗑️ **{pack['name']}** wurde entfernt.", ephemeral=True)

    @remove.autocomplete("name")
    async def remove_autocomplete(self, interaction: discord.Interaction, current: str):
        return [
            app_commands.Choice(name=p["name"][:100], value=p["name"])
            for p in _db_list(25)
            if current.lower() in p["name"].lower()
        ][:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(ResourcePacksCog(bot))
