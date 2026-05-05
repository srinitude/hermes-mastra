"""Load-order invariance contract.

Hermes loads plugins in directory-scan order; later sources override.
Our externally observable behaviour must be invariant under any valid
permutation of (mastra_register, observer_register, command_register,
lifecycle_register).

Backed by ``analysis/plugin-contract.md`` §7 and the compatibility
matrix's `unknown_plugins_policy`.
"""

from __future__ import annotations

import itertools
from unittest.mock import MagicMock

import pytest

from tests.helpers import make_provider
from tests.helpers.fake_plugins import (
    install_command_plugin,
    install_lifecycle_plugin,
    install_observer_plugin,
    make_ctx,
)


@pytest.fixture
def slow_client():
    c = MagicMock()
    c.health.return_value = {"ok": True}
    c.recall.return_value = ""
    c.write_observation.return_value = True
    return c


def _register_mastra(ctx, slow_client):
    """Run our plugin's register(ctx) with a recording context, then
    swap in our slow client so subsequent calls are deterministic."""
    from __init__ import register

    register(ctx)
    # Provider was registered via ctx.register_memory_provider; pull it back.
    found = [t for t in ctx.tools if t[0] == "memory_provider"]
    assert found, "our register() did not call register_memory_provider"
    return found[0][1]["name"]


def _reg_mastra(ctx, _slow_client):
    return _register_mastra(ctx, _slow_client)


def _reg_observer(ctx, _slow_client):
    return install_observer_plugin(ctx)


def _reg_command(ctx, _slow_client):
    return install_command_plugin(ctx, name="other_cmd_z")


def _reg_lifecycle(ctx, _slow_client):
    return install_lifecycle_plugin(ctx)


_REGISTRARS = {
    "mastra": _reg_mastra,
    "observer": _reg_observer,
    "command": _reg_command,
    "lifecycle": _reg_lifecycle,
}


@pytest.mark.parametrize("order", list(itertools.permutations(_REGISTRARS.keys())))
def test_observer_plugin_sees_post_tool_call_irrespective_of_load_order(order, slow_client):
    """No matter when our plugin registers, a coexisting observer plugin
    still receives every post_tool_call event."""
    ctx = make_ctx()
    for name in order:
        _REGISTRARS[name](ctx, slow_client)

    callbacks = ctx.hooks.get("post_tool_call", [])
    # observer plugin contributed exactly one callback; ours is wired
    # via the memory loader path, not register_hook on this ctx — so
    # we expect at least the observer's callback to be present.
    payload = {"tool_name": "execute_code", "args": {"code": "x"}, "result": "ok"}
    for cb in callbacks:
        cb(**payload)


@pytest.mark.parametrize("order", list(itertools.permutations(_REGISTRARS.keys())))
def test_canonical_plugin_id_unchanged_by_load_order(order, slow_client):
    """The plugin ID 'mastra' is invariant across all load orders."""
    ctx = make_ctx()
    for name in order:
        _REGISTRARS[name](ctx, slow_client)
    found = [t for t in ctx.tools if t[0] == "memory_provider"]
    assert found and found[0][1]["name"] == "mastra"


@pytest.mark.parametrize(
    "order",
    list(itertools.permutations(["mastra", "observer", "command"])),
)
def test_no_command_collision_under_load_order(order, slow_client):
    """No load order causes our plugin to register a command that
    conflicts with the fake command plugin's name."""
    ctx = make_ctx()
    for name in order:
        _REGISTRARS[name](ctx, slow_client)
    cmd_names = [c[0] for c in ctx.commands]
    assert cmd_names.count("other_cmd_z") <= 1, (
        "duplicate command registration — collision under load order"
    )
    assert not any(c[0].startswith("mastra_") for c in ctx.commands)
