"""Load ScratchAI's local .env before application modules read os.environ.

Python imports sitecustomize during interpreter startup when this directory is on
sys.path, which makes direct `python bot.py` starts use `_inner_bot/.env` too.
"""
from pathlib import Path

from dotenv import load_dotenv

BOT_DIR = Path(__file__).resolve().parent
load_dotenv(BOT_DIR / ".env", override=False)
