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


DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
VERIFY_CHANNEL_ID = _env_int("VERIFY_CHANNEL_ID", 0)
VERIFIED_ROLE_NAME = os.environ.get("VERIFIED_ROLE_NAME", "Verified")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://scratch-ai-24bv.onrender.com")
BOT_SECRET = os.environ.get("BOT_SECRET", "")
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "http://localhost:5678/webhook/ticket-analyze")
OWNER_ID = _env_int("OWNER_ID", 0)
ADMIN_LOG_CHANNEL_ID = _env_int("ADMIN_LOG_CHANNEL_ID", 1518606440472776858)

# Persistente Bot-Daten
DATA_DIR = Path(os.environ.get("DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
TRANSCRIPTS_DIR = Path(os.environ.get("TRANSCRIPTS_DIR", str(DATA_DIR / "transcripts"))).resolve()
TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = Path(os.environ.get("DB_PATH", str(DATA_DIR / "discord_verify.db"))).resolve()

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
