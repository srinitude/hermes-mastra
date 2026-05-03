"""Config + path helpers for the Mastra server.

Everything here is pure: no subprocess spawning, no network. Splitting this
out keeps `server_process.py` (which DOES spawn) testable in isolation.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_PORT = 4191
DEFAULT_HOST = "127.0.0.1"
SERVER_DIR = Path(__file__).parent / "server"


def _hermes_home() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home())


def config_path() -> Path:
    return _hermes_home() / "mastra.json"


def pid_file() -> Path:
    return _hermes_home() / "mastra.pid"


def log_file() -> Path:
    log_dir = _hermes_home() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "mastra.log"


def _builtin_defaults() -> dict:
    home = _hermes_home()
    return {
        "server_url": os.environ.get("MASTRA_URL") or f"http://{DEFAULT_HOST}:{DEFAULT_PORT}",
        "server_host": DEFAULT_HOST,
        "server_port": DEFAULT_PORT,
        "auto_start": True,
        "server_per_profile": False,
        "db_path": str(home / "mastra.db"),
        # Legacy single-model fallback used only when role-specific
        # observer_*/reflector_* keys are unset.
        "model_url": "https://api.venice.ai/api/v1",
        "model_name": "gemini-3-flash-preview",
        "model_api_key_env": "VENICE_API_KEY",
        # Split observer/reflector — see model_config.py.
        "observer_url": "https://api.venice.ai/api/v1",
        "observer_name": "gemini-3-flash-preview",
        "observer_api_key_env": "VENICE_API_KEY",
        "reflector_url": "https://api.venice.ai/api/v1",
        "reflector_name": "gemini-3-1-pro-preview",
        "reflector_api_key_env": "VENICE_API_KEY",
        "recall_top_k": 4,
        "recall_token_budget": 1500,
        "temporal_markers": True,
        "share_token_budget": False,
        "auth_token_env": "MASTRA_API_KEY",
    }


def load_config() -> dict:
    """Built-in defaults overlaid with $HERMES_HOME/mastra.json + env."""
    cfg = _builtin_defaults()
    p = config_path()
    if p.exists():
        try:
            user = json.loads(p.read_text(encoding="utf-8"))
            cfg.update({k: v for k, v in user.items() if v not in (None, "")})
        except Exception as exc:  # pragma: no cover
            logger.warning("mastra: failed to parse %s: %s", p, exc)
    if os.environ.get("MASTRA_URL"):
        cfg["server_url"] = os.environ["MASTRA_URL"]
    return cfg


def save_config(values: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    existing.update(values)
    p.write_text(json.dumps(existing, indent=2), encoding="utf-8")


def is_port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def read_pid() -> int | None:
    p = pid_file()
    if not p.exists():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def write_pid(pid: int) -> None:
    pid_file().write_text(str(pid), encoding="utf-8")


def clear_pid() -> None:
    p = pid_file()
    if p.exists():
        p.unlink(missing_ok=True)
