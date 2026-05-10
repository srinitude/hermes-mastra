"""B03 — circuit-breaker integration tests (R07)."""

from __future__ import annotations

import time

import pytest

from tests.helpers.red_phase import (
    await_breaker,
    bring_up,
    replay_log_paths,
)


def test_imports_circuit_breaker_surface() -> None:
    """Sanity smoke — the modules R07 / G04 will exercise are importable."""
    import circuit_breaker
    import client
    import provider_lifecycle


def _drive_turn(provider, idx: int) -> None:
    provider.sync_turn(f"r07 user msg {idx}", f"r07 assistant reply {idx}")
    provider.on_memory_write("add", "MEMORY.md", f"r07 fact {idx}", {})
    provider.prefetch(f"r07 query {idx}")


def _drive_outage(provider, outage_token: str) -> float:
    outage_start = time.monotonic()
    provider.on_memory_write("add", "MEMORY.md", outage_token, {"r07": True})
    for i in range(2, 7):
        _drive_turn(provider, i)
    return outage_start


def _measure_outage_prefetch(provider) -> tuple[float, str]:
    t0 = time.monotonic()
    result = provider.prefetch("r07 outage prefetch")
    return (time.monotonic() - t0) * 1000.0, result


def _assert_breaker_opened(provider, outage_start: float) -> None:
    state = await_breaker(provider._client, target_state="OPEN", deadline_seconds=1.0)
    elapsed = time.monotonic() - outage_start
    assert state == "OPEN", (
        f"circuit breaker did not open within 1 s of outage; state={state!r} after {elapsed:.2f}s"
    )


def _assert_prefetch_degraded(prefetch_ms: float, prefetch_result: str) -> None:
    assert prefetch_ms <= 5.0, (
        f"prefetch took {prefetch_ms:.2f} ms with server down (budget is 5 ms cache-only return)"
    )
    assert prefetch_result == "", (
        f"prefetch returned non-empty {prefetch_result!r} with server "
        "down; expected empty cache fallback"
    )


def _assert_replay_log_has_token(token: str) -> None:
    files = replay_log_paths()
    assert files, (
        "no $HERMES_HOME/data/mastra/replay-*.ndjson file written "
        "during the outage; the outage-time on_memory_write was "
        "silently dropped (A07 mandates a disk replay buffer)"
    )
    blob = "\n".join(p.read_text(encoding="utf-8") for p in files)
    assert token in blob, f"replay log exists but does not contain {token!r}; paths={files!r}"


@pytest.mark.integration
def test_red_graceful_degradation(mastra_client, mastra_server) -> None:
    """R07 — Mastra server hard-down must degrade gracefully.

    Failure mode today: hermes-mastra has no replay log — outage-time
    on_memory_write payloads are silently dropped by the circuit
    breaker. G04 wires a disk replay log so outage-time writes survive.
    """
    from server_manager import stop_server

    provider = bring_up("r07-graceful-degradation")
    try:
        for i in range(2):
            _drive_turn(provider, i)
        ok, _ = stop_server()
        assert ok, "stop_server did not signal a clean shutdown"
        outage_token = "r07_outage_token_grtwbqz"
        outage_start = _drive_outage(provider, outage_token)
        _assert_breaker_opened(provider, outage_start)
        prefetch_ms, prefetch_result = _measure_outage_prefetch(provider)
        _assert_prefetch_degraded(prefetch_ms, prefetch_result)
        time.sleep(1.0)  # let the runner queue drain whatever it can
        _assert_replay_log_has_token(outage_token)
    finally:
        provider.shutdown()
