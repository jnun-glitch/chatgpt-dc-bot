"""Zentrale Konfiguration: Env-Variablen, Pfade, Konstanten."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Pfade zuerst definieren, bevor Logging importiert wird.
BOT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BOT_DIR.parent
load_dotenv(BOT_DIR / ".env", override=False)

from core.logging import logger  # noqa: E402


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    if raw.strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning('Env-Variable %s ist keine gültige Zahl ("%s") – Default %s verwendet.', name, raw, default)
        return default


def _env_text(name: str, default: str = "") -> str:
    """Return a trimmed env value, treating blank values as unset."""
    raw = os.environ.get(name, "")
    value = raw.strip()
    return value if value else default


DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
VERIFY_CHANNEL_ID = _env_int("VERIFY_CHANNEL_ID", 0)
VERIFIED_ROLE_NAME = _env_text("VERIFIED_ROLE_NAME", "Verified")
WEBAPP_URL = _env_text("WEBAPP_URL", "https://scratch-ai-24bv.onrender.com")
BOT_SECRET = _env_text("BOT_SECRET")
N8N_WEBHOOK_URL = _env_text("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/ticket-analyze")
OWNER_ID = _env_int("OWNER_ID", 0)
ADMIN_LOG_CHANNEL_ID = _env_int("ADMIN_LOG_CHANNEL_ID", 1518606440472776858)

# Persistente Bot-Daten. Leere Env-Werte gelten bewusst als "nicht gesetzt",
# damit z. B. DB_PATH= nicht versehentlich zum aktuellen Verzeichnis "." wird.
DATA_DIR = Path(_env_text("DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser().resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)

TRANSCRIPTS_DIR = Path(_env_text("TRANSCRIPTS_DIR", str(DATA_DIR / "transcripts"))).expanduser().resolve()
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = Path(_env_text("DB_PATH", str(DATA_DIR / "discord_verify.db"))).expanduser().resolve()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Musik
MUSIC_DISABLED_MSG = (
    "Die Musik-Funktion ist nicht verfügbar.\n"
    "**Benötigt:** FFmpeg, yt-dlp und PyNaCl.\n"
    "Nach der Installation den Bot neu starten."
)
DEFAULT_VOLUME = 0.5

LEVEL_ROLES = {
    5: "Scratcher",
    10: "Pro",
    20: "Master",
}


def _is_owner(user) -> bool:
    return bool(OWNER_ID) and str(user.id) == str(OWNER_ID)
