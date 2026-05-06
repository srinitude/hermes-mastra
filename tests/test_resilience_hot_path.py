"""R01 RED: hot paths stay fast with fault-injection surfaces enabled."""

from __future__ import annotations

from pathlib import Path

from provider import MastraMemoryProvider
from recall_cache import RecallCache
from tests.helpers.chaos import elapsed_ms
from tests.helpers.fault_injectors import SlowCallClient


def test_recall_cache_supports_concurrent_profile_thread_rotation():
    cache = RecallCache(max_entries=3)
    for i in range(5):
        cache.store(f"profile-{i}", "thread", f"text-{i}")
    assert cache.get("profile-4", "thread") == "text-4"
    assert cache.get("profile-0", "thread") == ""
    assert cache.size <= 3


def test_every_hook_stays_under_budget_with_slow_client_and_fault_config():
    p = MastraMemoryProvider()
    p._client = SlowCallClient(delay=0.5)
    p._profile = "profile"
    p._thread = "thread"
    p._cfg = {"recall_top_k": 4, "fault_injection": True}
    calls = [
        lambda: p.prefetch("q", session_id="thread"),
        lambda: p.sync_turn("u", "a", session_id="thread"),
        lambda: p.on_pre_compress([{"role": "user", "content": "x"}]),
        lambda: p.on_session_end([]),
        lambda: p.on_memory_write("add", "memory", "x"),
        lambda: p.on_delegation("task", "result"),
    ]
    assert max(elapsed_ms(call) for call in calls) < 100


def test_benchmark_declares_resilience_mode():
    src = Path("scripts/benchmark.py").read_text(encoding="utf-8")
    assert "bench:resilience" in src or "resilience" in src
    assert "fault" in src and "p99" in src
