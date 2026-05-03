"""Shared test helpers for the non-blocking-hook suite."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

PKG_ROOT = Path(__file__).resolve().parents[1]


def _stub_module(name: str, **attrs) -> None:
    if name in sys.modules:
        return
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod


def _ensure_hermes_stubs() -> None:
    _stub_module("agent")
    _stub_module(
        "agent.memory_provider",
        MemoryProvider=type("_StubMemoryProvider", (), {}),
    )
    _stub_module("tools")
    _stub_module("tools.registry", tool_error=lambda msg: f'{{"error":"{msg}"}}')


def _import_provider_module():
    """Make the package importable as plain top-level modules."""
    if str(PKG_ROOT) not in sys.path:
        sys.path.insert(0, str(PKG_ROOT))
    # ``provider.py`` re-exports the class via absolute imports — no
    # spec_from_file_location magic needed. Force a fresh import so test
    # isolation is preserved across modules that mutate sys.modules.
    sys.modules.pop("provider", None)
    import provider

    return provider


def make_provider(slow_client: MagicMock):
    """Build the provider with a slow mock client; bypass real network init."""
    _ensure_hermes_stubs()
    mod = _import_provider_module()
    p = mod.MastraMemoryProvider()
    p._client = slow_client
    p._cfg = {"recall_top_k": 4}
    p._profile = "test-profile"
    p._thread = "test-thread"
    p._cron_skipped = False
    return p
