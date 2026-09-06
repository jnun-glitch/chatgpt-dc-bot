from core import monitoring


def test_monitoring_snapshot_is_bounded_and_safe():
    monitoring.reset()
    monitoring.increment("commands.completed", 3)
    monitoring.observe_latency("test", 10)
    monitoring.observe_latency("test", 30)
    monitoring.record_event("command", command="system diagnostics", guild_id=123)

    snap = monitoring.snapshot()
    assert snap["counters"]["commands.completed"] == 3
    assert snap["latency"]["avg_ms"] == 20.0
    assert snap["latency"]["p95_ms"] == 30.0
    assert snap["recent_events"][-1]["command"] == "system diagnostics"
    assert "content" not in snap["recent_events"][-1]
    assert "token" not in str(snap).lower()


def test_monitoring_rejects_invalid_latency():
    monitoring.reset()
    monitoring.observe_latency("bad", "not-a-number")
    assert monitoring.snapshot()["latency"]["samples"] == 0
