"""Gemeinsame Test-Initialisierung."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "_inner_bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))
