"""Plugin clash analysis enforcement.

Every claim made in ``analysis/plugin-clash-analysis.md`` is encoded as
an executable test here. If anyone changes a namespace, registers a
new resource, or drops a stable prefix, this suite breaks.

The plugin contract requires explicit, stable, collision-resistant
names for every plugin-owned resource. These tests assert that.
"""

from __future__ import annotations

import logging
import re

import pytest

# --- 1. plugin identity --------------------------------------------------


def test_canonical_plugin_id_stable():
    """plugin.yaml name + provider.name + tool prefix are all 'mastra'."""
    from pathlib import Path

    import yaml

    repo_root = Path(__file__).resolve().parents[1]
    manifest = yaml.safe_load((repo_root / "plugin.yaml").read_text())
    assert manifest["name"] == "mastra", "plugin.yaml name drift"

    from provider import MastraMemoryProvider

    p = MastraMemoryProvider()
    assert p.name == "mastra", "provider.name drift — clash analysis broken"


def test_provider_name_is_mastra(fake_hermes_home):
    from provider import MastraMemoryProvider

    assert MastraMemoryProvider().name == "mastra"


# --- 2. tool-name namespace ---------------------------------------------


def test_all_tool_names_are_namespaced():
    """Every exposed tool name MUST start with 'mastra_'."""
    from tool_schemas import (
        ARTIFACT_GET_SCHEMA,
        ARTIFACT_HISTORY_SCHEMA,
        ARTIFACT_REVERT_SCHEMA,
        OBSERVE_SCHEMA,
        RECALL_SCHEMA,
        SEARCH_SCHEMA,
        SEMANTIC_SEARCH_SCHEMA,
        WORKING_MEMORY_GET_SCHEMA,
    )

    for s in (
        RECALL_SCHEMA,
        OBSERVE_SCHEMA,
        SEARCH_SCHEMA,
        SEMANTIC_SEARCH_SCHEMA,
        WORKING_MEMORY_GET_SCHEMA,
        ARTIFACT_GET_SCHEMA,
        ARTIFACT_HISTORY_SCHEMA,
        ARTIFACT_REVERT_SCHEMA,
    ):
        assert s["name"].startswith("mastra_"), (
            f"Tool name {s['name']!r} is not namespaced — clash risk"
        )


# --- 3. hook callbacks are observers, not mutators ----------------------


def test_hook_callbacks_are_observers_only(fake_hermes_home):
    """Calling our post_tool_call callback must NOT mutate the kwargs dict."""
    from unittest.mock import MagicMock

    from hermes_wiring import activate_for
    from tests.helpers import make_provider

    p = make_provider(MagicMock())
    cb = activate_for(p)["post_tool_call"]

    args = {"name": "plan", "_immutable_marker": object()}
    result = '{"name":"plan"}'
    args_before = dict(args)
    cb(tool_name="skill_view", args=args, result=result)
    assert args == args_before, "post_tool_call mutated the kwargs dict"
    p.shutdown()


def test_pre_tool_call_callback_is_pure_noop(fake_hermes_home):
    """Our pre_tool_call returns None and inspects nothing."""
    from unittest.mock import MagicMock

    from hermes_wiring import activate_for
    from tests.helpers import make_provider

    p = make_provider(MagicMock())
    cb = activate_for(p)["pre_tool_call"]
    out = cb(tool_name="any_tool", args={"x": 1})
    assert out is None
    p.shutdown()


# --- 4. command / cli-command surfaces empty ----------------------------


def test_no_cli_command_registration():
    """Source-level grep: __init__.py never calls register_cli_command."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    src = (repo_root / "__init__.py").read_text()
    assert "register_cli_command" not in src


def test_no_slash_command_registration():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    src = (repo_root / "__init__.py").read_text()
    assert "register_command(" not in src


# --- 5. env-var namespace ownership -------------------------------------


def test_env_var_namespace_ownership():
    """Every MASTRA_* env we read or document must use the MASTRA_ prefix."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    cfg_ts = (repo_root / "server" / "src" / "config.ts").read_text()

    pattern = re.compile(r"process\.env\.([A-Z_]+)")
    used = set(pattern.findall(cfg_ts))
    # Subtract reserved third-party names we deliberately read
    reserved = {"VENICE_API_KEY"}
    leaked = {n for n in used - reserved if not n.startswith("MASTRA_")}
    assert not leaked, f"server/src/config.ts reads non-namespaced env vars: {leaked}"


