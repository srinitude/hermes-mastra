"""Tests for the deeper Hermes integration surfaces:

  - kanban events    → kind=kanban_event observation
  - goals events     → kind=goal_event observation
  - context-file load (AGENTS.md / CLAUDE.md / SOUL.md / .cursorrules)
                    → kind=context_files_loaded observation (deduped)
  - batch isolation  → multiple parallel provider instances don't bleed
                       observations across resourceIds

These were identified during the Hermes docs map audit
(`references/hermes-docs-map.json`) as gaps the plugin can helpfully
fill without getting in Hermes' way.
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


# ---- kanban events ------------------------------------------------------


def test_kanban_event_persists_observation(provider, slow_client):
    """When a kanban card moves status (per Hermes' kanban_tools), the
    plugin should snapshot the change as a `kind=kanban_event` observation."""
    from provider_lifecycle import do_kanban_event

    do_kanban_event(
        provider,
        action="move",
        card_id="K-12",
        title="ship feature X",
        from_status="in_progress",
        to_status="completed",
    )
    _wait_for(slow_client, "write_observation")
    kanban_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "kanban_event"
    ]
    assert kanban_calls
    text = kanban_calls[0].args[2]
    assert "K-12" in text
    assert "completed" in text
    assert "ship feature X" in text


def test_kanban_event_skips_when_no_card_id(provider, slow_client):
    """No card_id → noisy noop event; skip."""
    from provider_lifecycle import do_kanban_event

    do_kanban_event(provider, action="list", card_id="", title="")
    time.sleep(0.05)
    kanban_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "kanban_event"
    ]
    assert not kanban_calls


def test_kanban_event_non_blocking(provider, slow_client):
    slow_client.write_observation.side_effect = lambda *a, **kw: time.sleep(1.0) or True
    from provider_lifecycle import do_kanban_event

    t0 = time.monotonic()
    do_kanban_event(provider, action="create", card_id="K-1", title="x")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1


# ---- goal events --------------------------------------------------------


def test_goal_event_persists_observation(provider, slow_client):
    """Hermes goals (`goals.py`) are durable per-profile — natural fit."""
    from provider_lifecycle import do_goal_event

    do_goal_event(provider, action="create", goal_id="G-1", text="finish migration to mise by EOQ")
    _wait_for(slow_client, "write_observation")
    goal_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "goal_event"
    ]
    assert goal_calls
    text = goal_calls[0].args[2]
    assert "G-1" in text
    assert "mise" in text


def test_goal_event_handles_completion(provider, slow_client):
    from provider_lifecycle import do_goal_event

    do_goal_event(
        provider, action="complete", goal_id="G-2", text="ship 1.0", completed_at="2026-05-15"
    )
    _wait_for(slow_client, "write_observation")
    goal_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "goal_event"
    ]
    assert goal_calls
    text = goal_calls[0].args[2]
    assert "complete" in text.lower()
    assert "2026-05-15" in text


# ---- context files (AGENTS.md / CLAUDE.md / SOUL.md / .cursorrules) ----


def test_context_files_loaded_persists_observation(provider, slow_client):
    """Hermes' subdirectory_hints loads AGENTS.md / CLAUDE.md / SOUL.md /
    .cursorrules into the system prompt. Snapshot which files were loaded
    so future sessions know the project conventions in effect."""
    from provider_lifecycle import do_context_files_loaded

    do_context_files_loaded(
        provider,
        files=[
            "/Users/k/work/proj/AGENTS.md",
            "/Users/k/work/proj/SOUL.md",
            "/Users/k/work/proj/subdir/CLAUDE.md",
        ],
    )
    _wait_for(slow_client, "write_observation")
    ctx_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "context_files_loaded"
    ]
    assert ctx_calls
    text = ctx_calls[0].args[2]
    for filename in ("AGENTS.md", "SOUL.md", "CLAUDE.md"):
        assert filename in text


def test_context_files_loaded_deduped_per_session(provider, slow_client):
    """Loading the same context-file set twice in one session shouldn't
    write two observations (the system prompt is frozen anyway)."""
    from provider_lifecycle import do_context_files_loaded

    files = ["/path/AGENTS.md", "/path/SOUL.md"]
    do_context_files_loaded(provider, files=files)
    do_context_files_loaded(provider, files=files)
    do_context_files_loaded(provider, files=files)
    time.sleep(0.05)
    ctx_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "context_files_loaded"
    ]
    assert len(ctx_calls) == 1


def test_context_files_loaded_skips_empty(provider, slow_client):
    from provider_lifecycle import do_context_files_loaded

    do_context_files_loaded(provider, files=[])
    do_context_files_loaded(provider, files=None)
    time.sleep(0.05)
    assert not slow_client.write_observation.called


# ---- batch processing isolation ----------------------------------------


def test_batch_runner_provider_instances_have_isolated_state(fake_hermes_home, slow_client):
    """Hermes' batch_runner instantiates many parallel agents. Each one
    creates its own MastraMemoryProvider. Verify two instances with
    different profiles route writes to different resourceIds."""
    from tests.helpers import make_provider

    c1, c2 = MagicMock(), MagicMock()
    c1.write_observation.return_value = c2.write_observation.return_value = True
    p1, p2 = make_provider(c1), make_provider(c2)
    p1._profile, p1._thread = "batch-A", "batch-A-thread"
    p2._profile, p2._thread = "batch-B", "batch-B-thread"
    p1.sync_turn("u1", "a1")
    p2.sync_turn("u2", "a2")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not (c1.save_turn.called and c2.save_turn.called):
        time.sleep(0.02)
    k1, k2 = c1.save_turn.call_args.kwargs, c2.save_turn.call_args.kwargs
    assert (k1["profile"], k1["thread"]) == ("batch-A", "batch-A-thread")
    assert (k2["profile"], k2["thread"]) == ("batch-B", "batch-B-thread")
    p1.shutdown()
    p2.shutdown()
