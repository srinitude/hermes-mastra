"""Tests for integration with Hermes' built-in MEMORY.md / USER.md system.

https://hermes-agent.nousresearch.com/docs/user-guide/features/memory

Hermes' built-in memory has hard char limits (2,200 for MEMORY.md,
1,375 for USER.md) and is injected into the system prompt as a frozen
snapshot. Mastra is unlimited and refreshes per-turn. The plugin
should:

  A. Snapshot the current built-in memory contents into the Mastra
     observation log at session start (so next session can see "what
     was in MEMORY.md when we last talked").

  B. Surface a capacity-aware hint in the system_prompt_block when
     either built-in store is ≥50% full, telling the agent to use
     `mastra_observe` for the bigger/session-specific durable facts.

  C. The `mastra_observe` tool description cross-references MEMORY.md
     so the agent picks the right surface for the right kind of fact.

  D. `on_memory_write` already mirrors writes — but the observation it
     persists must be tagged with the *target* (memory vs user) so the
     observation log retains the distinction Hermes maintains.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def slow_client():
    c = MagicMock()
    c.health.return_value = {"ok": True}
    c.recall.return_value = ""
    c.write_observation.return_value = True
    c.update_working_memory.return_value = True
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


# ---- A. session-start snapshot of built-in memory -----------------------


def test_memory_snapshot_persists_observation(provider, slow_client):
    """`do_memory_snapshot(provider, memory_text, user_text)` writes both
    blobs as `kind=memory_snapshot` observations so future sessions can
    recall the prior built-in-memory state."""
    from provider_lifecycle import do_memory_snapshot

    do_memory_snapshot(
        provider,
        memory_text="User runs macOS 14, prefers concise replies.",
        user_text="Name: Kiren. Timezone: America/Los_Angeles.",
    )
    _wait_for(slow_client, "write_observation", count=2)
    snapshot_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "memory_snapshot"
    ]
    assert len(snapshot_calls) == 2, (
        f"expected one observation for MEMORY.md and one for USER.md; got {len(snapshot_calls)}"
    )
    texts = [c.args[2] for c in snapshot_calls]
    assert any("MEMORY.md" in t and "macOS" in t for t in texts)
    assert any("USER.md" in t and "Kiren" in t for t in texts)


def test_memory_snapshot_skips_blank_blobs(provider, slow_client):
    """If either store is empty, only snapshot the non-empty one."""
    from provider_lifecycle import do_memory_snapshot

    do_memory_snapshot(provider, memory_text="actual content", user_text="")
    _wait_for(slow_client, "write_observation")
    snapshot_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "memory_snapshot"
    ]
    assert len(snapshot_calls) == 1


def test_memory_snapshot_non_blocking(provider, slow_client):
    slow_client.write_observation.side_effect = lambda *a, **kw: time.sleep(1.0) or True
    from provider_lifecycle import do_memory_snapshot

    t0 = time.monotonic()
    do_memory_snapshot(provider, memory_text="x", user_text="y")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1


def test_memory_snapshot_cron_skipped(fake_hermes_home, slow_client):
    from provider_lifecycle import do_initialize, do_memory_snapshot
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    p._client = None
    do_initialize(p, "sess", agent_context="cron")
    do_memory_snapshot(p, memory_text="x", user_text="y")
    time.sleep(0.05)
    assert not slow_client.write_observation.called
    p.shutdown()


# ---- B. capacity-aware hint in system_prompt_block ----------------------
# The hint MUST trigger early (≥50%) so the agent has plenty of room to
# off-load to mastra before MEMORY.md / USER.md fill up.  Waiting until
# 80% leaves only a few turns of headroom — by then the off-load window is
# nearly gone.  The user's principle: proactive triggers > reactive ones.


def test_system_prompt_hint_when_memory_at_50pct(provider):
    """The hint MUST appear at 50% — half-full is the early-warning point."""
    provider._memory_usage_pct = 0.50
    provider._user_usage_pct = 0.20
    block = provider.system_prompt_block()
    assert "MEMORY.md" in block
    assert "mastra_observe" in block.lower()


def test_system_prompt_hint_when_memory_above_50pct(provider):
    """When MEMORY.md is well past half-full, the hint still fires."""
    provider._memory_usage_pct = 0.85
    provider._user_usage_pct = 0.30
    block = provider.system_prompt_block()
    assert "MEMORY.md" in block
    assert "mastra_observe" in block.lower()


def test_system_prompt_hint_when_user_above_50pct(provider):
    provider._memory_usage_pct = 0.20
    provider._user_usage_pct = 0.55
    block = provider.system_prompt_block()
    assert "USER.md" in block


def test_system_prompt_no_hint_below_50pct(provider):
    """Below half-full there's still plenty of room — no need to nag."""
    provider._memory_usage_pct = 0.30
    provider._user_usage_pct = 0.40
    block = provider.system_prompt_block()
    # The "near capacity" warning shouldn't appear when there's room.
    assert "near capacity" not in block.lower()


def test_system_prompt_no_hint_when_usage_unknown(provider):
    """Hermes won't always tell us the usage. Don't fabricate warnings."""
    # Don't set _memory_usage_pct at all — provider must tolerate missing attr
    block = provider.system_prompt_block()
    assert "near capacity" not in block.lower()


# ---- C. mastra_observe description cross-references MEMORY.md --------


def test_observe_description_references_memory_md(provider):
    schemas = {s["name"]: s for s in provider.get_tool_schemas()}
    desc = schemas["mastra_observe"]["description"].lower()
    assert "memory.md" in desc or "memory tool" in desc, (
        "mastra_observe should explain it complements (not replaces) "
        "Hermes' built-in MEMORY.md / USER.md, so the agent picks the "
        "right surface: small + critical → MEMORY.md, larger / session-"
        "specific → mastra_observe."
    )


# ---- D. on_memory_write tags target in the observation -----------------


def test_on_memory_write_tagged_observation_includes_target(provider, slow_client):
    """Existing on_memory_write already mirrors writes via update_working_memory.
    Add a parallel write_observation so the observation log itself records
    that 'add to MEMORY.md' happened — not just the resulting working-memory
    update which loses the target distinction."""
    from provider_lifecycle import do_memory_write

    do_memory_write(
        provider, action="add", target="MEMORY.md", content="prefer mise as canonical CLI"
    )
    # update_working_memory is the existing path
    _wait_for(slow_client, "update_working_memory")
    # New path: tagged observation
    _wait_for(slow_client, "write_observation")
    obs_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "memory_write"
    ]
    assert obs_calls, (
        "on_memory_write must also emit a kind='memory_write' observation "
        "so the observation log distinguishes MEMORY.md vs USER.md edits."
    )
    text = obs_calls[0].args[2]
    assert "MEMORY.md" in text
    assert "add" in text
    assert "mise" in text
