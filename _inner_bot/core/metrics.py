"""Process-local metrics with bounded memory.

Only numeric counters/timings are stored; no user content or credentials.
"""
from __future__ import annotations

import statistics
import time
from collections import Counter, deque

_COMMANDS = Counter()
_ERRORS = Counter()
_LATENCIES = deque(maxlen=1000)
_STARTED = time.time()


def command_result(name: str, ok: bool) -> None:
    _COMMANDS[(name, "ok" if ok else "error")] += 1
    if not ok:
        _ERRORS[name] += 1


def observe_latency(milliseconds: float) -> None:
    if milliseconds >= 0:
        _LATENCIES.append(float(milliseconds))


def snapshot() -> dict:
    values = list(_LATENCIES)
    ordered = sorted(values)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)] if ordered else 0.0
    return {
        "uptime_seconds": max(0, time.time() - _STARTED),
        "commands": {f"{name}:{state}": count for (name, state), count in _COMMANDS.items()},
        "errors": dict(_ERRORS),
        "latency": {
            "samples": len(values),
            "average_ms": statistics.fmean(values) if values else 0.0,
            "p95_ms": p95,
        },
    }
