"""B00 — per-test Mastra server fixture + shared deterministic test config.

Provides:
  * ``mastra_server``   (session-scoped): spawns the Bun/Hono Mastra server
    once per pytest session against an isolated $HERMES_HOME, using
    ``test_mastra.json`` as the deterministic template (Observer/Reflector
    via Venice; semantic embedder = OpenAI when available, otherwise Google AI
    via ``GEMINI_API_KEY`` mapped to both Google API key env names).
  * ``mastra_client``   (function-scoped): yields a fresh ``MastraClient``
    bound to that server.

Tests that need the live server opt in via ``pytest.mark.integration``;
default ``mise run test`` does NOT spawn the server.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import types
from pathlib import Path
from typing import Any

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

TEMPLATE_PATH = Path(__file__).resolve().parent / "test_mastra.json"


def _free_port() -> int:
    """Return an OS-assigned free localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _dotenv_value(key: str) -> str:
    env_path = Path.home() / ".hermes" / ".env"
    if not env_path.exists():
        return ""
    prefix = f"{key}="
    for raw in env_path.read_text(errors="ignore").splitlines():
        line = raw.strip().removeprefix("export ")
        if line.startswith(prefix):
            return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def _env_value(*keys: str) -> str:
    for key in keys:
        value = os.environ.get(key) or _dotenv_value(key)
        if value:
            return value
    return ""


def _provider_keys_present() -> bool:
    """Live server needs Venice plus one supported embedding key."""
    embedder_key = _env_value(
        "OPENAI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"
    )
    return bool(_env_value("VENICE_API_KEY") and embedder_key)


def _bun_present() -> bool:
    return bool(shutil.which("bun"))


def _server_deps_ready() -> bool:
    return (PLUGIN_ROOT / "server" / "node_modules").is_dir()


def _resolve_google_key() -> str:
    return _env_value("GOOGLE_GENERATIVE_AI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY")


def _resolve_openai_key() -> str:
    return _env_value("OPENAI_API_KEY")


def _load_template() -> dict[str, Any]:
    return json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))


def _materialize_config(home: Path, port: int) -> Path:
    """Write the deterministic test mastra.json into HERMES_HOME with a real port."""
    cfg = _load_template()
    cfg["server_url"] = f"http://127.0.0.1:{port}"
    cfg["server_port"] = port
    cfg["db_path"] = str(home / "mastra.db")
    out = home / "mastra.json"
    out.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return out


def _install_hermes_constants_module(home: Path) -> None:
    """Make server_config._hermes_home() resolvable in pytest sys.path mode."""
    if "hermes_constants" not in sys.modules:
        constants_module = types.ModuleType("hermes_constants")
        constants_module.get_hermes_home = lambda: home  # type: ignore[attr-defined]
        sys.modules["hermes_constants"] = constants_module
    else:
        sys.modules["hermes_constants"].get_hermes_home = lambda: home  # type: ignore[attr-defined]


def _wire_server_env(home: Path) -> None:
    """Set HERMES_HOME and choose the live embedder with available quota."""
    os.environ["HERMES_HOME"] = str(home)
    venice_key = _env_value("VENICE_API_KEY")
    if venice_key and "VENICE_API_KEY" not in os.environ:
        os.environ["VENICE_API_KEY"] = venice_key
    openai_key = _resolve_openai_key()
    if openai_key and "OPENAI_API_KEY" not in os.environ:
        os.environ["OPENAI_API_KEY"] = openai_key
    google_key = _resolve_google_key()
    if google_key and "GOOGLE_GENERATIVE_AI_API_KEY" not in os.environ:
        os.environ["GOOGLE_GENERATIVE_AI_API_KEY"] = google_key
    if google_key and "GOOGLE_API_KEY" not in os.environ:
        os.environ["GOOGLE_API_KEY"] = google_key
    current_model = os.environ.get("MASTRA_EMBEDDER_MODEL", "")
    if openai_key and (not current_model or current_model.startswith("google/")):
        os.environ["MASTRA_EMBEDDER_MODEL"] = "openai/text-embedding-3-small"
    elif not current_model:
        os.environ["MASTRA_EMBEDDER_MODEL"] = "google/gemini-embedding-001"


