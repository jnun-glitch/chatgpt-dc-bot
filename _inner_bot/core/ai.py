"""AI-System-Loader: Render-Chat-Client + Render-Gen-Client mit Auto-Recovery.

Der KI-Chat und der Spiel-Generator laufen über die Render-Webapp-API.
Lokale Modell-Instanzen existieren bewusst nicht mehr.
"""
import base64
import json
import threading
import asyncio
import urllib.parse
import urllib.request
from core.config import WEBAPP_URL
from core.logging import logger

_ai_instance = None
_ai_ready = False


def _looks_like_error_text(reply: str) -> bool:
    """Erkennt rohe JSON-/Fehler-Textbrocken, die nie an User gehen dürfen."""
    text = reply.strip()
    if not text:
        return True
    if text.startswith('{') and text.endswith('}'):
        return True
    if text.startswith('[') and text.endswith(']'):
        return True
    lowered = text.lower()
    if 'json parse failed' in lowered or 'partial_parse_failed' in lowered:
        return True
    if 'traceback' in lowered or 'unexpected keyword argument' in lowered:
        return True
    return False


def _safe_reply(reply, fallback: str) -> str:
    """Liefert immer einen sauberen String als Antwort."""
    if not isinstance(reply, str):
        reply = str(reply)
    if _looks_like_error_text(reply):
        logger.warning(f'Rohtext/Fehler wurde abgefangen und durch Fallback ersetzt: {reply[:200]}')
        return fallback
    return reply[:2000]


class RenderAIClient:
    """Leichtgewichtiger AI-Client: fragt die AI über die Render-Webapp-API."""

    def __init__(self):
        self.brain = None
        self._loaded = True

    def answer(self, message: str, lang: str = 'de', context: str | None = None) -> dict:
        payload = {'message': message, 'lang': lang}
        if context:
            payload['message'] = f'{message} [Kontext: {context}]'
        req = urllib.request.Request(
            f'{WEBAPP_URL}/api/chat',
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            reply = _safe_reply(
                data.get('reply', ''),
                'Die AI hat keine Antwort geliefert. Bitte stell die Frage etwas anders.',
            )
            return {'reply': reply, 'source': 'render', 'confidence': 0.9}
        except Exception as e:
            logger.warning(f'Render API Fehler: {e}')
            return {
                'reply': 'Die AI ist gerade nicht erreichbar. Bitte versuch es später erneut.',
                'source': 'render',
                'confidence': 0.0,
            }


class RenderGenClient:
    """Spiel-Generator via Render-Webapp-API (/api/ai_generate, /api/ai_analyze)."""

    def __init__(self):
        self.brain = None

    def _post(self, path: str, payload: dict, timeout: int = 120) -> dict:
        req = urllib.request.Request(
            f'{WEBAPP_URL}{path}',
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))

    def is_ready(self) -> bool:
        try:
            req = urllib.request.Request(f'{WEBAPP_URL}/health', method='GET')
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception as e:
            logger.warning(f'Render /health nicht erreichbar: {e}')
            return False

    def generate(self, text: str, session_id: str) -> tuple:
        """Generiert ein Spiel über die Web-App. Liefert (sb3_bytes, metadata)."""
        data = self._post('/api/ai_generate', {'text': text, 'session_id': session_id})
        if 'sb3_base64' not in data:
            raise RuntimeError(data.get('error') or 'Web-App hat kein SB3 geliefert.')
        sb3_bytes = base64.b64decode(data['sb3_base64'])
        metadata = {
            'features': data.get('features', []),
            'skill_level': data.get('skill_level', 'unbekannt'),
            'suggestions': data.get('suggestions', []),
            'details': {},
        }
        return sb3_bytes, metadata

    def analyze(self, text: str) -> dict:
        return self._post('/api/ai_analyze', {'text': text}, timeout=30)

    def suggest(self, session_id: str) -> dict:
        try:
            req = urllib.request.Request(
                f'{WEBAPP_URL}/api/brain/suggest?session_id={urllib.parse.quote(session_id)}',
                method='GET',
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            return data.get('suggestion') or {}
        except Exception as e:
            logger.warning(f'Brain-Suggest via Render fehlgeschlagen: {e}')
            return {}


def _init_ai_sync():
    """Init Render-Chat-Client (blocking, runs in thread)."""
    global _ai_instance, _ai_ready
    try:
        _ai_instance = RenderAIClient()
        _ai_ready = True
        logger.info('AI ChatRouter ready (Render API, kein lokales Modell)')
    except Exception as e:
        logger.error(f'Failed to init AI Chat: {e}')


async def _ai_recovery_loop(bot):
    """Automatisch AI neu laden wenn sie fehlgeschlagen sind."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(30)
        if not _ai_ready:
            logger.info('AI Chat nicht bereit - versuche Reinit...')
            threading.Thread(target=_init_ai_sync, daemon=True).start()


def _get_ai():
    return _ai_instance if _ai_ready else None


def _get_ai_gen():
    """Liefert immer einen Render-Gen-Client (kein lokales Modell mehr)."""
    return RenderGenClient()
