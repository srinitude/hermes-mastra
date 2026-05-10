"""B04 — observation-pipeline tests (R04 + R05)."""

from __future__ import annotations

import time

import pytest

from tests.helpers.red_phase import bring_up


def test_imports_observation_surface() -> None:
    """Sanity smoke — production observation surface is importable."""
    import agent_observers
    import tool_observers
    from provider_lifecycle import do_pre_compress, do_session_end


def _synth_conversation(turns: int) -> tuple[list[dict], list[str]]:
    facts: list[str] = []
    messages: list[dict] = []
    for i in range(turns):
        topic = f"distinct-fact-{i:03d}-payload"
        messages.append({"role": "user", "content": f"please remember {topic}"})
        messages.append({"role": "assistant", "content": f"acknowledged {topic}"})
        facts.append(topic)
    return messages, facts


def _count_distinct(text: str, candidates: list[str]) -> int:
    return sum(1 for c in candidates if c in text)


def _seed_initial_observations(provider, messages: list[dict], turns: int) -> None:
    for m in messages[: 2 * turns]:
        if m["role"] == "user":
            provider._client.write_observation(
                provider._thread, provider._profile, m["content"], kind="user_msg"
            )


def _assert_extraction_dense(extraction: str, facts: list[str], min_distinct: int) -> None:
    distinct = _count_distinct(extraction, facts)
    assert distinct >= min_distinct, (
        f"on_pre_compress produced extraction with {distinct} of "
        f"{len(facts)} seeded facts (required >= {min_distinct}); "
        f"extraction preview={extraction[:300]!r}"
    )


@pytest.mark.integration
def test_red_on_pre_compress_quality_beats_baseline(mastra_client) -> None:
    """R04 — on_pre_compress must produce a fact-dense extraction.

    Failure mode today: do_pre_compress returns the recall cache
    verbatim (or "" when cold); never invokes the Reflector model.
    G07 wires the Reflector path so the conversation buffer is
    summarised into observable facts.
    """
    provider = bring_up("r04-pre-compress-quality")
    try:
        messages, facts = _synth_conversation(turns=100)
        _seed_initial_observations(provider, messages, turns=5)
        time.sleep(1.0)
        extraction = provider.on_pre_compress(messages)
        _assert_extraction_dense(extraction, facts, min_distinct=10)
    finally:
        provider.shutdown()


def _list_obs_text(provider) -> tuple[str, int]:
    observations = provider._client.list_observations(provider._thread, provider._profile)
    return " ".join(str(o.get("text", "")) for o in observations), len(observations)


def _assert_summary_dense(blob: str, count: int, facts: list[str], min_distinct: int) -> None:
    distinct = _count_distinct(blob, facts)
    assert distinct >= min_distinct, (
        f"on_session_end persisted {distinct} of {len(facts)} "
        f"seeded facts as observations (required >= {min_distinct}); "
        f"observations count={count}, preview={blob[:300]!r}"
    )


def _await_summary_dense(
    provider, facts: list[str], min_distinct: int, timeout: float
) -> tuple[str, int]:
    deadline = time.monotonic() + timeout
    blob, count = "", 0
    while time.monotonic() < deadline:
        blob, count = _list_obs_text(provider)
        if _count_distinct(blob, facts) >= min_distinct:
            return blob, count
        time.sleep(0.25)
    return blob, count


@pytest.mark.integration
def test_red_on_session_end_quality(mastra_client) -> None:
    """R05 — on_session_end must persist a fact-dense session summary.

    Failure mode today: do_session_end only enqueues client.flush —
    it never passes the buffer through the Reflector and never
    persists a structured summary. G07 wires the Reflector path.
    """
    provider = bring_up("r05-session-end-quality")
    try:
        messages, facts = _synth_conversation(turns=50)
        provider.on_session_end(messages)
        blob, count = _await_summary_dense(provider, facts, min_distinct=5, timeout=8.0)
        _assert_summary_dense(blob, count, facts, min_distinct=5)
    finally:
        provider.shutdown()
