"""Pytest fixtures shared across the suite.

Every test gets:
  * an isolated $HERMES_HOME (tmp dir) — no test ever touches the real ~/.hermes
  * the plugin's source directory on sys.path so we can `import client`,
    `import server_manager`, `import model_config`, etc. directly without an
    install step (matches how Hermes loads the plugin at runtime).
  * a clean process env with the MASTRA_* vars cleared so defaults apply.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Make the plugin source importable as top-level modules. This mirrors how
# Hermes loads the plugin: via importlib spec_from_file_location, where
# `from .client import ...` resolves through sys.modules registration.
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


@pytest.fixture
def fake_hermes_home(tmp_path, monkeypatch):
    """Isolated $HERMES_HOME — every test gets a fresh empty dir."""
    home = tmp_path / "hermes_home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))

    # The plugin reads HERMES_HOME via hermes_constants.get_hermes_home().
    # In CI / non-Hermes environments that module isn't importable, so we
    # provide a stub.
    if "hermes_constants" not in sys.modules:
        import types

        stub = types.ModuleType("hermes_constants")
        stub.get_hermes_home = lambda: home  # type: ignore[attr-defined]
        sys.modules["hermes_constants"] = stub
    else:
        sys.modules["hermes_constants"].get_hermes_home = lambda: home  # type: ignore[attr-defined]

    yield home


@pytest.fixture(autouse=True)
def _scrub_mastra_env(monkeypatch):
    """Clear MASTRA_* env vars so defaults are deterministic per test."""
    for key in list(os.environ):
        if key.startswith("MASTRA_"):
            monkeypatch.delenv(key, raising=False)
    # Also scrub keys we use as defaults so model-config tests start from zero.
    for key in ("VENICE_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    yield
