"""Tests for the Hermes call-site wiring layer.

`hermes_wiring.activate_for(provider)` is the entry point. It wires
the provider's observers to:

  A. Native Hermes plugin hooks (via the `ctx.register_hook` contract).
     We test this by simulating Hermes invoking each hook with the same
     kwargs the upstream code uses.

  B. Targeted monkey-patches for surfaces with no native hook
     (SOUL.md loader, personality command, goals lifecycle,
     BatchRunner.run). We test this by importing each upstream module's
     stub and confirming the wrapped function delegates correctly.

Both paths are activated once at register() time and idempotent — calling
`activate_for` multiple times must not double-fire.
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


def _kinds(slow_client, kind: str) -> list:
    return [c for c in slow_client.write_observation.call_args_list if c.kwargs.get("kind") == kind]


# ---- A. native plugin-hook routing -------------------------------------


def test_activate_returns_callbacks_for_native_hooks(provider):
    """activate_for(provider) returns a dict of {hook_name: callback}
    that callers can register with Hermes' plugin context."""
    from hermes_wiring import activate_for

    callbacks = activate_for(provider)
    assert "pre_tool_call" in callbacks
    assert "post_tool_call" in callbacks
    assert "on_session_reset" in callbacks
    assert "on_session_finalize" in callbacks


def test_post_tool_call_routes_skill_view_to_skill_loaded(provider, slow_client):
    """When `skill_view` ran, fire `do_skill_loaded`."""
    from hermes_wiring import activate_for

    cb = activate_for(provider)["post_tool_call"]
    cb(tool_name="skill_view", args={"name": "plan"}, result='{"name":"plan"}')
    _wait_for(slow_client, "write_observation")
    assert _kinds(slow_client, "skill_loaded")


def test_post_tool_call_routes_execute_code(provider, slow_client):
    from hermes_wiring import activate_for

    cb = activate_for(provider)["post_tool_call"]
    cb(
        tool_name="execute_code",
        args={"code": "print(1+1)"},
        result='{"exit_code": 0, "output": "2"}',
    )
    _wait_for(slow_client, "write_observation")
    text = _kinds(slow_client, "execute_code")[0].args[2]
    assert "print(1+1)" in text


def test_post_tool_call_routes_todo_snapshot(provider, slow_client):
    import json

    from hermes_wiring import activate_for

    cb = activate_for(provider)["post_tool_call"]
    todos = [{"id": "1", "content": "x", "status": "pending"}]
    cb(tool_name="todo", args={}, result=json.dumps({"todos": todos}))
    _wait_for(slow_client, "write_observation")
    assert _kinds(slow_client, "todo_snapshot")


def test_post_tool_call_routes_kanban_event(provider, slow_client):
    from hermes_wiring import activate_for

    cb = activate_for(provider)["post_tool_call"]
    cb(
        tool_name="kanban",
        args={"action": "move", "card_id": "K-1", "to_status": "done"},
        result='{"ok":true}',
    )
    _wait_for(slow_client, "write_observation")
    assert _kinds(slow_client, "kanban_event")


def test_post_tool_call_routes_goals(provider, slow_client):
    from hermes_wiring import activate_for

    cb = activate_for(provider)["post_tool_call"]
    cb(
        tool_name="goals",
        args={"action": "create", "text": "ship 1.0"},
        result='{"ok":true,"goal_id":"G-1"}',
    )
    _wait_for(slow_client, "write_observation")
    # Either kind=goal_set (CLI /goal) or kind=goal_event (tool path) is fine
    found = _kinds(slow_client, "goal_set") + _kinds(slow_client, "goal_event")
    assert found, "expected goal observation"


def test_post_tool_call_unknown_tool_is_silent_noop(provider, slow_client):
    """Tools we don't care about must not produce noise."""
    from hermes_wiring import activate_for

    cb = activate_for(provider)["post_tool_call"]
    cb(tool_name="web_search", args={"query": "x"}, result="...")
    cb(tool_name="terminal", args={"command": "ls"}, result="...")
    cb(tool_name="read_file", args={"path": "/x"}, result="...")
    time.sleep(0.05)
    # No observations of any of our kinds for these
    for kind in (
        "skill_loaded",
        "execute_code",
        "todo_snapshot",
        "kanban_event",
        "goal_set",
        "goal_event",
    ):
        assert not _kinds(slow_client, kind)


def test_on_session_finalize_drains_pending_writes(provider, slow_client):
    """Hermes fires on_session_finalize at session end. Our callback
    must trigger the provider's flush+drain so observations actually
    land in Mastra before the process exits."""
    from hermes_wiring import activate_for

    cb = activate_for(provider)["on_session_finalize"]
    # Pre-load some pending work
    provider.sync_turn("u", "a")
    cb(session_id=provider._thread)
    _wait_for(slow_client, "save_turn")
    assert slow_client.save_turn.called


def test_on_session_reset_clears_recall_cache(provider, slow_client):
    """/reset → cache must clear so the new session doesn't see stale
    observations from the prior thread."""
    from hermes_wiring import activate_for

    provider._recall_cache._text = "stale observations"
    cb = activate_for(provider)["on_session_reset"]
    cb(session_id="new-sess", platform="cli")
    assert provider._recall_cache.get() == ""


# ---- B. monkey-patch wiring ---------------------------------------------


def test_activate_returns_patches_handle(provider):
    """activate_for installs monkey-patches and returns a `revert` callable
    so tests + plugin shutdown can cleanly undo them."""
    from hermes_wiring import activate_for

    out = activate_for(provider)
    assert callable(out.get("revert"))


def test_activate_is_idempotent(provider, slow_client):
    """Calling activate_for twice doesn't double-wire patches (would
    cause every hook to fire 2x)."""
    from hermes_wiring import activate_for

    a = activate_for(provider)
    b = activate_for(provider)
    cb = b["post_tool_call"]
    cb(tool_name="skill_view", args={"name": "plan"}, result="ok")
    _wait_for(slow_client, "write_observation")
    assert len(_kinds(slow_client, "skill_loaded")) == 1
    a["revert"]()
    b["revert"]()


# ---- C. cron context still skips ---------------------------------------


def test_wiring_respects_cron_context(fake_hermes_home, slow_client):
    """When the provider is in cron mode, every wired hook must no-op."""
    from hermes_wiring import activate_for
    from provider_lifecycle import do_initialize
    from tests.helpers import make_provider

    p = make_provider(slow_client)
    p._client = None
    do_initialize(p, "sess", agent_context="cron")
    out = activate_for(p)
    out["post_tool_call"](tool_name="execute_code", args={"code": "x"}, result="ok")
    out["post_tool_call"](tool_name="skill_view", args={"name": "plan"}, result="ok")
    out["on_session_finalize"](session_id="x")
    out["on_session_reset"](session_id="x")
    time.sleep(0.05)
    assert not slow_client.write_observation.called
    out["revert"]()
    p.shutdown()
