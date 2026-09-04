"""Zentrales Logging für den Bot."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv

# Logging wird vor den eigentlichen Anwendungsmodulen importiert. Deshalb lädt
# dieses Modul die lokale .env selbst, ohne config.py zu importieren.
BOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BOT_DIR / ".env", override=False)

_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

_file_handler = RotatingFileHandler(
    BOT_DIR / 'bot.log',
    maxBytes=5 * 1024 * 1024,
    backupCount=3,
    encoding='utf-8',
)
_file_handler.setFormatter(_formatter)
_stream_handler = logging.StreamHandler()
_stream_handler.setFormatter(_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[_file_handler, _stream_handler],
)
logger = logging.getLogger('ScratchGameDevAI')
