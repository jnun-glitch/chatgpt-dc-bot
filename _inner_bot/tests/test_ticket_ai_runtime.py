from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BOT_DIR = Path(__file__).resolve().parents[1]
if str(BOT_DIR) not in sys.path:
    sys.path.insert(0, str(BOT_DIR))

from core.ai_ticket_runtime import TicketAIRuntime


def test_ticket_ai_runtime_allows_first_run_and_blocks_cooldown():
    async def scenario():
        runtime = TicketAIRuntime(max_concurrency=2, cooldown_seconds=300)

        async def work():
            return "ok"

        assert await runtime.run("ticket-1", work, now=100.0) == "ok"
        try:
            await runtime.run("ticket-1", work, now=101.0)
        except RuntimeError as exc:
            assert str(exc).startswith("cooldown:")
        else:
            raise AssertionError("Expected cooldown")

    asyncio.run(scenario())


def test_ticket_ai_runtime_limits_parallel_work():
    async def scenario():
        runtime = TicketAIRuntime(max_concurrency=1, cooldown_seconds=0)
        active = 0
        peak = 0

        async def work():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return "ok"

        await asyncio.gather(
            runtime.run("a", work),
            runtime.run("b", work),
            runtime.run("c", work),
        )
        assert peak == 1

    asyncio.run(scenario())
