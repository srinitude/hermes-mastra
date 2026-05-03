"""Integration test for the `register(ctx)` -> ContextEngine wiring.

Confirms the plugin only registers a context engine when:
  - the host gateway/CLI exposes `register_context_engine`, AND
  - the user has not disabled it via `context_engine_wrapper: false`.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any, Optional

import pytest


class _FakeCtx:
    """In-memory plugin context capturing every register_* call."""

    def __init__(self, has_engine_register: bool = True) -> None:
        self.memory_provider = None
        self.context_engine = None
        self.hooks: dict[str, Any] = {}
        if has_engine_register:
            self.register_context_engine = self._register_context_engine

    def register_memory_provider(self, provider) -> None:
        self.memory_provider = provider

    def _register_context_engine(self, engine) -> None:
        self.context_engine = engine

    def register_hook(self, name: str, cb) -> None:
        self.hooks[name] = cb


@pytest.fixture
def patched_load_config(monkeypatch):
    """Stub server_manager.load_config so register() doesn't read disk.

    Patches every server_manager module currently in sys.modules — the
    plugin imports relative-first (`from .server_manager import …`)
    which loads a *new* package-scoped copy when we exec the plugin
    __init__ via spec_from_file_location.  So we patch the top-level
    one now and do a second sweep just before each test runs the plugin.
    """
    cfg_box = {"value": {}}

    def _stub_load_config():
        return dict(cfg_box["value"])

    def _set(cfg: dict) -> None:
        cfg_box["value"] = dict(cfg)
        # Patch both already-imported and any future copies.
        for mod_name, mod in list(sys.modules.items()):
            if mod_name.endswith("server_manager") and hasattr(mod, "load_config"):
                monkeypatch.setattr(mod, "load_config", _stub_load_config, raising=True)

    _set({})
    return _set


@pytest.fixture
def stub_compressor(monkeypatch):
    """Substitute a minimal ContextCompressor stub so tests don't need
    Hermes' heavyweight transitive deps (requests, anthropic, etc.).

    The wrapper only calls the delegate's methods at compress time; for
    register() we just need the constructor to succeed.
    """
    import types

    try:
        from agent.context_engine import ContextEngine
    except ImportError:  # pragma: no cover — Hermes not installed in CI

        class ContextEngine:  # type: ignore[no-redef]
            pass

    class _StubCompressor(ContextEngine):
        def __init__(self, model: str = "x", **_kwargs) -> None:
            self.model = model
            self.threshold_tokens = 100_000
            self.context_length = 200_000

        @property
        def name(self) -> str:
            return "compressor"

        def update_from_response(self, usage):  # pragma: no cover
            pass

        def should_compress(self, prompt_tokens=None):  # pragma: no cover
            return False

        def compress(self, messages, **_):  # pragma: no cover
            return messages

    fake_module = types.ModuleType("agent.context_compressor")
    fake_module.ContextCompressor = _StubCompressor
    monkeypatch.setitem(sys.modules, "agent.context_compressor", fake_module)
    return _StubCompressor


def _fresh_plugin_module():
    """Import the plugin's __init__.py as a top-level module under a fresh name.

    The plugin uses relative imports inside __init__ which only work when
    loaded via importlib.spec_from_file_location with submodule_search_locations.
    For tests we already have the source dir on sys.path (via tests/conftest.py)
    so individual modules import as top-level — but `register()` itself lives
    in __init__.py, which collect_ignore stops pytest from picking up.  We
    load it manually here under a unique name so each test gets a clean
    instance (avoids the disabled-flag test seeing the previous test's
    cached module).
    """
    import uuid
    from pathlib import Path

    plugin_root = Path(__file__).resolve().parents[1]
    init = plugin_root / "__init__.py"
    mod_name = f"mastra_plugin_under_test_{uuid.uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(
        mod_name,
        str(init),
        submodule_search_locations=[str(plugin_root)],
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_register_installs_context_engine_when_enabled(patched_load_config, stub_compressor):
    plugin = _fresh_plugin_module()
    patched_load_config({"context_engine_wrapper": True})  # patch after load
    ctx = _FakeCtx(has_engine_register=True)
    plugin.register(ctx)
    assert ctx.memory_provider is not None
    assert ctx.context_engine is not None
    # Name override matches what the user puts in config.yaml.
    assert ctx.context_engine.name == "mastra"


def test_register_skips_context_engine_when_disabled(patched_load_config, stub_compressor):
    plugin = _fresh_plugin_module()
    patched_load_config({"context_engine_wrapper": False})
    ctx = _FakeCtx(has_engine_register=True)
    plugin.register(ctx)
    assert ctx.memory_provider is not None
    assert ctx.context_engine is None


def test_register_skips_context_engine_when_host_lacks_hook(patched_load_config, stub_compressor):
    plugin = _fresh_plugin_module()
    patched_load_config({"context_engine_wrapper": True})
    ctx = _FakeCtx(has_engine_register=False)
    plugin.register(ctx)
    assert ctx.memory_provider is not None
    assert getattr(ctx, "context_engine", None) is None
