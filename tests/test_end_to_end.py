"""B04 — end-to-end "what did I do" recall tests (R10)."""

from __future__ import annotations

import time

import pytest

from tests.helpers.red_phase import bring_up


def test_imports_end_to_end_surface() -> None:
    """Sanity smoke — every cross-session recall participant is importable."""
    import client
    import provider_lifecycle


RECAP_DAYS = (
    ("day-1-mon", "shipped the Hermes plugin loader fix"),
    ("day-2-tue", "wrote tests for memory_tool dual-writes"),
    ("day-3-wed", "drafted the parity matrix design"),
    ("day-4-thu", "tuned the Mastra observer model"),
    ("day-5-fri", "reviewed the lifecycle hook latency"),
)


def _seed_recap(provider) -> list[str]:
    for thread, topic in RECAP_DAYS:
        provider._client.write_observation(
            thread, provider._profile, f"yesterday I {topic}", kind="recap_seed"
        )
    return [t for _, t in RECAP_DAYS]


def _assert_recap_includes_seeded(recap: str, topics: list[str]) -> None:
    matched = [t for t in topics if t in recap]
    assert matched, (
        "prefetch did not return any Mastra-sourced recap content "
        f"for a 'what did I work on yesterday?' query — "
        f"recap={recap!r}; expected at least one of {topics!r}"
    )


@pytest.mark.integration
def test_red_recap_hits_mastra_first(mastra_client) -> None:
    """R10 — recap query must surface Mastra-sourced recall content.

    Failure mode today: per the May 2026 audit, recap returns 0 hits
    from Mastra. G08 wires the Mastra-first prefetch path so seeded
    observations surface back through the recap query.
    """
    provider = bring_up("r10-recap-today")
    try:
        topics = _seed_recap(provider)
        time.sleep(1.0)
        provider.prefetch("recap warmup")
        time.sleep(1.0)
        recap = provider.prefetch("what did I work on yesterday?")
        _assert_recap_includes_seeded(recap, topics)
    finally:
        provider.shutdown()
