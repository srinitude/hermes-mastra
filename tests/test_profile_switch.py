"""Tests for in-plugin synthetic profile-switch detection.

Hermes has no upstream `on_profile_switch` hook (see explanation in
`docs/upstream-watch.md`). The plugin detects profile changes inside the
already-existing `on_turn_start` hook by comparing the kwargs Hermes passes
each turn against the profile we recorded at `initialize()`.

When the comparison flips, we treat it like a session boundary:
  - Drop the recall cache (observations from the old profile/resourceId
    must not leak into the new one).
  - Rebind `_profile` to the new value.
  - Write a synthetic ``kind=profile_switch`` observation to the new
    profile's thread so the lineage is traceable.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def slow_client():
    c = MagicMock()
    c.health.return_value = {"ok": True}
    c.recall.return_value = ""
    c.write_observation.return_value = True
    c.flush.return_value = True
    return c


@pytest.fixture
def provider(fake_hermes_home, slow_client):
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    yield p
    p.shutdown()


def _drain(slow_client, attr: str, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while not getattr(slow_client, attr).called and time.monotonic() < deadline:
        time.sleep(0.02)


# ---- happy path: profile flips between turns -----------------------------


def test_profile_switch_detected_on_turn_start(provider, slow_client):
    provider._profile = "hypothium"
    provider._recall_cache._text = "stale observations from hypothium"
    provider.on_turn_start(turn_number=2, message="hi", agent_identity="krysum")
    assert provider._profile == "krysum"
    assert provider._recall_cache.get() == ""


def test_profile_switch_writes_lineage_observation(provider, slow_client):
    provider._profile = "alpha"
    provider._thread = "thr-1"
    provider.on_turn_start(turn_number=2, message="hi", agent_identity="beta")
    _drain(slow_client, "write_observation")
    calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "profile_switch"
    ]
    assert calls, "expected a profile_switch observation"
    args = calls[0].args
    assert args[1] == "beta"  # written to the NEW profile
    assert "alpha" in args[2]  # text mentions the old profile


# ---- no-op cases ---------------------------------------------------------


def test_no_switch_when_profile_unchanged(provider, slow_client):
    provider._profile = "alpha"
    provider.on_turn_start(turn_number=3, message="hi", agent_identity="alpha")
    time.sleep(0.05)
    assert not slow_client.write_observation.called


def test_no_switch_when_kwarg_missing(provider, slow_client):
    """Most turns won't carry a profile kwarg — that must NOT trigger a
    spurious switch back to 'default'."""
    provider._profile = "alpha"
    provider.on_turn_start(turn_number=3, message="hi")
    assert provider._profile == "alpha"
    time.sleep(0.05)
    assert not slow_client.write_observation.called


def test_no_switch_when_kwarg_blank(provider, slow_client):
    provider._profile = "alpha"
    provider.on_turn_start(turn_number=3, message="hi", agent_identity="   ")
    assert provider._profile == "alpha"
    time.sleep(0.05)
    assert not slow_client.write_observation.called


# ---- alternate kwarg names ----------------------------------------------


def test_profile_kwarg_also_triggers_switch(provider, slow_client):
    provider._profile = "alpha"
    provider.on_turn_start(turn_number=2, message="hi", profile="gamma")
    assert provider._profile == "gamma"


# ---- isolation guarantees -----------------------------------------------


def test_switch_clears_recall_cache_synchronously(provider, slow_client):
    """The hook MUST clear the cache before returning, so the very next
    prefetch() can't serve stale observations from the old profile."""
    provider._profile = "alpha"
    provider._recall_cache._text = "alpha observations"
    provider.on_turn_start(turn_number=4, message="hi", agent_identity="omega")
    # No sleep — must already be empty
    assert provider._recall_cache.get() == ""


def test_switch_is_non_blocking(provider, slow_client):
    provider._profile = "alpha"
    # Make every client call slow
    slow_client.write_observation.side_effect = lambda *a, **kw: time.sleep(1.0) or True
    t0 = time.monotonic()
    provider.on_turn_start(turn_number=5, message="hi", agent_identity="zeta")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1, (
        f"on_turn_start took {elapsed:.3f}s — must be <0.1s. The lineage "
        "observation MUST be enqueued, not awaited inline."
    )


# ---- cron path stays inert ----------------------------------------------


def test_cron_skipped_means_no_profile_switch(fake_hermes_home, slow_client):
    from provider_lifecycle import do_initialize
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    p._client = None
    do_initialize(p, "sess", agent_context="cron")
    assert p._cron_skipped is True
    p.on_turn_start(turn_number=1, message="hi", agent_identity="anything")
    time.sleep(0.05)
    assert not slow_client.write_observation.called
    p.shutdown()
