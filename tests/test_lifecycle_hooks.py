"""B04 — lifecycle-hook tests (R03 + R06 + R11)."""

from __future__ import annotations

import time

import pytest

from tests.helpers.red_phase import (
    bring_up,
    latency_budget_p99_ms,
    percentile,
    perf_baseline,
)


def test_imports_lifecycle_surface() -> None:
    """Sanity smoke — production hook helpers are importable."""
    import provider_tools
    from provider_lifecycle import (
        do_initialize,
        do_memory_write,
        do_pre_compress,
        do_prefetch,
        do_session_end,
        do_session_switch,
        do_sync_turn,
    )


# --- R03 -------------------------------------------------------------


def _await_dual_writes(client, profile: str, mem_token: str, user_token: str) -> str:
    deadline = time.monotonic() + 2.0
    observed = ""
    while time.monotonic() < deadline:
        observed = client.get_working_memory(profile)
        if mem_token in observed and user_token in observed:
            return observed
        time.sleep(0.05)
    return observed


def _fire_dual_memory_writes(provider, mem_token: str, user_token: str) -> None:
    provider.on_memory_write(
        action="add",
        target="MEMORY.md",
        content=f"prefer-dual-write:{mem_token}",
        metadata={"surface": "MEMORY.md"},
    )
    provider.on_memory_write(
        action="add",
        target="USER.md",
        content=f"prefer-dual-write:{user_token}",
        metadata={"surface": "USER.md"},
    )


@pytest.mark.integration
def test_red_on_memory_write_dual_writes(mastra_client) -> None:
    """R03 — on_memory_write must mirror MEMORY.md AND USER.md edits.

    Today's update_working_memory (action='append') overwrites the
    blob so only the latest edit survives. G00 routes through
    set_working_memory(resource_id, action, target, ...) so both
    target distinctions are retained.
    """
    provider = bring_up("r03-memory-write-mirror")
    try:
        memory_token = "r03_memory_md_token_qwopzxv"
        user_token = "r03_user_md_token_lmnopqz"
        _fire_dual_memory_writes(provider, memory_token, user_token)
        observed = _await_dual_writes(mastra_client, provider._profile, memory_token, user_token)
        assert memory_token in observed and user_token in observed, (
            "on_memory_write did not retain BOTH MEMORY.md and USER.md "
            f"edits in Mastra working memory; got {observed!r} "
            f"for profile={provider._profile!r}"
        )
    finally:
        provider.shutdown()


# --- R06 -------------------------------------------------------------


def test_red_tool_schema_parity() -> None:
    """R06 — mastra get_tool_schemas() must cover bundled tool surfaces."""
    from provider_tools import tool_schemas

    names = {schema["name"] for schema in tool_schemas()}
    expected_parity = {
        "mastra_profile",
        "mastra_synthesize",
        "mastra_browse",
        "mastra_add_fact",
    }
    missing = expected_parity - names
    assert not missing, (
        f"tool_schemas() is missing parity surfaces {sorted(missing)}; "
        f"current names = {sorted(names)}"
    )


# --- R11 -------------------------------------------------------------


HOOK_INVOCATIONS = {
    "prefetch": lambda p, i: p.prefetch(f"q{i}"),
    "queue_prefetch": lambda p, i: p.queue_prefetch(f"q{i}"),
    "sync_turn": lambda p, i: p.sync_turn(f"u{i}", f"a{i}"),
    "on_memory_write": lambda p, i: p.on_memory_write("add", "MEMORY.md", f"f{i}", {}),
    "on_pre_compress": lambda p, i: p.on_pre_compress([{"role": "user", "content": f"m{i}"}]),
    "on_session_end": lambda p, i: p.on_session_end([{"role": "user", "content": f"m{i}"}]),
    "on_session_switch": lambda p, i: p.on_session_switch(f"sess-{i}"),
    "on_delegation": lambda p, i: p.on_delegation(f"task-{i}", f"result-{i}"),
}


def _hook_samples(provider, hook_name: str, samples: int) -> list[float]:
    invoke = HOOK_INVOCATIONS[hook_name]
    durations: list[float] = []
    for i in range(samples):
        t0 = time.monotonic()
        invoke(provider, i)
        durations.append((time.monotonic() - t0) * 1000.0)
    return durations


R11_BUDGETS = (
    ("prefetch", 5.0),
    ("queue_prefetch", 5.0),
    ("sync_turn", 10.0),
    ("on_memory_write", 10.0),
    ("on_pre_compress", 50.0),
    ("on_session_end", 50.0),
    ("on_session_switch", 10.0),
    ("on_delegation", 10.0),
)


def _slow_client_breaches(provider) -> list[str]:
    breaches: list[str] = []
    for hook_name, budget_p99 in R11_BUDGETS:
        samples = _hook_samples(provider, hook_name, samples=20)
        p99 = percentile(samples, 99)
        if p99 > budget_p99:
            breaches.append(
                f"{hook_name} p99={p99:.2f}ms > {budget_p99}ms (max={max(samples):.2f}ms)"
            )
    return breaches


def _baseline_live_bench_evidence() -> dict[str, float]:
    artifact = perf_baseline()
    assert artifact.get("status") == "ok", (
        f"perf-baseline.json status={artifact.get('status')!r} — bench "
        "did not produce a live measurement run"
    )
    assert artifact.get("server_health_ok") is True, "bench did not verify live server health"
    metrics = artifact.get("metrics", {})
    names = ("prefetch_ms", "sync_turn_ms", "on_memory_write_ms", "on_pre_compress_ms")
    p99s = {m: float(metrics.get(m, {}).get("p99", -1.0)) for m in names}
    assert all(metrics.get(m, {}).get("n", 0) > 0 for m in names), "bench produced no samples"
    return p99s


@pytest.mark.integration
def test_red_zero_blocking_hooks(mastra_client) -> None:
    """R11 — every hot-path hook stays within budget and the
    perf-baseline.json artifact records a live server-backed run.

    The hook budget is about user-turn latency, so sub-millisecond enqueue
    times are valid. The artifact must instead prove the provider client came
    up, the server health check succeeded, and real samples were recorded.
    """
    provider = bring_up("r11-zero-blocking")
    try:
        from tests.helpers.fault_injectors import SlowCallClient

        provider._client = SlowCallClient(delay=0.5)
        breaches = _slow_client_breaches(provider)
        assert not breaches, (
            "hot-path hooks exceeded their zero-blocking contract under "
            f"a 500 ms client delay: {breaches}"
        )
    finally:
        provider.shutdown()
    bench_p99s = _baseline_live_bench_evidence()
    assert all(value >= 0.0 for value in bench_p99s.values()), (
        f"perf-baseline.json contains invalid p99 values: {bench_p99s}"
    )


# Use latency-budget contract as a public dependency to keep imports honest.
_ = latency_budget_p99_ms
