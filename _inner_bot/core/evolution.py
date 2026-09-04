"""AI-Evolution-Engine Loader."""
from core.logging import logger

_evolution_engine = None


def _get_evolution():
    global _evolution_engine
    if _evolution_engine is None:
        try:
            from ai_evolution.engine import EvolutionEngine
            _evolution_engine = EvolutionEngine()
        except Exception as e:
            logger.warning(f'Evolution Engine nicht verfügbar: {e}')
    return _evolution_engine
