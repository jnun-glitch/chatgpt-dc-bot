"""Mute-Immune: User-IDs aus mute_immune.txt laden (eine pro Zeile, # = Kommentar)."""
from pathlib import Path
from core.config import BOT_DIR
from core.logging import logger

_IMMUNE_DEFAULT = [
    '1265657381476630589',  # OWNER
]


def _load_immune() -> set:
    """Lädt User-IDs aus mute_immune.txt (eine pro Zeile, # = Kommentar)."""
    path = BOT_DIR / 'mute_immune.txt'
    try:
        ids = set()
        for raw in path.read_text(encoding='utf-8').splitlines():
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.isdigit():
                ids.add(int(line))
        if ids:
            return ids
    except FileNotFoundError:
        logger.warning('mute_immune.txt nicht gefunden – verwende eingebettete Liste')
    except Exception as e:
        logger.warning(f'mute_immune.txt konnte nicht geladen werden ({e}) – verwende eingebettete Liste')
    return set(_IMMUNE_DEFAULT)


IMMUNE_USERS: set = _load_immune()


def is_mute_immune(user_id: int) -> bool:
    """Prüft ob ein User vor Auto-Mute geschützt ist."""
    return user_id in IMMUNE_USERS


def add_immune(user_id: int):
    """Fügt einen User zur Whitelist hinzu und speichert in Datei."""
    IMMUNE_USERS.add(user_id)
    _save()


def remove_immune(user_id: int):
    """Entfernt einen User von der Whitelist und speichert in Datei."""
    IMMUNE_USERS.discard(user_id)
    _save()


def _save():
    """Speichert die aktuelle Liste in mute_immune.txt."""
    path = BOT_DIR / 'mute_immune.txt'
    try:
        lines = ['# Mute-Immune Whitelist', '# Eine User-ID pro Zeile', '#']
        for uid in sorted(IMMUNE_USERS):
            lines.append(str(uid))
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    except Exception as e:
        logger.warning(f'mute_immune.txt konnte nicht gespeichert werden: {e}')
