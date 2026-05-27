"""Tests for cross-cutting tool + skill integration.

Tools: https://hermes-agent.nousresearch.com/docs/user-guide/features/tools
Skills: https://hermes-agent.nousresearch.com/docs/user-guide/features/skills

The plugin already wires `on_memory_write` (memory tool) and `on_delegation`
(delegate_task tool) through dedicated hooks. This file tests the next
integration tier:

  A. Todo snapshots — when the agent uses the `todo` tool, the plugin
     captures the new list as a `kind="todo_snapshot"` observation so
     cross-session task state survives via Mastra.

  B. Skill-load observations — when a skill is loaded into context (via
     `/skill-name` or `skill_view`), the plugin records it as a
     `kind="skill_loaded"` observation so future sessions know which
     skills were used and when.

  C. The plugin ships its own `skills/mastra/SKILL.md` so `/mastra` works in any
     Hermes session (skills auto-discover).
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


# ---- A. todo snapshots ---------------------------------------------------


def test_todo_snapshot_persists_observation(provider, slow_client):
    """When the agent updates its todo list, snapshot it to Mastra
    so the next session can recall what was being worked on."""
    from provider_lifecycle import do_todo_snapshot

    do_todo_snapshot(
        provider,
        [
            {"id": "1", "content": "ship feature X", "status": "in_progress"},
            {"id": "2", "content": "write tests", "status": "completed"},
        ],
    )
    _wait_for(slow_client, "write_observation")
    todo_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "todo_snapshot"
    ]
    assert todo_calls, "todo snapshot must be tagged kind='todo_snapshot'"
    args = todo_calls[0].args
    assert args[0] == provider._thread
    assert args[1] == provider._profile
    text = args[2]
    assert "ship feature X" in text
    assert "in_progress" in text


def test_todo_snapshot_skips_empty_list(provider, slow_client):
    """Empty/missing todos should NOT spam the observation log."""
    from provider_lifecycle import do_todo_snapshot

    do_todo_snapshot(provider, [])
    do_todo_snapshot(provider, None)
    time.sleep(0.05)
    todo_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "todo_snapshot"
    ]
    assert not todo_calls


def test_todo_snapshot_non_blocking(provider, slow_client):
    """Like every write hook, must enqueue not await."""
    slow_client.write_observation.side_effect = lambda *a, **kw: time.sleep(1.0) or True
    from provider_lifecycle import do_todo_snapshot

    t0 = time.monotonic()
    do_todo_snapshot(provider, [{"id": "1", "content": "x", "status": "pending"}])
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1


def test_todo_snapshot_in_cron_context_is_noop(fake_hermes_home, slow_client):
    from provider_lifecycle import do_initialize, do_todo_snapshot
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    p._client = None
    do_initialize(p, "sess", agent_context="cron")
    do_todo_snapshot(p, [{"id": "1", "content": "x", "status": "pending"}])
    time.sleep(0.05)
    assert not slow_client.write_observation.called
    p.shutdown()


# ---- B. skill-load observations ------------------------------------------


def test_skill_loaded_persists_observation(provider, slow_client):
    """When a skill is loaded into context, persist it as an observation."""
    from provider_lifecycle import do_skill_loaded

    do_skill_loaded(provider, skill_name="plan", reason="user invoked /plan")
    _wait_for(slow_client, "write_observation")
    skill_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "skill_loaded"
    ]
    assert skill_calls
    args = skill_calls[0].args
    assert "plan" in args[2]


def test_skill_loaded_dedup_within_session(provider, slow_client):
    """Loading the same skill twice in one session shouldn't double-write."""
    from provider_lifecycle import do_skill_loaded

    do_skill_loaded(provider, skill_name="excalidraw")
    do_skill_loaded(provider, skill_name="excalidraw")
    do_skill_loaded(provider, skill_name="excalidraw")
    time.sleep(0.1)
    skill_calls = [
        c
        for c in slow_client.write_observation.call_args_list
        if c.kwargs.get("kind") == "skill_loaded"
    ]
    assert len(skill_calls) == 1, (
        f"expected exactly 1 skill_loaded observation per session per skill; got {len(skill_calls)}"
    )


def test_skill_loaded_non_blocking(provider, slow_client):
    slow_client.write_observation.side_effect = lambda *a, **kw: time.sleep(1.0) or True
    from provider_lifecycle import do_skill_loaded

    t0 = time.monotonic()
    do_skill_loaded(provider, skill_name="any-skill")
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1


# ---- C. SKILL.md ships with the plugin ----------------------------------


def test_skill_md_exists_in_plugin_skill_dir():
    """The plugin ships its own skill package so users can `/mastra` to load
    context-aware guidance about when to use recall/search/observe."""
    from pathlib import Path

    plugin_root = Path(__file__).resolve().parents[1]
    skill_md = plugin_root / "skills" / "mastra" / "SKILL.md"
    assert skill_md.exists(), (
        f"SKILL.md missing at {skill_md} — the plugin should auto-register "
        "as a skill so users get `/mastra` for free."
    )


def test_skill_md_has_required_frontmatter():
    plugin_root = Path(__file__).resolve().parents[1]
    skill_md = plugin_root / "skills" / "mastra" / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    fm_end = text.find("\n---\n", 4)
    assert fm_end > 0, "SKILL.md frontmatter must be terminated"
    fm = text[4:fm_end]
    for required in ("name:", "description:", "version:"):
        assert required in fm, f"SKILL.md frontmatter missing '{required}'"
    assert "name: mastra" in fm or "name: mastra" in fm


def test_skill_md_documents_three_tools():
    plugin_root = Path(__file__).resolve().parents[1]
    body = (plugin_root / "skills" / "mastra" / "SKILL.md").read_text(encoding="utf-8")
    for tool in ("mastra_recall", "mastra_search", "mastra_observe"):
        assert tool in body, f"SKILL.md must document {tool}"


def test_skill_md_cross_references_session_search():
    plugin_root = Path(__file__).resolve().parents[1]
    body = (plugin_root / "skills" / "mastra" / "SKILL.md").read_text(encoding="utf-8")
    assert "session_search" in body, (
        "SKILL.md should explain how mastra_* relates to session_search "
        "so users learn the recall hierarchy."
    )
