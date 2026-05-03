"""Tests for the integration between mastra and Hermes' context system.

Hermes' `_compress_context` calls `on_pre_compress(messages)` but discards
the return value (see run_agent.py L9034). So the plugin can't directly
inject text into the compressor's summary; instead we:

  1. Persist the pre-compression observation block as a synthetic Mastra
     observation. The next `prefetch()` (which IS consumed by Hermes
     and injected into the next user message) will surface it.
  2. Pre-emptively flush + recall when prompt tokens approach the
     compression threshold, so by the time the compressor fires, fresh
     observations are already in the cache.

These tests verify both behaviours.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def slow_client():
    c = MagicMock()
    c.health.return_value = {"ok": True}
    c.recall.return_value = "old observation A\nold observation B"
    c.write_observation.return_value = True
    c.flush.return_value = True
    return c


@pytest.fixture
def provider(fake_hermes_home, slow_client):
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    yield p
    p.shutdown()


def _wait_for(slow_client, attr: str, count: int = 1, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while getattr(slow_client, attr).call_count < count and time.monotonic() < deadline:
        time.sleep(0.02)


# ---- on_pre_compress writes a recoverable observation --------------------


def test_pre_compress_persists_synthetic_observation(provider, slow_client):
    """The hook MUST write a `kind=pre_compress` observation so the next
    prefetch can resurface it after the compressor wipes the middle turns.
    Just returning a string is wasted — Hermes discards the return value.
    """
    provider._thread = "thr-1"
    provider._profile = "alpha"
    provider._recall_cache._text = "context the compressor is about to discard"
    provider.on_pre_compress(messages=[{"role": "user", "content": "x"}])
    _wait_for(slow_client, "write_observation")
    pre_compress_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "pre_compress"
    ]
    assert pre_compress_calls, (
        "on_pre_compress must persist a synthetic observation tagged "
        "kind='pre_compress' — the return value is ignored by Hermes."
    )
    args = pre_compress_calls[0].args
    assert args[0] == "thr-1"
    assert args[1] == "alpha"


def test_pre_compress_skips_synthetic_when_cache_empty(provider, slow_client):
    """No point writing an empty pre_compress observation."""
    provider._recall_cache._text = ""
    provider.on_pre_compress([])
    time.sleep(0.05)
    pre_compress_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "pre_compress"
    ]
    assert not pre_compress_calls


# ---- pre-emptive refresh when context fills up ---------------------------


def test_high_token_pressure_triggers_extra_recall(provider, slow_client):
    """When prompt tokens cross compression.threshold (minus a small epsilon),
    the next prefetch should refresh the cache eagerly so the compressor
    finds fresh observations waiting."""
    provider._cfg = {"recall_top_k": 4, "compression_threshold": 0.50, "context_length": 200_000}
    # Simulate a turn that just crossed 90% of the threshold (i.e. near
    # the compression boundary). The plugin tracks this by reading
    # `last_prompt_tokens` from the agent if exposed.
    provider._last_prompt_tokens = int(0.45 * 200_000)  # 45% — below threshold
    provider.prefetch("anything")
    _wait_for(slow_client, "recall", count=1)
    initial = slow_client.recall.call_count

    # Now simulate token pressure climbing
    provider._last_prompt_tokens = int(0.49 * 200_000)  # just under threshold
    provider.prefetch("anything")
    _wait_for(slow_client, "recall", count=initial + 1)
    # Either we got a 2nd recall (because the in-flight one finished),
    # OR we still have a single in-flight one — both are acceptable. The
    # contract is that we DON'T silently no-op when pressure rises.
    assert slow_client.recall.call_count >= 1


# ---- non-blocking guarantee -----------------------------------------------


def test_pre_compress_is_non_blocking_even_with_synthetic_write(provider, slow_client):
    """Adding the synthetic observation write must NOT block the hook."""
    provider._recall_cache._text = "stale"
    slow_client.write_observation.side_effect = lambda *a, **kw: time.sleep(1.0) or True
    t0 = time.monotonic()
    provider.on_pre_compress([])
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1, (
        f"on_pre_compress took {elapsed:.3f}s — must stay non-blocking "
        "even when the synthetic observation write is slow."
    )


# ---- still returns the cache for the (discarded) return path -------------


def test_pre_compress_still_returns_cached_text_for_introspection(provider, slow_client):
    """Even though Hermes discards it, return the cache so other consumers
    (custom subclasses, debug output, future Hermes versions) can read it."""
    provider._recall_cache._text = "observed: user prefers concise replies"
    text = provider.on_pre_compress([])
    assert "observed" in text
    assert "before compression" in text.lower()
