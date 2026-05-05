"""In-test fake Hermes plugins used to validate non-interference.

These are NOT production code and never ship — they live under
``tests/helpers/`` and exist only so we can prove the Mastra memory
plugin coexists with arbitrary contract-valid plugins. Each fake
emulates one real plugin behaviour: hook registration, command
registration, configuration reads, storage writes, event emission,
lifecycle callbacks, and intentional failures.
"""

from __future__ import annotations

import threading
from collections.abc import Callable


class _RecordingCtx:
    """A minimal PluginContext stand-in that records every call."""

    def __init__(self) -> None:
        self.tools: list[tuple[str, dict]] = []
        self.hooks: dict[str, list[Callable]] = {}
        self.commands: list[tuple[str, str]] = []
        self.cli_commands: list[str] = []
        self._lock = threading.Lock()

    def register_hook(self, name: str, callback: Callable) -> None:
        with self._lock:
            self.hooks.setdefault(name, []).append(callback)

    def register_tool(self, *, name: str, schema: dict, **_kw) -> None:
        with self._lock:
            self.tools.append((name, schema))

    def register_command(self, name: str, handler: Callable, **_kw) -> None:
        with self._lock:
            self.commands.append((name, getattr(handler, "__name__", "<fn>")))

    def register_cli_command(self, name: str, **_kw) -> None:
        with self._lock:
            self.cli_commands.append(name)

    def register_memory_provider(self, provider) -> None:
        with self._lock:
            self.tools.append(("memory_provider", {"name": provider.name}))


def make_ctx() -> _RecordingCtx:
    return _RecordingCtx()


def install_observer_plugin(ctx) -> dict:
    """A read-only observer plugin: registers post_tool_call only."""
    state = {"calls": 0, "last_tool": "", "kwargs_seen": []}

    def cb(*, tool_name: str = "", args=None, result=None, **_kw) -> None:
        state["calls"] += 1
        state["last_tool"] = tool_name
        state["kwargs_seen"].append({"tool_name": tool_name, "args": args, "result": result})

    ctx.register_hook("post_tool_call", cb)
    return state


def install_command_plugin(ctx, name: str = "fake_cmd") -> dict:
    state = {"called": False, "raw_args": ""}

    def handler(raw_args: str = "") -> str:
        state["called"] = True
        state["raw_args"] = raw_args
        return "fake-cmd ok"

    ctx.register_command(name, handler, description="fake command for tests")
    return state


def install_failing_plugin(ctx, *, fail_at: str = "post_tool_call") -> dict:
    """A plugin that intentionally raises in its hook to test failure isolation."""
    state = {"raised_count": 0}

    def cb(**_kw) -> None:
        state["raised_count"] += 1
        raise RuntimeError("intentional failure from fake plugin")

    ctx.register_hook(fail_at, cb)
    return state


def install_storage_writer(ctx, *, path) -> dict:
    """A plugin that writes its own files under HERMES_HOME / data / fake_plugin / ."""
    state = {"writes": 0, "path": str(path)}

    def cb(*, session_id: str = "", **_kw) -> None:
        state["writes"] += 1
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fake-plugin-write count={state['writes']} sess={session_id}\n")

    ctx.register_hook("on_session_finalize", cb)
    return state


def install_lifecycle_plugin(ctx) -> dict:
    """Records every lifecycle event the plugin runtime fires for it."""
    state = {"events": []}

    def make_cb(name: str):
        def cb(**kwargs) -> None:
            state["events"].append((name, dict(kwargs)))

        return cb

    for hook in ("on_session_start", "on_session_end", "on_session_reset", "on_session_finalize"):
        ctx.register_hook(hook, make_cb(hook))
    return state
