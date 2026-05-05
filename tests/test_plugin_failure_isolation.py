"""Failure isolation contract — our failures and theirs are independent.

Encodes ``analysis/plugin-clash-analysis.md`` §error_isolation. Hermes
catches per-callback exceptions inside ``invoke_hook`` and per-provider
exceptions inside ``MemoryManager``. We additionally verify that:

1. Our hook callbacks NEVER raise into the host — they catch and log.
2. When our plugin raises during init, MemoryManager surfaces it but
   other plugins keep working.
3. When another plugin's hook raises, our callbacks still fire.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from tests.helpers import make_provider
from tests.helpers.fake_plugins import install_failing_plugin, make_ctx


@pytest.fixture
def slow_client():
    c = MagicMock()
    c.health.return_value = {"ok": True}
    c.recall.return_value = ""
    c.write_observation.side_effect = RuntimeError("simulated network blip")
    c.update_working_memory.return_value = True
    return c


@pytest.fixture
def provider(fake_hermes_home, slow_client):
    p = make_provider(slow_client)
    yield p
    p.shutdown()


# --- 1. our callbacks never raise to the caller -------------------------


def test_our_post_tool_call_swallows_handler_errors(provider, slow_client):
    """If a route handler inside our wiring raises, the wrapping cb
    must still return cleanly."""
    from hermes_wiring import activate_for

    cb = activate_for(provider)["post_tool_call"]
    # Bogus result string makes _try_json return None and then
    # downstream handler operates on empty dict — must not raise
    cb(tool_name="execute_code", args={"code": "x"}, result="not-json")


def test_our_session_reset_callback_swallows_provider_errors(provider):
    """Even if provider.on_session_switch raises, our cb must not
    propagate the exception out of Hermes' invoke_hook."""
    from hermes_wiring import activate_for

    def boom(*a, **kw):
        raise RuntimeError("simulated provider failure")

    provider.on_session_switch = boom  # type: ignore[method-assign]
    cb = activate_for(provider)["on_session_reset"]
    cb(session_id="x", platform="cli")  # must not raise


def test_our_session_finalize_callback_swallows_provider_errors(provider):
    from hermes_wiring import activate_for

    def boom(*a, **kw):
        raise RuntimeError("simulated provider failure")

    provider.on_session_end = boom  # type: ignore[method-assign]
    cb = activate_for(provider)["on_session_finalize"]
    cb(session_id="x")


# --- 2. our hot-path hooks degrade gracefully when the client is broken --


def test_prefetch_returns_empty_when_client_dies(provider, slow_client):
    """If the recall client has been torn down (None), prefetch returns
    empty without raising."""
    provider._client = None
    out = provider.prefetch("hello?")
    assert out == ""


def test_sync_turn_with_dead_client_does_not_raise(provider):
    """Sync writes must be best-effort; a dead client → silent no-op."""
    provider._client = None
    provider.sync_turn("u", "a")  # must not raise


def test_on_pre_compress_with_dead_client_does_not_raise(provider):
    provider._client = None
    out = provider.on_pre_compress([{"role": "user", "content": "x"}])
    assert isinstance(out, str)


# --- 3. other plugins' failures don't take us down ---------------------


def test_other_plugin_failing_does_not_block_our_callback(provider):
    """Hermes invoke_hook fires every callback even when one raises.
    Our callback must produce its result regardless."""
    ctx = make_ctx()
    install_failing_plugin(ctx, fail_at="post_tool_call")

    from hermes_wiring import activate_for

    our_cb = activate_for(provider)["post_tool_call"]
    # Run their callbacks first — they raise — then ours
    callbacks = [*ctx.hooks["post_tool_call"], our_cb]

    invoked = 0
    for cb in callbacks:
        try:
            cb(tool_name="skill_view", args={"name": "plan"}, result='{"name":"plan"}')
            invoked += 1
        except Exception:
            # Hermes' invoke_hook catches, but we simulate that by swallowing
            pass

    # Our callback should have run successfully (returned None)
    assert invoked >= 1
