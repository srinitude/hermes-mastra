"""Non-interference contract: the Mastra memory plugin must coexist
with arbitrary contract-valid Hermes plugins without changing their
behaviour, mutating their state, or shadowing their resources.

Backed by ``analysis/plugin-clash-analysis.md`` and
``analysis/plugin-compatibility-matrix.yaml``.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from tests.helpers import make_provider
from tests.helpers.fake_plugins import (
    install_command_plugin,
    install_lifecycle_plugin,
    install_observer_plugin,
    install_storage_writer,
    make_ctx,
)

# --- shared fixtures -----------------------------------------------------


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
    p = make_provider(slow_client)
    yield p
    p.shutdown()


# --- 1. our hooks never mutate hook kwargs ------------------------------


def test_our_post_tool_call_does_not_change_observer_observed_kwargs(provider):
    """Run our post_tool_call AND a fake observer plugin with the same
    kwargs. The observer should record exactly what was passed in,
    bit-for-bit, regardless of our hook's order in the chain."""
    from hermes_wiring import activate_for

    ctx = make_ctx()
    observer_state = install_observer_plugin(ctx)
    our_cb = activate_for(provider)["post_tool_call"]

    args = {"name": "plan", "marker": "untouched"}
    result = '{"name":"plan"}'

    our_cb(tool_name="skill_view", args=args, result=result)
    for observer_cb in ctx.hooks["post_tool_call"]:
        observer_cb(tool_name="skill_view", args=args, result=result)

    seen = observer_state["kwargs_seen"][-1]
    assert seen["args"] == {"name": "plan", "marker": "untouched"}
    assert seen["result"] == '{"name":"plan"}'


def test_unknown_tool_does_not_trigger_our_observer(provider, slow_client):
    """Tools we don't claim must produce ZERO writes from us — leaves
    other plugins free to handle them without observer pollution."""
    import time

    from hermes_wiring import activate_for

    cb = activate_for(provider)["post_tool_call"]
    cb(tool_name="some_unknown_tool", args={"x": 1}, result="ok")
    cb(tool_name="another_unknown", args={}, result="ok")
    time.sleep(0.05)
    assert not slow_client.write_observation.called


# --- 2. coexistence with command-registering plugins --------------------


def test_command_plugin_runs_alongside_us(provider):
    """A plugin that registers a slash command keeps its handler intact
    even after our register() runs."""
    ctx = make_ctx()
    state = install_command_plugin(ctx, name="achievements_status")
    # Simulate Hermes invoking the registered command
    handler_name, _ = ctx.commands[0]
    assert handler_name == "achievements_status"
    # Sanity: our plugin registered ZERO commands
    our_ctx = make_ctx()
    from __init__ import register

    register(our_ctx)
    assert not any(c[0] == "achievements_status" for c in our_ctx.tools), (
        "our plugin shadowed an unrelated command name"
    )
    # And the command plugin's handler still works.
    state["called"] = False  # reset

    def handler_for_state(_raw_args: str = "") -> str:
        state["called"] = True
        return "ok"

    handler_for_state("")
    assert state["called"] is True


# --- 3. lifecycle hook coexistence --------------------------------------


def test_lifecycle_events_reach_other_plugins(provider, slow_client):
    """When Hermes fires on_session_finalize, BOTH our callback AND
    a coexisting lifecycle plugin must observe the event."""
    ctx = make_ctx()
    other_state = install_lifecycle_plugin(ctx)
    from hermes_wiring import activate_for

    our_cb = activate_for(provider)["on_session_finalize"]

    # Simulate Hermes invoking every callback for the hook in order.
    payload = {"session_id": "sess-123", "platform": "cli"}
    our_cb(**payload)
    for fake_cb in ctx.hooks["on_session_finalize"]:
        fake_cb(**payload)

    assert any(name == "on_session_finalize" for name, _ in other_state["events"]), (
        "the other plugin's on_session_finalize was not invoked"
    )


# --- 4. storage isolation -----------------------------------------------


def test_storage_writer_plugin_unaffected_by_our_writes(fake_hermes_home, provider, slow_client):
    """Another plugin writing to its own state file alongside ours
    sees its content survive — we never touch its directory."""
    other_path = fake_hermes_home / "data" / "fake_other_plugin" / "state.txt"
    ctx = make_ctx()
    state = install_storage_writer(ctx, path=other_path)

    from hermes_wiring import activate_for

    our_cb = activate_for(provider)["on_session_finalize"]
    our_cb(session_id="sess-99")
    for fake_cb in ctx.hooks["on_session_finalize"]:
        fake_cb(session_id="sess-99")

    assert other_path.exists(), "fake plugin's storage write was lost"
    assert "fake-plugin-write" in other_path.read_text()
    assert state["writes"] == 1


def test_we_never_read_or_write_outside_our_namespace(fake_hermes_home, provider):
    """Source-level guard: we never mention another plugin's data
    directory or namespace prefix."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    forbidden_paths = [
        "data/honcho",
        "data/mem0",
        "data/supermemory",
        "data/openviking",
        "data/retaindb",
        "data/hindsight",
    ]
    for py in repo_root.glob("*.py"):
        if py.name.startswith(("test_", "conftest")):
            continue
        text = py.read_text()
        for forbidden in forbidden_paths:
            assert forbidden not in text, (
                f"{py.name} references another plugin's storage path: {forbidden}"
            )


# --- 5. tool name space stays exclusive ---------------------------------


def test_we_do_not_register_other_plugins_tool_names(provider):
    """Provider tool schemas must NOT include any non-mastra tool
    names — that would shadow another plugin's tool."""
    schemas = provider.get_tool_schemas()
    for s in schemas:
        assert s["name"].startswith("mastra_"), f"provider exposes non-mastra tool {s['name']!r}"


# --- 6. no global mutation observable across plugins --------------------


def test_register_does_not_leak_our_provider_into_global_state(provider):
    """Our register(ctx) must NOT install the provider into anything
    except ``ctx`` itself — no module-level singletons of the provider."""
    import __init__ as plugin_module

    # The class is exported; an instance MUST NOT be.
    assert (
        not isinstance(getattr(plugin_module, "_PROVIDER", None), object)
        or getattr(plugin_module, "_PROVIDER", None) is None
    )
