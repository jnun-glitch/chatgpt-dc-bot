"""Lightweight in-process monitoring for ScratchAI.

No external service is required. The module keeps bounded counters and timing
samples so the bot can expose useful diagnostics without leaking message
content or secrets.
"""
from __future__ import annotations

import time
from collections import Counter, deque
from threading import Lock

_MAX_SAMPLES = 200
_MAX_EVENTS = 500

_lock = Lock()
_started_at = time.time()
_counters: Counter[str] = Counter()
_latency_ms: deque[float] = deque(maxlen=_MAX_SAMPLES)
_events: deque[dict] = deque(maxlen=_MAX_EVENTS)


def increment(name: str, amount: int = 1) -> None:
    """Increment a bounded metric counter."""
    if not name:
        return
    with _lock:
        _counters[str(name)] += amount


def observe_latency(name: str, milliseconds: float) -> None:
    """Record command/system latency and increment its observation counter."""
    try:
        value = max(0.0, float(milliseconds))
    except (TypeError, ValueError):
        return
    with _lock:
        _latency_ms.append(value)
        _counters[f"latency.{name}"] += 1


def record_event(kind: str, **data) -> None:
    """Record a small diagnostic event; never store message content/tokens."""
    if not kind:
        return
    safe = {"type": str(kind), "time": time.time()}
    for key in ("command", "status", "source", "guild_id"):
        if key in data and data[key] is not None:
            safe[key] = str(data[key])[:120]
    with _lock:
        _events.append(safe)
        _counters[f"event.{kind}"] += 1


def snapshot() -> dict:
    """Return a JSON-friendly diagnostic snapshot."""
    with _lock:
        samples = list(_latency_ms)
        counters = dict(_counters)
        events = list(_events)[-20:]
    avg = sum(samples) / len(samples) if samples else None
    p95 = None
    if samples:
        ordered = sorted(samples)
        p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {
        "uptime_seconds": round(max(0.0, time.time() - _started_at), 1),
        "counters": counters,
        "latency": {
            "samples": len(samples),
            "avg_ms": round(avg, 1) if avg is not None else None,
            "p95_ms": round(p95, 1) if p95 is not None else None,
        },
        "recent_events": events,
    }


def reset() -> None:
    """Reset metrics; intended for tests only."""
    with _lock:
        _counters.clear()
        _latency_ms.clear()
        _events.clear()
