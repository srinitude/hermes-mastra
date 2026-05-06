#!/usr/bin/env python3
"""Benchmark suite for the mastra plugin.

Answers four concrete questions:

  Q1. How much overhead does this plugin add per Hermes turn?
  Q2. What happens when Mastra is slow / unreachable?
  Q3. How many concurrent writes can the background queue absorb?
  Q4. Does the recall cache stay fresh under a realistic turn loop?

For each question we compare against a NAIVE baseline — what hook latency
would look like if the plugin synchronously awaited every HTTP call —
so the value of the cache + bounded async queue is visible.

Run via:  mise run bench
        ⇒  prints a markdown table + writes references/last-benchmark.json
           so CI / future contributors can detect regressions.

Resilience mode (`mise run bench:resilience`) injects fault scenarios and
asserts hot-path p99 stays under the 100ms contract budget.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Stub the Hermes-only deps so this script runs standalone.
import types  # noqa: E402

if "agent" not in sys.modules:
    sys.modules["agent"] = types.ModuleType("agent")
if "agent.memory_provider" not in sys.modules:
    mp = types.ModuleType("agent.memory_provider")
    mp.MemoryProvider = type("S", (), {})
    sys.modules["agent.memory_provider"] = mp
if "tools" not in sys.modules:
    sys.modules["tools"] = types.ModuleType("tools")
if "tools.registry" not in sys.modules:
    reg = types.ModuleType("tools.registry")
    reg.tool_error = lambda m: m
    sys.modules["tools.registry"] = reg

import async_runner  # noqa: E402
import provider  # noqa: E402

NAIVE_HTTP_LATENCY_MS = 500


def _slow_client(latency_seconds: float, recall_text: str = "obs A\nobs B") -> MagicMock:
    """A mock client where every public method sleeps `latency_seconds`.

    `recall_text` is what `recall()` returns — non-empty by default so the
    cache actually populates and we measure realistic prefetch behaviour.
    """

    def _slow(value: Any = ""):
        def _impl(*args, **kwargs):
            if latency_seconds > 0:
                time.sleep(latency_seconds)
            return value

        return _impl

    c = MagicMock()
    c.health.side_effect = _slow({"ok": True})
    c.recall.side_effect = _slow(recall_text)
    c.save_turn.side_effect = _slow(True)
    c.write_observation.side_effect = _slow(True)
    c.update_working_memory.side_effect = _slow(True)
    c.flush.side_effect = _slow(True)
    return c


def _make_provider(client: MagicMock) -> Any:
    p = provider.MastraMemoryProvider()
    p._client = client
    p._cfg = {"recall_top_k": 4}
    p._profile = "bench"
    p._thread = "bench-thread"
    p._cron_skipped = False
    return p


# ---------------------------------------------------------------------------
# Q1 + Q2: hot-path latency, plugin vs naive baseline
# ---------------------------------------------------------------------------


def _ms(seconds: float) -> float:
    return seconds * 1000.0


def _percentiles(samples: list[float]) -> dict[str, float]:
    samples_sorted = sorted(samples)
    n = len(samples_sorted)

    def pct(q: float) -> float:
        idx = max(0, min(int(n * q), n - 1))
        return _ms(samples_sorted[idx])

    return {
        "min_ms": round(_ms(samples_sorted[0]), 4),
        "p50_ms": round(pct(0.50), 4),
        "p95_ms": round(pct(0.95), 4),
        "p99_ms": round(pct(0.99), 4),
        "max_ms": round(_ms(samples_sorted[-1]), 4),
    }


def _time_call(fn: Callable[[], Any], iterations: int = 200) -> dict[str, float]:
    samples: list[float] = []
    # Warm-up to populate import caches + prime the recall cache.
    for _ in range(10):
        fn()
    # Drain background work between warm-up and measurement so we don't
    # confuse timing with whatever the warm-up scheduled.
    time.sleep(0.05)
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return _percentiles(samples)


def bench_hot_path() -> dict[str, Any]:
    """For each hot-path hook, report plugin vs naive sync baseline.

    The naive baseline is what the latency WOULD be if the hook awaited
    the HTTP call inline (i.e. the obvious implementation). We compute it
    as `latency_seconds` for write hooks and recall.
    """
    fast_client = _slow_client(0.0)
    slow_client = _slow_client(NAIVE_HTTP_LATENCY_MS / 1000.0)

    # Plugin paths use the async runner — measurements include enqueue cost.
    p_fast = _make_provider(fast_client)
    p_slow = _make_provider(slow_client)

    cases: dict[str, tuple[Callable[[], Any], Callable[[], Any]]] = {
        "prefetch": (
            lambda: p_fast.prefetch("anything"),
            lambda: p_slow.prefetch("anything"),
        ),
        "sync_turn": (
            lambda: p_fast.sync_turn("u", "a"),
            lambda: p_slow.sync_turn("u", "a"),
        ),
        "on_pre_compress": (
            lambda: p_fast.on_pre_compress([]),
            lambda: p_slow.on_pre_compress([]),
        ),
        "on_session_end": (
            lambda: p_fast.on_session_end([]),
            lambda: p_slow.on_session_end([]),
        ),
        "on_memory_write": (
            lambda: p_fast.on_memory_write("add", "MEMORY.md", "x"),
            lambda: p_slow.on_memory_write("add", "MEMORY.md", "x"),
        ),
        "on_delegation": (
            lambda: p_fast.on_delegation("t", "r"),
            lambda: p_slow.on_delegation("t", "r"),
        ),
    }

    results: dict[str, Any] = {}
    for name, (fast_fn, slow_fn) in cases.items():
        results[name] = {
            "fast_client": _time_call(fast_fn, iterations=200),
            "slow_client_500ms_http": _time_call(slow_fn, iterations=50),
            "naive_baseline_p50_ms": NAIVE_HTTP_LATENCY_MS,
        }

    p_fast.shutdown()
    p_slow.shutdown()
    async_runner.reset()
    return results


# ---------------------------------------------------------------------------
# Q3: runner throughput
# ---------------------------------------------------------------------------


def bench_runner_throughput() -> dict[str, Any]:
    """Two regimes:

    A. Sustained — workers can keep up; measures real throughput.
    B. Burst overflow — producer floods faster than workers drain;
       measures how the bounded queue's drop-oldest policy behaves.
    """
    results: dict[str, Any] = {}

    # ---- A. Sustained: small batches with explicit drain between -------
    # The bounded queue (size=256) is sized for steady-state agent traffic,
    # not benchmark floods. Submit batches that fit, drain, repeat — that's
    # the realistic shape of agent-driven work.
    async_runner.reset()
    counter_a = {"n": 0}

    def _quick():
        counter_a["n"] += 1

    sustained_total = 5_000
    batch_size = 200  # well under DEFAULT_QUEUE_SIZE
    t0 = time.perf_counter()
    runner = async_runner.get_runner()
    for batch_start in range(0, sustained_total, batch_size):
        for _ in range(batch_size):
            async_runner.submit(_quick)
        # Wait for this batch to drain before submitting the next one;
        # this is what an agent loop actually does (one turn at a time).
        runner.drain(timeout=5.0)
    async_runner.shutdown(wait=10.0)
    sustained_elapsed = time.perf_counter() - t0
    results["sustained"] = {
        "jobs_submitted": sustained_total,
        "jobs_delivered": counter_a["n"],
        "delivery_rate_pct": round(100.0 * counter_a["n"] / sustained_total, 2),
        "wall_seconds": round(sustained_elapsed, 3),
        "throughput_jobs_per_sec": round(counter_a["n"] / max(sustained_elapsed, 0.001)),
    }

    # ---- B. Burst overflow: producer outruns workers; verify drop-oldest -
    async_runner.reset()
    counter_b = {"n": 0}

    def _quick_b():
        counter_b["n"] += 1

    burst_total = 10_000
    t0 = time.perf_counter()
    for _ in range(burst_total):
        async_runner.submit(_quick_b)
    enqueue_elapsed = time.perf_counter() - t0
    async_runner.shutdown(wait=10.0)
    delivered = counter_b["n"]
    results["burst_overflow"] = {
        "jobs_submitted": burst_total,
        "jobs_delivered": delivered,
        "delivery_rate_pct": round(100.0 * delivered / burst_total, 2),
        "enqueue_total_ms": round(_ms(enqueue_elapsed), 2),
        "enqueue_per_job_us": round(enqueue_elapsed * 1_000_000 / burst_total, 2),
        "note": (
            f"Bounded queue drops oldest when full (size={async_runner.DEFAULT_QUEUE_SIZE}). "
            "A delivery_rate <100% under burst is the documented overflow policy — "
            "producers stay non-blocking by dropping pending writes."
        ),
    }
    return results


# ---------------------------------------------------------------------------
# Q4: cache freshness across a simulated turn loop
# ---------------------------------------------------------------------------


def bench_cache_freshness() -> dict[str, Any]:
    """Simulate 200 turns. Each turn: prefetch (read cache), sync_turn (write).
    The Mastra recall takes 80ms per call. Measure how often prefetch
    returned non-empty (= cache was warm).
    """
    async_runner.reset()
    versions = [{"n": 0}]

    def _slow_recall(*args, **kwargs):
        time.sleep(0.08)
        versions[0]["n"] += 1
        return f"observation-version-{versions[0]['n']}"

    client = _slow_client(0.0)
    client.recall.side_effect = _slow_recall

    p = _make_provider(client)

    hits, misses = 0, 0
    n_turns = 200
    for _ in range(n_turns):
        text = p.prefetch("any")
        if text:
            hits += 1
        else:
            misses += 1
        p.sync_turn("user msg", "assistant reply")
        time.sleep(0.005)  # turn pacing

    p.shutdown()
    async_runner.reset()
    return {
        "turns": n_turns,
        "cache_hits": hits,
        "cache_misses": misses,
        "hit_rate_pct": round(100.0 * hits / n_turns, 2),
        "background_recalls_completed": versions[0]["n"],
    }


# ---------------------------------------------------------------------------
# Resilience mode: fault-injected hot-path budget
# ---------------------------------------------------------------------------


def bench_resilience() -> dict[str, Any]:
    async_runner.reset()
    p = _make_provider(_slow_client(0.5))
    p._cfg["fault_injection"] = True
    cases = [
        lambda: p.prefetch("fault"),
        lambda: p.sync_turn("u", "a"),
        lambda: p.on_pre_compress([]),
        lambda: p.on_session_end([]),
        lambda: p.on_memory_write("add", "MEMORY.md", "x"),
        lambda: p.on_delegation("task", "result"),
    ]
    samples = []
    failures = 0
    for fn in cases * 20:
        try:
            t0 = time.perf_counter()
            fn()
            samples.append(time.perf_counter() - t0)
        except Exception:
            failures += 1
    p.shutdown()
    async_runner.reset()
    stats = _percentiles(samples or [0.0])
    return {"fault_injection": stats, "failures": failures, "budget_ms": 100}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render_markdown(results: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# Plugin benchmarks\n")
    lines.append(f"_Generated {time.strftime('%Y-%m-%d %H:%M:%S')}_\n")

    lines.append("\n## Q1+Q2 — Hot-path latency (plugin vs naive sync baseline)\n")
    lines.append("Naive baseline = what each hook would take if it awaited the HTTP call inline.")
    lines.append("Slow-client column injects 500ms HTTP latency into the mock client.\n")
    lines.append("| Hook | p50 (fast) | p95 (fast) | p99 (slow 500ms HTTP) | naive baseline |")
    lines.append("|------|-----------:|-----------:|----------------------:|---------------:|")
    for name, r in results["hot_path"].items():
        f, s, n = r["fast_client"], r["slow_client_500ms_http"], r["naive_baseline_p50_ms"]
        lines.append(
            f"| `{name}` | {f['p50_ms']:.2f} ms | {f['p95_ms']:.2f} ms | "
            f"{s['p99_ms']:.2f} ms | {n:.0f} ms |"
        )

    rt = results["runner"]
    lines.append("\n## Q3 — Background queue throughput\n")
    s, b = rt["sustained"], rt["burst_overflow"]
    lines.append("**Sustained** (paced producer; workers keep up):")
    lines.append(
        f"- Delivered **{s['jobs_delivered']:,}** of {s['jobs_submitted']:,} "
        f"in {s['wall_seconds']}s = **{s['throughput_jobs_per_sec']:,} jobs/sec**"
    )
    lines.append(f"- Delivery rate: **{s['delivery_rate_pct']}%**\n")
    lines.append("**Burst overflow** (producer floods, queue drops oldest):")
    lines.append(
        f"- Enqueue cost: **{b['enqueue_per_job_us']} µs/job** "
        f"({b['enqueue_total_ms']} ms total for {b['jobs_submitted']:,} submits)"
    )
    lines.append(
        f"- Delivery rate: **{b['delivery_rate_pct']}%** — "
        f"{b['jobs_delivered']:,} delivered before drop-oldest kicked in"
    )
    lines.append(f"- _{b['note']}_\n")

    cf = results["cache_freshness"]
    lines.append("\n## Q4 — Cache freshness over 200-turn loop (80ms recall latency)\n")
    lines.append(
        f"- Cache hit rate: **{cf['hit_rate_pct']}%** "
        f"({cf['cache_hits']} hit / {cf['cache_misses']} miss)"
    )
    lines.append(
        f"- Background recalls completed during run: **{cf['background_recalls_completed']}**\n"
    )

    if "resilience" in results:
        rf = results["resilience"]["fault_injection"]
        lines.append("\n## Resilience — fault-injected hot-path latency\n")
        lines.append(f"- p99: **{rf['p99_ms']:.2f} ms** under fault injection")
        lines.append(f"- Failures escaping hooks: **{results['resilience']['failures']}**\n")

    lines.append(
        "\n_Reproduce: `mise run bench` or `mise run bench:resilience`. "
        "Raw numbers in `references/last-benchmark.json`._\n"
    )
    return "\n".join(lines)


def main() -> int:
    resilience = "--resilience" in sys.argv
    print(
        "running resilience benchmarks ..." if resilience else "running benchmarks (~15s) ...",
        file=sys.stderr,
    )
    t0 = time.perf_counter()
    results = {
        "version": 2,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "hot_path": bench_hot_path(),
        "runner": bench_runner_throughput(),
        "cache_freshness": bench_cache_freshness(),
    }
    if resilience:
        results["resilience"] = bench_resilience()
        p99 = results["resilience"]["fault_injection"]["p99_ms"]
        if p99 >= results["resilience"]["budget_ms"]:
            return 1
    results["wall_seconds"] = round(time.perf_counter() - t0, 2)

    out_dir = ROOT / "references"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "last-benchmark.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    md = render_markdown(results)
    (out_dir / "last-benchmark.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\n  → wrote references/last-benchmark.json ({results['wall_seconds']}s wall)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
