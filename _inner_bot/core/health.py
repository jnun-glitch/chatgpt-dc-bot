"""Centralized health checks for the bot.

Checks are intentionally lightweight and safe: no secrets or message content are returned.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, asdict
from typing import Any

from core.logging import logger


@dataclass
class CheckResult:
    name: str
    ok: bool
    latency_ms: float | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


async def check_database() -> CheckResult:
    started = time.perf_counter()
    try:
        from core.db import get_db
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        conn.close()
        return CheckResult("database", True, (time.perf_counter() - started) * 1000, "ok")
    except Exception as exc:
        logger.exception("Database health check failed")
        return CheckResult("database", False, (time.perf_counter() - started) * 1000, type(exc).__name__)


async def check_ai() -> CheckResult:
    started = time.perf_counter()
    try:
        from core.ai import _get_ai
        ai = _get_ai()
        return CheckResult("ai", ai is not None, (time.perf_counter() - started) * 1000,
                           "ready" if ai is not None else "not ready")
    except Exception as exc:
        return CheckResult("ai", False, (time.perf_counter() - started) * 1000, type(exc).__name__)


async def run_health_checks(bot) -> list[CheckResult]:
    results = [CheckResult("discord", bot.is_ready(), 0.0, "ready" if bot.is_ready() else "not ready")]
    db, ai = await asyncio.gather(check_database(), check_ai())
    results.extend((db, ai))
    return results