# --- 6. storage / DB namespace ------------------------------------------


def test_storage_namespace_is_hermes_mastra():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    src = (repo_root / "server" / "src" / "resources.ts").read_text()
    assert 'id: "hermes-mastra"' in src or "id: 'hermes-mastra'" in src, (
        "LibSQLStore id namespace drifted from 'hermes-mastra'"
    )


def test_resource_id_format_is_hermes_profile():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    src = (repo_root / "server" / "src" / "config.ts").read_text()
    assert "`hermes:${profile" in src, "resourceFor() drifted from 'hermes:<profile>'"


# --- 7. recall cache is instance-scoped ---------------------------------


def test_recall_cache_is_instance_scoped(fake_hermes_home):
    from provider import MastraMemoryProvider

    a = MastraMemoryProvider()
    b = MastraMemoryProvider()
    a._recall_cache._text = "private to a"
    assert b._recall_cache.get() == "", "RecallCache leaked across instances"


# --- 8. async runner thread namespacing ---------------------------------


def test_async_runner_thread_names_namespaced():
    """Daemon thread names must start with 'mastra-runner-' so log filters work."""
    import async_runner

    # Touch the singleton so threads exist
    runner = async_runner.get_runner()
    names = [t.name for t in runner._workers]
    assert names, "no async_runner workers spawned"
    for n in names:
        assert n.startswith("mastra-runner-"), f"runner thread name '{n}' not namespaced"


# --- 9. logger names are module-scoped ----------------------------------


def test_logger_names_are_module_scoped():
    """Modules that own a logger must use ``__name__``-derived names so
    Hermes' log filtering can isolate this plugin's output cleanly."""
    import async_runner
    import client
    import provider_lifecycle
    import recall_cache

    for mod in (provider_lifecycle, async_runner, client, recall_cache):
        assert mod.logger.name == mod.__name__, (
            f"logger '{mod.logger.name}' diverged from module name '{mod.__name__}'"
        )


# --- 10. no monkey-patching of Hermes core modules ----------------------


def test_no_monkey_patching():
    """Source-level grep across the plugin: we never assign to any
    ``hermes_*``, ``agent.*``, or ``cli`` attribute, nor do we replace
    methods on imported Hermes modules."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    forbidden = re.compile(r"(setattr|monkeypatch)\s*\(\s*(hermes_|agent\.|cli\.|run_agent)")
    for py in repo_root.glob("*.py"):
        if py.name.startswith(("test_", "conftest")):
            continue
        text = py.read_text()
        match = forbidden.search(text)
        assert match is None, f"{py.name}: monkey-patches Hermes core via {match.group(0)!r}"


# --- 11. environment mutation scope -------------------------------------


def test_environment_mutation_scope(fake_hermes_home, tmp_path, monkeypatch):
    """do_initialize only writes os.environ['HERMES_HOME'] when caller
    supplied an override — never overwrites unrelated keys."""
    import os
    from unittest.mock import MagicMock

    from provider_lifecycle import do_initialize
    from tests.helpers import make_provider

    monkeypatch.setenv("UNRELATED_KEY", "must-not-change")
    p = make_provider(MagicMock())

    # Without override: os.environ['HERMES_HOME'] is whatever Hermes set.
    do_initialize(p, "sess-1")
    assert os.environ.get("UNRELATED_KEY") == "must-not-change"

    # With override: HERMES_HOME mutates eventually (background work);
    # but UNRELATED_KEY MUST stay untouched regardless.
    do_initialize(p, "sess-2", agent_identity="x", hermes_home=str(tmp_path))
    assert os.environ.get("UNRELATED_KEY") == "must-not-change"
    p.shutdown()


# --- 12. no skill / image_gen / platform registration -------------------


def test_no_skill_registration():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    src = (repo_root / "__init__.py").read_text()
    assert "register_skill" not in src


def test_no_image_gen_registration():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    src = (repo_root / "__init__.py").read_text()
    assert "register_image_gen_provider" not in src


def test_no_platform_registration():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[1]
    src = (repo_root / "__init__.py").read_text()
    assert "register_platform" not in src
