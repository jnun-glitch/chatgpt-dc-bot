import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "_inner_bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from cogs.voice import VoiceCog  # noqa: E402


def test_voice_safe_name_removes_path_like_characters():
    value = VoiceCog._safe_name('../Speaker:Name?.txt')
    assert '/' not in value
    assert '\\' not in value
    assert '..' not in value
    assert value


def test_voice_safe_name_has_reasonable_length_limit():
    value = VoiceCog._safe_name('A' * 500)
    assert len(value) <= 60
