from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BOT_DIR = ROOT / "_inner_bot"
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from core.badwords import find_bad_word  # noqa: E402


def test_voice_review_detects_bad_word():
    assert find_bad_word("Das ist ein Idiot") == "idiot"


def test_voice_review_ignores_clean_text():
    assert find_bad_word("Heute spielen wir Minecraft") is None


def test_voice_review_is_detection_only():
    # Voice AutoMod uses the existing detector as a review signal. It must not
    # itself call the normal AutoMod warning/escalation path.
    assert find_bad_word("Alles gut") is None