def _start_or_skip(wait_seconds: float) -> tuple[bool, str]:
    try:
        from server_manager import start_server
    except ImportError as exc:
        pytest.skip(f"server_manager unavailable: {exc}")
    return start_server(wait_seconds=wait_seconds)


def _stop_server_quiet() -> None:
    try:
        from server_manager import stop_server
    except ImportError:
        return
    stop_server()


def _live_prereqs_or_skip() -> None:
    if not _bun_present():
        pytest.skip("bun not in PATH; live Mastra server fixture skipped")
    if not _server_deps_ready():
        pytest.skip("server/node_modules missing; run `mise run install`")
    if not _provider_keys_present():
        pytest.skip("VENICE_API_KEY plus OPENAI/GOOGLE/GEMINI key required for live server")


def _saved_server_env() -> dict[str, str | None]:
    keys = (
        "HERMES_HOME",
        "VENICE_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "GOOGLE_API_KEY",
        "MASTRA_EMBEDDER_MODEL",
        "OPENAI_API_KEY",
    )
    return {k: os.environ.get(k) for k in keys}


def _restore_env(saved_env: dict[str, str | None]) -> None:
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _ensure_session_server_running() -> None:
    """Restart the session Mastra server if R07 (or another test) stopped it."""
    try:
        from server_manager import is_running, start_server
    except ImportError as exc:
        pytest.skip(f"server_manager unavailable: {exc}")
    if not is_running():
        ok, msg = start_server(wait_seconds=12.0)
        if not ok:
            pytest.skip(f"mastra server failed to restart: {msg}")


def _build_mastra_client(base_url: str, home_basename: str):
    """Construct a MastraClient against the live session server."""
    try:
        from client import MastraClient
    except ImportError as exc:
        pytest.skip(f"client unavailable: {exc}")
    return MastraClient(base_url, home_basename=home_basename)


@pytest.fixture(scope="session")
def mastra_server(tmp_path_factory):
    """Spawn the Bun/Hono Mastra server once per pytest session."""
    _live_prereqs_or_skip()
    home = tmp_path_factory.mktemp("hermes_home_mastra")
    (home / "logs").mkdir()
    port = _free_port()
    _materialize_config(home, port)
    saved_env = _saved_server_env()
    _wire_server_env(home)
    _install_hermes_constants_module(home)

    ok, msg = _start_or_skip(wait_seconds=12.0)
    if not ok:
        pytest.skip(f"mastra server failed to start: {msg}")
    try:
        yield {"base_url": f"http://127.0.0.1:{port}", "home": home, "port": port}
    finally:
        _stop_server_quiet()
        _restore_env(saved_env)


@pytest.fixture
def mastra_client(mastra_server):
    """Per-test MastraClient bound to the live session server.

    Carries the same ``home_basename`` the provider's bring-up uses so
    the boundary scoping installed in G02 (per-home resourceId) keeps
    test reads aligned with provider writes when no override is set.

    Function-scoped: rewires the session HERMES_HOME / API-key /
    embedder env (other tests may have monkeypatched them or overridden
    ``hermes_constants.get_hermes_home``), reinstalls the
    ``hermes_constants`` module shim, and restarts the session server
    if R07 (or any other test) has stopped it. The session-scoped
    fixture is left untouched so its setup/teardown invariants hold.
    """
    home = Path(str(mastra_server["home"]))
    _wire_server_env(home)
    _install_hermes_constants_module(home)
    _ensure_session_server_running()
    c = _build_mastra_client(mastra_server["base_url"], home_basename=home.name)
    try:
        yield c
    finally:
        c.close()
