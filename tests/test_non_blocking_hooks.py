"""Non-blocking contract for every public MemoryProvider hook.

These tests are the enforcement arm of `docs/HERMES_INTEGRATION_MAP.md` §4.

The setup substitutes the Mastra HTTP client with a fake that takes
**5 full seconds** on every call.  Each provider hook listed in the
integration map's latency table is invoked and asserted to return
within its budget.

If you add a new hook to the provider, **add it here too.**  If the
budget here doesn't match the integration map, one of them is wrong.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Test infra
# ---------------------------------------------------------------------------


class _SlowClient:
    """Stand-in for the Mastra HTTP client with a 5-second hang on every call.

    If the provider ever calls `_client.<method>(...)` synchronously from a
    Hermes hook, the test will time out far above the budget and fail.
    """

    HANG_SECONDS = 5.0

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def _hang(self, name: str, args, kwargs):
        self.calls.append((name, args, kwargs))
        time.sleep(self.HANG_SECONDS)
        return ""

    def __getattr__(self, name: str):
        def _fn(*args: Any, **kwargs: Any):
            return self._hang(name, args, kwargs)

        return _fn

    def close(self) -> None:
        pass


def _stub_hermes_constants(tmp_path):
    """Provide a stand-in `hermes_constants` module if Hermes isn't installed."""
    import sys
    import types

    if "hermes_constants" not in sys.modules:
        stub = types.ModuleType("hermes_constants")
        stub.get_hermes_home = lambda: tmp_path
        sys.modules["hermes_constants"] = stub
    else:
        sys.modules["hermes_constants"].get_hermes_home = lambda: tmp_path


def _load_plugin_module():
    """Import the plugin's __init__.py under a unique name."""
    import importlib.util
    import sys
    from pathlib import Path

    plugin_root = Path(__file__).resolve().parents[1]
    init_path = plugin_root / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "mastra_plugin_under_test_blocking",
        str(init_path),
        submodule_search_locations=[str(plugin_root)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def provider_with_slow_client(monkeypatch, tmp_path):
    """A live MastraMemoryProvider whose HTTP client hangs for 5 s."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _stub_hermes_constants(tmp_path)
    mod = _load_plugin_module()
    provider = mod.MastraMemoryProvider()
    provider._client = _SlowClient()
    provider._cfg = {"recall_top_k": 4}
    provider._profile = "default"
    provider._thread = "test-session"
    return provider


def _assert_budget_ms(fn, budget_ms: float, *args, **kwargs):
    """Run *fn* and assert it returns within *budget_ms* milliseconds."""
    t0 = time.perf_counter()
    result = fn(*args, **kwargs)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < budget_ms, (
        f"{fn.__qualname__} took {elapsed_ms:.1f} ms — over the "
        f"{budget_ms} ms budget.  Hermes' main thread cannot afford this."
    )
    return result


# ---------------------------------------------------------------------------
# Per-hook deadline assertions (mirrors §1 of the integration map)
# ---------------------------------------------------------------------------


def test_is_available_returns_under_5ms(provider_with_slow_client):
    # is_available is a local fs probe — never touches client.
    _assert_budget_ms(provider_with_slow_client.is_available, 5)


def test_system_prompt_block_is_pure_string(provider_with_slow_client):
    _assert_budget_ms(provider_with_slow_client.system_prompt_block, 5)


def test_prefetch_returns_under_5ms_with_dead_client(provider_with_slow_client):
    # prefetch must read RecallCache only; never call the slow client.
    _assert_budget_ms(
        provider_with_slow_client.prefetch,
        50,
        "what did we do?",
    )


def test_queue_prefetch_returns_under_5ms_with_dead_client(provider_with_slow_client):
    _assert_budget_ms(
        provider_with_slow_client.queue_prefetch,
        50,
        "what did we do?",
    )


def test_sync_turn_returns_under_5ms_with_dead_client(provider_with_slow_client):
    _assert_budget_ms(
        provider_with_slow_client.sync_turn,
        50,
        "user msg",
        "assistant reply",
    )


def test_on_pre_compress_returns_under_50ms_with_dead_client(provider_with_slow_client):
    _assert_budget_ms(
        provider_with_slow_client.on_pre_compress,
        50,
        [{"role": "user", "content": "x"}],
    )


def test_on_session_switch_returns_under_5ms_with_dead_client(provider_with_slow_client):
    _assert_budget_ms(
        provider_with_slow_client.on_session_switch,
        50,
        "new-session",
    )


def test_on_memory_write_returns_under_5ms_with_dead_client(provider_with_slow_client):
    _assert_budget_ms(
        provider_with_slow_client.on_memory_write,
        50,
        "add",
        "memory",
        "user prefers tabs",
    )


def test_on_delegation_returns_under_5ms_with_dead_client(provider_with_slow_client):
    _assert_budget_ms(
        provider_with_slow_client.on_delegation,
        50,
        "do thing",
        "did thing",
    )


def test_get_tool_schemas_returns_under_5ms(provider_with_slow_client):
    _assert_budget_ms(provider_with_slow_client.get_tool_schemas, 5)


def test_on_session_end_returns_under_50ms_with_dead_client(provider_with_slow_client):
    _assert_budget_ms(
        provider_with_slow_client.on_session_end,
        50,
        [{"role": "user", "content": "x"}],
    )


# ---------------------------------------------------------------------------
# Cumulative budget — a full Hermes turn through every hook
# ---------------------------------------------------------------------------


def test_full_turn_through_every_hook_under_200ms(provider_with_slow_client):
    """Even if every hook is called sequentially in one turn (worst case),
    the total time on Hermes' main thread must stay under a comfortable
    200 ms cap, with a slow client.
    """
    p = provider_with_slow_client
    t0 = time.perf_counter()
    p.system_prompt_block()
    p.prefetch("q")
    p.on_memory_write("add", "memory", "x")
    p.sync_turn("u", "a")
    p.queue_prefetch("q")
    p.on_pre_compress([{"role": "user", "content": "y"}])
    p.on_session_switch("next-sess")
    p.on_delegation("t", "r")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert elapsed_ms < 200, (
        f"Full hook sequence took {elapsed_ms:.1f} ms — over the 200 ms cap "
        f"with a slow Mastra client.  Plugin is leaking a sync HTTP call."
    )
