"""Hermes-context import contract.

The plugin is loaded by Hermes via ``importlib.import_module`` as
``plugins.memory.mastra``. Submodule imports therefore MUST resolve as
either relative imports (``from . import foo``) or be guarded by a
``try/except ImportError`` fallback to absolute names.

A bare ``from server_config import ...`` works under pytest only because
``conftest.py`` puts the plugin root on sys.path. Under the real Hermes
loader it raises ``ModuleNotFoundError`` and ``is_available()`` silently
returns ``False`` — looking healthy in tests but no-op in production.

These tests run each import in a **subprocess** so in-process sys.path
and sys.modules state can't leak into the rest of the suite.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "plugins.memory.mastra"


def _build_hermes_loader_bootstrap(body: str) -> str:
    """Construct the subprocess bootstrap that simulates the Hermes loader.

    Sets up a synthetic ``plugins.memory.mastra`` package (via symlink to
    this plugin source) so imports resolve under the same package context
    Hermes uses. The plugin root is NOT on sys.path, so bare absolute
    sibling imports must fail — exactly the production constraint.
    """
    return textwrap.dedent(
        f"""
        import os, sys, tempfile, shutil
        from pathlib import Path
        plugin_root = Path({str(PLUGIN_ROOT)!r}).resolve()
        tmp = Path(tempfile.mkdtemp())
        try:
            fake = tmp / "plugins" / "memory"
            fake.mkdir(parents=True)
            (tmp / "plugins" / "__init__.py").write_text("")
            (fake / "__init__.py").write_text("")
            (fake / "mastra").symlink_to(plugin_root)
            sys.path.insert(0, str(tmp))
            os.environ["HERMES_HOME"] = str(tmp / "home")
            os.makedirs(os.environ["HERMES_HOME"], exist_ok=True)
            """
        + textwrap.indent(body, " " * 12)
        + """
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    """
    )


def _run_in_clean_subprocess(body: str) -> subprocess.CompletedProcess:
    """Run *body* under the synthetic Hermes loader context."""
    bootstrap = _build_hermes_loader_bootstrap(body)
    return subprocess.run(
        [sys.executable, "-c", bootstrap],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_package_imports_under_hermes_loader_path():
    """``import plugins.memory.mastra`` succeeds under the package context."""
    body = textwrap.dedent("""
        import importlib
        mod = importlib.import_module("plugins.memory.mastra")
        assert hasattr(mod, "register"), "missing register(ctx)"
        assert hasattr(mod, "MastraMemoryProvider"), "missing class"
        print("OK")
    """)
    r = _run_in_clean_subprocess(body)
    assert r.returncode == 0, f"stdout:{r.stdout}\nstderr:{r.stderr}"
    assert "OK" in r.stdout


def test_is_available_does_not_raise_under_hermes_loader():
    """``is_available()`` MUST NOT raise under the package context."""
    body = textwrap.dedent("""
        import importlib
        mod = importlib.import_module("plugins.memory.mastra")
        p = mod.MastraMemoryProvider()
        result = p.is_available()
        assert isinstance(result, bool), f"not a bool: {result!r}"
        print("OK", result)
    """)
    r = _run_in_clean_subprocess(body)
    assert r.returncode == 0, f"stdout:{r.stdout}\nstderr:{r.stderr}"
    assert "OK" in r.stdout


def test_server_manager_resolves_under_hermes_loader():
    """server_manager (back-compat shim) imports cleanly under package."""
    body = textwrap.dedent("""
        import importlib
        mod = importlib.import_module("plugins.memory.mastra.server_manager")
        for name in ("find_bun", "load_config", "ensure_running",
                     "start_server", "install_dependencies"):
            assert hasattr(mod, name), f"server_manager missing {name!r}"
        print("OK")
    """)
    r = _run_in_clean_subprocess(body)
    assert r.returncode == 0, f"stdout:{r.stdout}\nstderr:{r.stderr}"


def test_provider_lifecycle_resolves_under_hermes_loader():
    """provider_lifecycle is the busiest hot-path module — must import."""
    body = textwrap.dedent("""
        import importlib
        mod = importlib.import_module("plugins.memory.mastra.provider_lifecycle")
        for name in ("do_initialize", "do_prefetch", "do_sync_turn",
                     "do_session_switch", "do_pre_compress",
                     "do_session_end", "do_memory_write",
                     "do_delegation", "do_turn_start"):
            assert hasattr(mod, name), f"provider_lifecycle missing {name!r}"
        print("OK")
    """)
    r = _run_in_clean_subprocess(body)
    assert r.returncode == 0, f"stdout:{r.stdout}\nstderr:{r.stderr}"


def test_load_memory_provider_via_hermes_helper_smoke():
    """End-to-end smoke: plugins.memory.load_memory_provider('mastra')
    via Hermes' actual venv, exactly mirroring its runtime call."""
    hermes_root = Path.home() / ".hermes" / "hermes-agent"
    venv_python = hermes_root / "venv" / "bin" / "python"
    if not venv_python.exists():
        pytest.skip("Hermes venv not found on this machine")
    code = (
        "from plugins.memory import load_memory_provider; "
        "p = load_memory_provider('mastra'); "
        "assert p, 'failed to load'; "
        "ok = p.is_available(); "
        "assert isinstance(ok, bool); "
        "print('is_available=' + str(ok))"
    )
    # Pin HERMES_HOME to the real home so the loader scans the installed
    # ~/.hermes/plugins/. Other fixtures (mastra_server) set HERMES_HOME to
    # a temp dir without restoring it; the child inherits os.environ, so an
    # explicit value keeps this subprocess independent of suite ordering.
    import os as _os

    child_env = dict(_os.environ)
    child_env["HERMES_HOME"] = str(Path.home() / ".hermes")
    result = subprocess.run(
        [str(venv_python), "-c", code],
        capture_output=True,
        text=True,
        cwd=str(hermes_root),
        timeout=30,
        check=False,
        env=child_env,
    )
    assert result.returncode == 0, (
        f"plugin failed under Hermes venv:\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
