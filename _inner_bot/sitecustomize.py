"""Early ScratchAI runtime setup.

Only environment loading belongs here. Slash-command routing is implemented
explicitly in ``bot.py`` so there is exactly one owner for application-command
compaction and no global monkey patch of discord.py internals is required.
"""
from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv

BOT_DIR = Path(__file__).resolve().parent
load_dotenv(BOT_DIR / ".env", override=False)
