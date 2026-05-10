"""B04 — recall-pipeline tests (R01 + R02)."""

from __future__ import annotations

import statistics
import time

import pytest

from tests.helpers.red_phase import (
    bring_up,
    latency_budget_p99_ms,
)


def test_imports_recall_surface() -> None:
    """Sanity smoke — production recall surface is importable."""
    import client
    import recall_cache
    from provider_lifecycle import do_prefetch


def _seed_observations(provider, count: int) -> None:
    for i in range(count):
        provider._client.write_observation(
            provider._thread,
            provider._profile,
            f"R02 seed fact #{i}: distinct token zorblax-{i}",
            kind="seed",
        )


def _measure_prefetch_p99(provider, samples: int) -> tuple[float, list[float]]:
    durations: list[float] = []
    for i in range(samples):
        t0 = time.monotonic()
        provider.prefetch(f"R02 prefetch query {i}")
        durations.append((time.monotonic() - t0) * 1000.0)
    durations.sort()
    n = len(durations)
    p99 = durations[max(0, min(n - 1, round(0.99 * (n - 1))))]
    return p99, durations


SEED_TOPICS = (
    "kubernetes networking",
    "rust borrow checker",
    "postgres replication",
    "react server components",
    "mastra observer pipeline",
)


def _seed_facts_across_sessions(provider, sessions: int, facts_per_session: int) -> None:
    for s in range(sessions):
        thread = f"r01-session-{s}"
        topic = SEED_TOPICS[s % len(SEED_TOPICS)]
        for f in range(facts_per_session):
            fact = f"in {topic}, the value of constant-{s}-{f} is {1000 + s * 10 + f}"
            provider._client.write_observation(thread, provider._profile, fact, kind="seed")


def _semantic_recall_score(provider, queries: list[tuple[str, str]], top_k: int) -> float:
    hits = 0
    for query, expected in queries:
        results = provider._client.semantic_search(query, provider._profile, top_k)
        texts = " ".join(str(r.get("text", "")) for r in results)
        if expected in texts:
            hits += 1
    return hits / max(1, len(queries))


def _r01_queries() -> list[tuple[str, str]]:
    return [
        ("kubernetes networking constant", "constant-0-0"),
        ("rust borrow checker", "constant-1-0"),
        ("postgres replication", "constant-2-0"),
        ("react server components", "constant-3-0"),
        ("mastra observer pipeline", "constant-4-0"),
    ]


def _assert_recall_meets_floor(provider, recall: float, queries: list[tuple[str, str]]) -> None:
    min_recall = 0.5
    sample = provider._client.semantic_search(queries[0][0], provider._profile, 5)
    assert recall >= min_recall, (
        f"Mastra semantic_search recall@5 = {recall:.2f} on a "
        f"{len(queries)}-question held-out set; required >= "
        f"{min_recall:.2f}. Live probe sample: {sample!r}"
    )


@pytest.mark.integration
def test_red_semantic_recall_at_k_beats_bundled(mastra_client) -> None:
    """R01 — Mastra semantic recall@5 must surface seeded facts.

    The bundled-provider parity bar (mastra recall@5 >= max(honcho,
    hindsight, mem0, supermemory) + 0.10) is enforced in the
    parity-matrix harness; this RED test enforces the precondition:
    Mastra semantic_search must return >= 0.5 recall on a 5-question
    held-out set.

    Failure mode today: client.semantic_search returns 0 hits per the
    May 2026 audit. recall@5 = 0.00. G06 fixes the embedder/index.
    """
    provider = bring_up("r01-semantic-recall")
    try:
        _seed_facts_across_sessions(provider, sessions=5, facts_per_session=10)
        time.sleep(2.0)
        queries = _r01_queries()
        recall = _semantic_recall_score(provider, queries, top_k=5)
        _assert_recall_meets_floor(provider, recall, queries)
    finally:
        provider.shutdown()


def _assert_cache_populated(cached: str) -> None:
    assert "zorblax" in cached, (
        "after 15 seeded observations + warmup the recall cache is "
        f"still empty (got {cached!r}); the prefetch hot path cannot "
        "serve a populated cache because the recall pipeline did "
        "not surface seeded observations back to client.recall()"
    )


def _assert_p99_within_budget(p99_ms: float, budget_p99: float, samples: list[float]) -> None:
    assert p99_ms <= budget_p99, (
        f"prefetch p99={p99_ms:.3f}ms > {budget_p99}ms cache-only budget "
        f"(p50={statistics.median(samples):.3f}ms, "
        f"max={samples[-1]:.3f}ms, n={len(samples)})"
    )


@pytest.mark.integration
def test_red_prefetch_p99_under_budget(mastra_client) -> None:
    """R02 — prefetch hot path stays within the 5 ms p99 cache-only contract
    AND serves a populated cache.

    Failure mode today: cache stays empty after seeding observations
    + warmup because the recall pipeline does not surface seeded
    observations back to client.recall. G06 fixes the populate side
    so prefetch delivers prefetched recall content.
    """
    budget_p99 = latency_budget_p99_ms("prefetch")
    provider = bring_up("r02-prefetch-budget")
    try:
        _seed_observations(provider, count=15)
        time.sleep(0.5)
        provider.prefetch("R02 warmup")
        time.sleep(1.0)
        cached = provider._recall_cache.get(provider._profile, provider._thread)
        _assert_cache_populated(cached)
        p99_ms, samples = _measure_prefetch_p99(provider, samples=200)
        _assert_p99_within_budget(p99_ms, budget_p99, samples)
    finally:
        provider.shutdown()
