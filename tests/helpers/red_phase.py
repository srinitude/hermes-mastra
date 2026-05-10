"""Shared helpers for the RED-phase integration tests.

Each helper is intentionally tiny so the failing-assertion tests stay
within the project's per-construct LOC budget.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path


def await_client(provider, deadline_seconds: float = 10.0) -> None:
    deadline = time.monotonic() + deadline_seconds
    while time.monotonic() < deadline and provider._client is None:
        time.sleep(0.05)


def _ensure_server_up() -> None:
    """Restart the live Mastra server if a prior test (e.g. R07) stopped it."""
    try:
        from server_manager import is_running, start_server
    except ImportError:
        return
    if is_running():
        return
    try:
        start_server(wait_seconds=10.0)
    except Exception:
        return


def bring_up(session_id: str, hermes_home: str | None = None):
    from __init__ import MastraMemoryProvider

    home = hermes_home if hermes_home is not None else os.environ.get("HERMES_HOME") or ""
    _ensure_server_up()
    provider = MastraMemoryProvider()
    provider.initialize(session_id, hermes_home=home)
    await_client(provider)
    assert provider._client is not None, (
        f"provider did not come up against live server (home={home!r})"
    )
    return provider


def latency_budget_p99_ms(hook_name: str) -> float:
    contract_path = Path(__file__).resolve().parents[2] / "analysis" / "latency-budget.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    return float(contract["contract"][hook_name]["p99_ms"])


def perf_baseline() -> dict:
    artifact_path = Path(__file__).resolve().parents[2] / "analysis" / "perf-baseline.json"
    return json.loads(artifact_path.read_text(encoding="utf-8"))


def percentile(values: list[float], pct: float) -> float:
    s = sorted(values)
    n = len(s)
    return s[max(0, min(n - 1, round(pct / 100.0 * (n - 1))))]


def await_working_memory(client, profile: str, needle: str, deadline_seconds: float) -> str:
    deadline = time.monotonic() + deadline_seconds
    last = ""
    while time.monotonic() < deadline:
        last = client.get_working_memory(profile)
        if needle in last:
            return last
        time.sleep(0.05)
    return last


def await_breaker(client_obj, target_state: str, deadline_seconds: float) -> str:
    deadline = time.monotonic() + deadline_seconds
    last = ""
    while time.monotonic() < deadline:
        last = client_obj._breaker.state
        if last == target_state:
            return last
        time.sleep(0.05)
    return last


def replay_log_paths(home: str | None = None) -> list[Path]:
    base = home if home is not None else os.environ.get("HERMES_HOME")
    if not base:
        return []
    return sorted((Path(base) / "data" / "mastra").glob("replay-*.ndjson"))
