"""Shared bounded runtime for ticket AI analysis."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable


class TicketAIRuntime:
    """Limit concurrent analyses and enforce a simple per-key cooldown."""

    def __init__(self, max_concurrency: int = 2, cooldown_seconds: int = 300):
        self.semaphore = asyncio.Semaphore(max(1, max_concurrency))
        self.cooldown_seconds = max(0, cooldown_seconds)
        self._last_run: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def run(self, key: str, func: Callable[[], Awaitable[str]], now: float | None = None) -> str:
        loop = asyncio.get_running_loop()
        current = loop.time() if now is None else now
        async with self._lock:
            last = self._last_run.get(key)
            if last is not None and current - last < self.cooldown_seconds:
                remaining = int(self.cooldown_seconds - (current - last)) + 1
                raise RuntimeError(f"cooldown:{remaining}")
            self._last_run[key] = current
        async with self.semaphore:
            return await func()
