import asyncio

from core import metrics
from core.health import run_health_checks


class FakeBot:
    def is_ready(self):
        return True


def test_metrics_snapshot_records_results_and_latency():
    metrics.command_result("demo", True)
    metrics.command_result("demo", False)
    metrics.observe_latency(10)
    metrics.observe_latency(20)
    data = metrics.snapshot()
    assert data["commands"]["demo:ok"] >= 1
    assert data["commands"]["demo:error"] >= 1
    assert data["errors"]["demo"] >= 1
    assert data["latency"]["samples"] >= 2
    assert data["latency"]["p95_ms"] >= 10


def test_health_checks_have_expected_core_services():
    results = asyncio.run(run_health_checks(FakeBot()))
    names = {result.name for result in results}
    assert {"discord", "database", "ai"} <= names
