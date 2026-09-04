"""Zentrale Konfiguration: Env-Variablen, Pfade, Konstanten."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Pfade zuerst definieren (logging.py importiert BOT_DIR -> Reihenfolge vermeidet Circular Import)
BOT_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BOT_DIR.parent

# .env explizit laden (unabhängig vom Arbeitsverzeichnis)
load_dotenv(BOT_DIR / '.env', override=False)

from core.logging import logger  # noqa: E402


def _env_int(name: str, default: int) -> int:
    """Liest eine Env-Variable als int; bei ungültigem Wert wird der Default verwendet."""
    raw = os.environ.get(name, '')
    if raw.strip() == '':
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        logger.warning(f'Env-Variable {name} ist keine gültige Zahl ("{raw}") – Default {default} verwendet.')
        return default


DISCORD_TOKEN = os.environ.get('DISCORD_TOKEN', '')
VERIFY_CHANNEL_ID = _env_int('VERIFY_CHANNEL_ID', 0)
VERIFIED_ROLE_NAME = os.environ.get('VERIFIED_ROLE_NAME', 'Verified')
WEBAPP_URL = os.environ.get('WEBAPP_URL', 'https://scratch-ai-24bv.onrender.com')
BOT_SECRET = os.environ.get('BOT_SECRET', '')
N8N_WEBHOOK_URL = os.environ.get('N8N_WEBHOOK_URL', 'http://localhost:5678/webhook/ticket-analyze')
OWNER_ID = _env_int('OWNER_ID', 0)
ADMIN_LOG_CHANNEL_ID = _env_int('ADMIN_LOG_CHANNEL_ID', 1518606440472776858)

# Musik (Music-Cog)
MUSIC_DISABLED_MSG = (
    'Die Musik-Funktion ist auf diesem Server deaktiviert.\n'
    '**Fehlend:** `ffmpeg` (nicht installiert).\n'
    'Installiere ffmpeg (z.B. via `winget install ffmpeg` oder https://ffmpeg.org) '
    'und starte den Bot neu – dann funktionieren /play, /skip, /stop und /queue.'
)
DEFAULT_VOLUME = 0.5

# Level-Rollen: Automatische Rollen bei bestimmten Leveln
LEVEL_ROLES = {
    5: 'Scratcher',
    10: 'Pro',
    20: 'Master',
}

DB_PATH = Path(os.environ.get('DB_PATH', str(PROJECT_ROOT / 'data' / 'discord_verify.db')))


def _is_owner(user) -> bool:
    """Prüft ob ein Discord-User der Bot-Owner ist."""
    return bool(OWNER_ID) and str(user.id) == str(OWNER_ID)
