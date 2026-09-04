"""Zentrales Logging für den Bot."""
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

# Logging darf config.py nicht importieren, weil config.py selbst den Logger
# für Warnungen beim Einlesen der Umgebungsvariablen benötigt. Dadurch vermeiden
# wir einen Circular Import beim Bot-Start.
BOT_DIR = Path(__file__).resolve().parent.parent

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
