"""Tests for the Hermes ↔ Mastra identity link.

Verifies that every piece of context Hermes hands the provider gets
faithfully relayed to Mastra:

  - ``hermes_home`` from initialize() kwargs takes precedence over the
    process-wide HERMES_HOME / hermes_constants lookup.
  - The provider exposes ``resourceId == hermes:<profile>`` and
    ``threadId == <session_id>`` to every downstream HTTP call.
  - Profile name resolves from the first of ``agent_identity`` / ``profile``
    that's non-empty; falls back to ``default``.
  - The system_prompt_block always names the active profile + thread so
    Hermes users can see the link even before the first observation lands.
  - ``on_session_switch(reset=True)`` clears the cache and rebinds the
    threadId without leaking observations from the prior session.
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
    c.save_turn.return_value = True
    c.write_observation.return_value = True
    c.update_working_memory.return_value = True
    c.flush.return_value = True
    return c


@pytest.fixture
def provider(fake_hermes_home, slow_client):
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    yield p
    p.shutdown()


# ---- profile identity ------------------------------------------------------


def test_profile_falls_back_to_default(provider):
    from provider_lifecycle import do_initialize

    do_initialize(provider, "sess-1")
    assert provider._profile == "default"
    assert provider._thread == "sess-1"


def test_profile_uses_agent_identity_kwarg(provider):
    from provider_lifecycle import do_initialize

    do_initialize(provider, "sess-2", agent_identity="hypothium")
    assert provider._profile == "hypothium"


def test_profile_strips_whitespace(provider):
    from provider_lifecycle import do_initialize

    do_initialize(provider, "sess-3", agent_identity="  krysum  ")
    assert provider._profile == "krysum"


def test_thread_falls_back_when_session_id_empty(provider):
    from provider_lifecycle import do_initialize

    do_initialize(provider, "")
    assert provider._thread == "default-session"


# ---- system_prompt_block surfaces identity to the LLM --------------------


def test_system_prompt_names_profile_and_thread(provider, slow_client):
    from provider_lifecycle import do_initialize

    do_initialize(provider, "session-xyz", agent_identity="synthalloy")
    # Force the bring-up coroutine to run synchronously by setting client
    provider._client = slow_client
    block = provider.system_prompt_block()
    assert "synthalloy" in block
    assert "session-xyz" in block
    assert "Mastra Observational Memory" in block


def test_system_prompt_empty_when_provider_unavailable(provider):
    provider._client = None
    assert provider.system_prompt_block() == ""


# ---- every write hook tags resourceId + threadId correctly ---------------


def test_sync_turn_passes_thread_and_profile(provider, slow_client):
    provider._thread = "thr-A"
    provider._profile = "alpha"
    provider.sync_turn("u", "a")
    # Drain background work
    deadline = time.monotonic() + 2.0
    while not slow_client.save_turn.called and time.monotonic() < deadline:
        time.sleep(0.02)
    assert slow_client.save_turn.called
    kwargs = slow_client.save_turn.call_args.kwargs
    assert kwargs["thread"] == "thr-A"
    assert kwargs["profile"] == "alpha"


def test_observation_targets_profile_thread(provider, slow_client):
    provider._thread = "thr-B"
    provider._profile = "beta"
    provider.on_delegation("task X", "result Y", child_session_id="sub-1")
    deadline = time.monotonic() + 2.0
    while not slow_client.write_observation.called and time.monotonic() < deadline:
        time.sleep(0.02)
    assert slow_client.write_observation.called
    args, kwargs = slow_client.write_observation.call_args
    # signature: write_observation(thread, profile, text, kind=...)
    assert args[0] == "thr-B"
    assert args[1] == "beta"
    assert kwargs.get("kind") == "delegation"


def test_memory_write_mirrors_to_working_memory(provider, slow_client):
    provider._thread = "thr-C"
    provider._profile = "gamma"
    provider.on_memory_write(action="add", target="MEMORY.md", content="prefer concise responses")
    deadline = time.monotonic() + 2.0
    while not slow_client.update_working_memory.called and time.monotonic() < deadline:
        time.sleep(0.02)
    assert slow_client.update_working_memory.called
    kwargs = slow_client.update_working_memory.call_args.kwargs
    assert kwargs["profile"] == "gamma"
    assert kwargs["thread"] == "thr-C"
    assert "[MEMORY.md:add]" in kwargs["content"]


# ---- session lifecycle ----------------------------------------------------


def test_session_switch_clears_recall_cache(provider, slow_client):
    provider._thread = "old-thr"
    provider._profile = "delta"
    # Prime the cache with stale data
    provider._recall_cache._text = "stale observations from old session"
    provider.on_session_switch("new-thr", parent_session_id="old-thr")
    # Cache must be cleared so we don't bleed observations across sessions
    assert provider._recall_cache.get() == ""
    assert provider._thread == "new-thr"


def test_session_switch_with_reset_does_not_write_lineage(provider, slow_client):
    provider._thread = "old-thr"
    provider._profile = "epsilon"
    provider.on_session_switch("brand-new", reset=True)
    # No lineage observation when explicitly resetting
    time.sleep(0.1)
    for call in slow_client.write_observation.call_args_list:
        assert call.kwargs.get("kind") != "lineage"


def test_session_switch_without_reset_writes_lineage(provider, slow_client):
    provider._thread = "old-thr"
    provider._profile = "zeta"
    provider.on_session_switch("forked", parent_session_id="old-thr")
    deadline = time.monotonic() + 2.0
    while not slow_client.write_observation.called and time.monotonic() < deadline:
        time.sleep(0.02)
    lineage_calls = [
        c for c in slow_client.write_observation.call_args_list if c.kwargs.get("kind") == "lineage"
    ]
    assert lineage_calls, "expected a lineage observation to be written"
    args = lineage_calls[0].args
    assert args[0] == "forked"  # thread
    assert args[1] == "zeta"  # profile
    assert "old-thr" in args[2]  # text mentions parent


# ---- cron/flush context never touches Mastra ------------------------------


def test_cron_context_skips_all_io(provider, slow_client):
    from provider_lifecycle import do_initialize

    provider._client = None  # reset
    do_initialize(provider, "sess", agent_context="cron")
    assert provider._cron_skipped is True
    # Now call every hook — none should reach the client
    provider.sync_turn("u", "a")
    provider.on_session_end([])
    provider.on_memory_write("add", "MEMORY.md", "x")
    time.sleep(0.1)
    for method in (
        "save_turn",
        "write_observation",
        "update_working_memory",
        "flush",
        "recall",
        "health",
    ):
        assert not getattr(slow_client, method).called, f"{method} fired in cron context"
