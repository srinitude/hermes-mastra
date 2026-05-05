"""Retrieval relevance contract.

The cached prefetch must be relevant — never spill stale content from a
previous profile/session, never surface empty noise, always announce
the active profile so the model can interpret correctly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.helpers import make_provider


@pytest.fixture
def client():
    c = MagicMock()
    c.health.return_value = {"ok": True}
    c.recall.return_value = ""
    c.write_observation.return_value = True
    return c


@pytest.fixture
def provider(fake_hermes_home, client):
    p = make_provider(client)
    yield p
    p.shutdown()


# --- 1. empty cache → empty prefetch ------------------------------------


def test_prefetch_returns_empty_string_when_cache_empty(provider):
    """No observations yet → prefetch returns '' so the agent sees no
    spurious context block."""
    out = provider.prefetch("anything")
    assert out == ""


# --- 2. populated cache → header + body ---------------------------------


def test_prefetch_announces_active_profile(provider):
    """When the cache has content, the returned string must name the
    active profile so the model can scope the recall correctly."""
    provider._recall_cache._text = "fact-1\nfact-2"
    provider._profile = "alpha"
    out = provider.prefetch("query")
    assert "alpha" in out, "prefetch output omits the active profile name"
    assert "fact-1" in out and "fact-2" in out, "cached observations missing"


# --- 3. session-id mismatch → cache cleared -----------------------------


def test_session_id_mismatch_clears_stale_cache(provider):
    """Switching to a new session must purge the cached snapshot before
    returning, otherwise the new session sees the old session's text."""
    provider._recall_cache._text = "stale from session A"
    provider._thread = "session-a"
    out = provider.prefetch("query", session_id="session-b")
    assert out == "", (
        "prefetch leaked the previous session's cached snapshot when the session_id rotated"
    )
    assert provider._thread == "session-b"


# --- 4. profile-switch detection clears the cache -----------------------


def test_profile_switch_clears_cache(provider):
    """do_turn_start synthesises a profile-switch when Hermes doesn't
    fire one. Cache must clear so the new profile doesn't see the
    old profile's content."""
    from provider_lifecycle import do_turn_start

    provider._recall_cache._text = "user-a's secret notes"
    provider._profile = "user-a"
    do_turn_start(provider, 1, "hi", agent_identity="user-b")
    assert provider._recall_cache.get() == "", (
        "profile flip from user-a to user-b leaked observations across profiles"
    )
    assert provider._profile == "user-b"


# --- 5. on_session_switch reset=True clears cache -----------------------


def test_session_switch_with_reset_clears_cache(provider):
    """/reset must clear the cache so the new session starts blank."""
    from provider_lifecycle import do_session_switch

    provider._recall_cache._text = "old session content"
    do_session_switch(provider, "new-session", reset=True)
    assert provider._recall_cache.get() == ""


# --- 6. lineage hint when session continues -----------------------------


def test_session_switch_writes_lineage_observation_when_parent_supplied(provider, client):
    """When parent_session_id is supplied (e.g. /branch), we must persist
    a lineage observation so the new thread inherits provenance."""
    import time

    from provider_lifecycle import do_session_switch

    provider._thread = "old-thread"
    do_session_switch(provider, "new-thread", parent_session_id="old-thread", reset=False)

    # write_observation enqueued on the runner — wait briefly
    deadline = time.monotonic() + 1.0
    while not client.write_observation.called and time.monotonic() < deadline:
        time.sleep(0.02)

    assert client.write_observation.called
    kinds = {c.kwargs.get("kind") for c in client.write_observation.call_args_list}
    assert "lineage" in kinds, "no lineage observation written on session continuation"


# --- 7. system_prompt_block speaks about three recall surfaces ----------


def test_system_prompt_block_lists_three_recall_surfaces(provider):
    """The block must instruct the model on which recall tool to use."""
    block = provider.system_prompt_block()
    for tool in ("mastra_recall", "mastra_search", "mastra_observe"):
        assert tool in block, f"system prompt block omits {tool}"


# --- 8. cron / flush contexts return empty ------------------------------


def test_cron_context_skips_system_prompt_block(fake_hermes_home, client):
    from provider_lifecycle import do_initialize

    p = make_provider(client)
    do_initialize(p, "sess", agent_context="cron")
    assert p.system_prompt_block() == ""
    assert p.get_tool_schemas() == []
    p.shutdown()
