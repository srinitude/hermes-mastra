"""R03 RED: supervised Bun subprocess auto-recovers without host blocking."""

from __future__ import annotations

import importlib
import importlib.util


def _module():
    spec = importlib.util.find_spec("supervisor")
    assert spec is not None, "supervisor.py must exist before GREEN"
    return importlib.import_module("supervisor")


def test_supervisor_detects_crash_and_caps_restart_burst():
    module = _module()
    clock = {"now": 0.0}
    restarts: list[float] = []
    sup = module.ServerSupervisor(max_restarts_per_minute=2, now=lambda: clock["now"])
    for _ in range(4):
        assert sup.record_crash(lambda: restarts.append(clock["now"])) is True
        clock["now"] += 1.0
    assert len(restarts) == 2
    assert sup.next_delay_seconds <= sup.max_backoff_seconds
    assert sup.host_hook_budget_ms < 100
